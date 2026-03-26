import asyncio
import logging
import queue
import threading
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from config import (
    CORS_ORIGINS, HOST, PORT, MAX_TEXT_LENGTH, MIN_SPEED, MAX_SPEED,
    MODEL_IDLE_TIMEOUT, PRESET_SPEAKERS, VALID_LANGUAGES,
)
from model_manager import ModelManager
from summarizer import Summarizer
from tts_engine import TTSEngine
from voice_manager import VoiceManager
from history import HistoryManager
from api_routes import router as api_router
from ssml_parser import is_ssml, inject_breaks, parse_ssml, SSMLDocument, SpeechSegment
from audio_ops import wav_to_mp3, wav_to_aac_fmp4, generate_fmp4_init, generate_silence, concatenate_wavs
from hls_manager import HLSManager
from telemetry import (
    init_telemetry, shutdown_telemetry, tracer, request_counter,
    summarize_duration, error_counter, input_chars, request_duration,
    stream_request_counter, stream_ttfb, hls_request_counter, hls_ttfb,
)

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_telemetry()

    manager = ModelManager(idle_timeout=MODEL_IDLE_TIMEOUT)
    app.state.model_manager = manager
    app.state.summarizer = Summarizer(manager)
    app.state.tts = TTSEngine(manager)
    app.state.voice_mgr = VoiceManager()
    app.state.history_mgr = HistoryManager()
    app.state.inference_lock = asyncio.Semaphore(1)
    app.state.hls_manager = HLSManager(ttl=300)

    idle_task = asyncio.create_task(manager.idle_checker(app.state.inference_lock))
    hls_cleanup_task = asyncio.create_task(_hls_cleanup_loop(app.state.hls_manager))

    # Preload pinned models so first request isn't slow
    await asyncio.to_thread(manager.preload_pinned)

    log.info("Server ready (idle timeout: %ds)", MODEL_IDLE_TIMEOUT)
    yield

    # Shutdown
    idle_task.cancel()
    hls_cleanup_task.cancel()
    manager.shutdown()
    shutdown_telemetry()
    log.info("All models unloaded.")


app = FastAPI(title="TTSQwen", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)

# Auto-instrument FastAPI (traces for all routes)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)


class SpeakRequest(BaseModel):
    text: str
    preset: str | None = None
    summarize: bool = True
    speaker: str | None = None
    language: str | None = None
    instruct: str | None = None
    speed: float | None = None
    voice: str | None = None
    summarize_prompt: str | None = None

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        if len(v) > MAX_TEXT_LENGTH:
            raise ValueError(f"text exceeds maximum length of {MAX_TEXT_LENGTH}")
        return v

    @field_validator("speed")
    @classmethod
    def speed_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (MIN_SPEED <= v <= MAX_SPEED):
            raise ValueError(f"speed must be between {MIN_SPEED} and {MAX_SPEED}")
        return v

    @field_validator("speaker")
    @classmethod
    def valid_speaker(cls, v: str | None) -> str | None:
        if v is not None and v not in PRESET_SPEAKERS:
            raise ValueError(f"unknown speaker: {v}")
        return v

    @field_validator("language")
    @classmethod
    def valid_language(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_LANGUAGES:
            raise ValueError(f"unsupported language: {v}")
        return v


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status(request: Request):
    manager = request.app.state.model_manager
    keep_alive = manager.keep_alive_remaining()
    resp = {
        "idle_timeout": MODEL_IDLE_TIMEOUT,
        "models": manager.status(),
    }
    if keep_alive > 0:
        resp["keep_alive_remaining"] = round(keep_alive, 0)
    return resp


@app.post("/keep-alive")
async def keep_alive(request: Request):
    """Prevent model unloading for a set number of hours."""
    body = await request.json()
    hours = body.get("hours", 1)
    if not isinstance(hours, (int, float)) or hours <= 0:
        raise HTTPException(400, "hours must be a positive number")
    manager = request.app.state.model_manager
    manager.keep_alive(hours)
    return {
        "keep_alive_hours": hours,
        "keep_alive_remaining": round(manager.keep_alive_remaining(), 0),
    }


@app.delete("/keep-alive")
async def cancel_keep_alive(request: Request):
    """Cancel keep-alive, resume normal idle unloading."""
    manager = request.app.state.model_manager
    manager.cancel_keep_alive()
    return {"keep_alive_remaining": 0}


@app.get("/help")
async def help_text(request: Request):
    from api_routes import _load_presets

    voices = request.app.state.voice_mgr.list_voices()
    presets = _load_presets()

    speakers = "\n".join(
        f"  - {name} ({meta['description']}, {meta['language']})"
        for name, meta in PRESET_SPEAKERS.items()
    )
    cloned = "\n".join(
        f"  - {v['name']}" for v in voices.get("cloned", [])
    ) or "  (none)"
    preset_lines = "\n".join(
        f"  - {p['name']}: speaker={p.get('speaker') or p.get('voice')}, "
        f"lang={p.get('language')}, speed={p.get('speed')}, summarize={p.get('summarize')}"
        for p in presets
    ) or "  (none)"
    langs = ", ".join(sorted(VALID_LANGUAGES))

    text = f"""\
TTSQwen — Text-to-Speech API
=============================

POST /speak
  Generate speech from text. Returns audio/wav.

  Request body (JSON):
    text      (string, required)  Text to synthesize (max {MAX_TEXT_LENGTH} chars)
    preset    (string)            Use a named preset (fills in all other fields)
    summarize (bool, default true) Condense text into spoken summary first
    speaker   (string)            Preset voice name (default: Aiden)
    voice     (string)            Cloned voice name (overrides speaker)
    language  (string)            {langs}
    instruct  (string)            Style instruction (e.g. "Calm, slow delivery")
    speed     (float)             Tempo multiplier ({MIN_SPEED}-{MAX_SPEED}, default 1.0)

  When using a preset, only text is required. Explicit fields override preset defaults.

  Response: audio/wav binary
  Response headers: X-Summarize-Time, X-TTS-Time, X-Spoken-Text

  Examples:
    # Using a preset (simplest)
    curl -X POST {request.base_url}speak \\
      -H "Content-Type: application/json" \\
      -d '{{"text": "Hello world", "preset": "Claude Response"}}' -o out.wav

    # Manual settings
    curl -X POST {request.base_url}speak \\
      -H "Content-Type: application/json" \\
      -d '{{"text": "Hello world", "summarize": false}}' -o out.wav

  SSML-like markup:
    Text can include tags for sound effects, pauses, and background audio.
    When tags are detected, summarization is automatically skipped.

    Tags (self-closing):
      <audio src="name"/>        Insert sound effect from server/sfx/
      <break time="500ms"/>      Insert silence (ms or s units, max 10s)
      <bg src="name" vol="0.15"/> Mix looped background audio underneath

    Example:
      The old man coughs. <audio src="cough"/> <break time="800ms"/>
      Then he whispers. <bg src="tavern" vol="0.12"/>

POST /speak/stream
  Same as /speak, but streams audio as MP3 chunks.
  Audio plays as it generates — lower time-to-first-byte.
  Falls back to buffered MP3 when background audio (<bg>) is used.
  Response: audio/mpeg (chunked transfer encoding)

POST /speak/hls
  Same as /speak, but returns HLS playlist for browser streaming.
  Response: JSON {{"session_id": "...", "playlist_url": "/hls/.../playlist.m3u8"}}
  Playlist grows as segments are generated. iOS Safari plays natively.
  Sessions expire after 5 minutes.

GET /hls/{{session_id}}/playlist.m3u8
  HLS playlist (EVENT type). Poll to discover new segments.

GET /hls/{{session_id}}/init.m4s
  fMP4 initialization segment (codec info).

GET /hls/{{session_id}}/{{index}}.m4s
  Individual fMP4 audio segment.

GET /api/sfx
  List available sound effect names for <audio> and <bg> tags.

GET /health
  Returns {{"status": "ok"}} when server is ready.

GET /status
  Returns model loading status, idle times, and keep-alive remaining.

POST /keep-alive
  Prevent model unloading for a set duration.
  Body: {{"hours": 2}}  (default: 1)

DELETE /keep-alive
  Cancel keep-alive, resume normal idle unloading.

GET /help
  This help text.

Preset speakers:
{speakers}

Cloned voices (use via "voice" field):
{cloned}

Presets (pre-configured combos):
{preset_lines}

Languages: {langs}

Speed guide:
  1.0x  Default, relaxed
  1.3x  Brisk, good for notifications
  1.5x  Background listening
  2.0x  Max for trained listeners

Tips:
  - Use summarize=true (default) for long/technical text
  - Use summarize=false for short text or exact wording
  - Male voices (Aiden, Ryan) handle higher speeds better
  - instruct controls delivery style, keep it short and descriptive
"""
    return PlainTextResponse(text)


@app.post("/speak")
async def speak(req: SpeakRequest, request: Request):
    _resolve_preset(req)

    summarizer = request.app.state.summarizer
    tts = request.app.state.tts
    lock = request.app.state.inference_lock

    voice_label = req.voice or req.speaker or "aiden"
    ssml_mode = is_ssml(req.text)
    if ssml_mode:
        req.summarize = False

    with tracer.start_as_current_span("speak", attributes={
        "tts.voice": voice_label,
        "tts.ssml": ssml_mode,
        "tts.summarize": req.summarize,
        "tts.input_chars": len(req.text),
    }) as span:
        async with lock:
            t0 = time.time()

            if ssml_mode:
                doc = parse_ssml(req.text)
                text = doc.plain_text()
                t_summarize = 0

                t1 = time.time()
                wav_bytes = await asyncio.to_thread(
                    tts.synthesize_ssml,
                    doc,
                    speaker=req.speaker,
                    language=req.language,
                    instruct=req.instruct,
                    speed=req.speed,
                    voice=req.voice,
                )
                t_tts = time.time() - t1
            else:
                if req.summarize and summarizer:
                    with tracer.start_as_current_span("summarize"):
                        text = await asyncio.to_thread(summarizer.summarize, req.text, req.language, req.summarize_prompt)
                    t_summarize = time.time() - t0
                    summarize_duration.record(t_summarize)
                    log.info("Summarized in %.2fs: %s...", t_summarize, text[:100])
                else:
                    text = req.text
                    t_summarize = 0

                # Auto-insert pauses at paragraph breaks
                text = inject_breaks(text)

                t1 = time.time()
                if is_ssml(text):
                    doc = parse_ssml(text)
                    wav_bytes = await asyncio.to_thread(
                        tts.synthesize_ssml,
                        doc,
                        speaker=req.speaker,
                        language=req.language,
                        instruct=req.instruct,
                        speed=req.speed,
                        voice=req.voice,
                    )
                    text = doc.plain_text()
                else:
                    wav_bytes = await asyncio.to_thread(
                        tts.synthesize,
                        text,
                        speaker=req.speaker,
                        language=req.language,
                        instruct=req.instruct,
                        speed=req.speed,
                        voice=req.voice,
                    )
                t_tts = time.time() - t1

        t_total = time.time() - t0
        request_counter.add(1, {"voice": voice_label, "endpoint": "/speak"})
        request_duration.record(t_total, {"voice": voice_label, "endpoint": "/speak"})
        input_chars.record(len(req.text), {"voice": voice_label})
        span.set_attribute("tts.generate_time", t_tts)
        span.set_attribute("tts.summarize_time", t_summarize)
        span.set_attribute("tts.request_time", t_total)
        span.set_attribute("tts.audio_bytes", len(wav_bytes))

        log.info("Request %.2fs (summarize=%.2fs tts=%.2fs), %d bytes", t_total, t_summarize, t_tts, len(wav_bytes))

        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "X-Summarize-Time": f"{t_summarize:.3f}",
                "X-TTS-Time": f"{t_tts:.3f}",
                "X-Spoken-Text": urllib.parse.quote(text[:200]),
            },
        )


def _resolve_preset(req: SpeakRequest):
    """Apply preset defaults to request (mutates req in place)."""
    if not req.preset:
        return
    from api_routes import _load_presets
    presets = _load_presets()
    p = next((p for p in presets if p["name"] == req.preset), None)
    if not p:
        return
    if req.speaker is None and req.voice is None:
        req.voice = p.get("voice")
        req.speaker = p.get("speaker")
    if req.language is None:
        req.language = p.get("language")
    if req.instruct is None:
        req.instruct = p.get("instruct", "")
    if req.speed is None:
        req.speed = p.get("speed")
    if req.summarize_prompt is None:
        req.summarize_prompt = p.get("summarize_prompt")
    req.summarize = p.get("summarize", req.summarize)


async def _preprocess_text(req: SpeakRequest, summarizer, lock) -> tuple[str, SSMLDocument, float]:
    """Summarize if needed, inject breaks, parse SSML. Returns (plain_text, doc, summarize_time)."""
    ssml_mode = is_ssml(req.text)
    if ssml_mode:
        req.summarize = False

    if ssml_mode:
        doc = parse_ssml(req.text)
        return doc.plain_text(), doc, 0.0

    t0 = time.time()
    if req.summarize and summarizer:
        async with lock:
            text = await asyncio.to_thread(summarizer.summarize, req.text, req.language, req.summarize_prompt)
        t_summarize = time.time() - t0
        summarize_duration.record(t_summarize)
        log.info("Summarized in %.2fs: %s...", t_summarize, text[:100])
    else:
        text = req.text
        t_summarize = 0.0

    text = inject_breaks(text)
    if is_ssml(text):
        doc = parse_ssml(text)
        return doc.plain_text(), doc, t_summarize
    else:
        doc = SSMLDocument(segments=[SpeechSegment(text=text)], background=None)
        return text, doc, t_summarize


@app.post("/speak/stream")
async def speak_stream(req: SpeakRequest, request: Request):
    _resolve_preset(req)

    summarizer = request.app.state.summarizer
    tts = request.app.state.tts
    lock = request.app.state.inference_lock

    voice_label = req.voice or req.speaker or "aiden"

    # Pre-processing (summarization) completes before streaming starts
    text, doc, t_summarize = await _preprocess_text(req, summarizer, lock)

    stream_request_counter.add(1, {"voice": voice_label})
    input_chars.record(len(req.text), {"voice": voice_label})

    # Background audio requires full foreground — fall back to buffered MP3
    if doc.background:
        async with lock:
            t1 = time.time()
            wav_bytes = await asyncio.to_thread(
                tts.synthesize_ssml, doc,
                speaker=req.speaker, language=req.language,
                instruct=req.instruct, speed=req.speed, voice=req.voice,
            )
            t_tts = time.time() - t1
        mp3_bytes = await asyncio.to_thread(wav_to_mp3, wav_bytes)
        log.info("Stream fallback (bg audio) %.2fs, %d bytes", t_tts, len(mp3_bytes))
        return Response(
            content=mp3_bytes,
            media_type="audio/mpeg",
            headers={
                "X-Summarize-Time": f"{t_summarize:.3f}",
                "X-TTS-Time": f"{t_tts:.3f}",
                "X-Spoken-Text": urllib.parse.quote(text[:200]),
            },
        )

    # Streaming path
    SENTINEL = object()
    cancel = threading.Event()
    q: queue.Queue = queue.Queue(maxsize=2)
    t_start = time.time()

    def _worker():
        try:
            chunk_idx = 0
            for wav_chunk in tts.synthesize_ssml_streaming(
                doc, speaker=req.speaker, language=req.language,
                instruct=req.instruct, speed=req.speed, voice=req.voice,
                cancel=cancel,
            ):
                t_enc = time.time()
                mp3_chunk = wav_to_mp3(wav_chunk)
                t_enc = time.time() - t_enc
                log.info(
                    "[Stream] chunk %d: wav=%dKB → mp3=%dKB (encode=%.2fs, elapsed=%.2fs)",
                    chunk_idx, len(wav_chunk) // 1024, len(mp3_chunk) // 1024,
                    t_enc, time.time() - t_start,
                )
                q.put(mp3_chunk)
                chunk_idx += 1
        except Exception as e:
            q.put(e)
        finally:
            q.put(SENTINEL)

    async def _generate():
        thread = threading.Thread(target=_worker, daemon=True)
        first = True
        chunk_count = 0
        total_bytes = 0
        async with lock:
            thread.start()
            try:
                while True:
                    item = await asyncio.to_thread(q.get)
                    if item is SENTINEL:
                        break
                    if isinstance(item, Exception):
                        log.error("Stream error: %s", item)
                        error_counter.add(1, {"voice": voice_label, "endpoint": "/speak/stream"})
                        break
                    if first:
                        ttfb = time.time() - t_start
                        stream_ttfb.record(ttfb, {"voice": voice_label})
                        log.info("[Stream] TTFB=%.2fs, voice=%s", ttfb, voice_label)
                        first = False
                    chunk_count += 1
                    total_bytes += len(item)
                    yield item
            finally:
                cancel.set()
                thread.join(timeout=10)

        t_total = time.time() - t_start
        log.info(
            "[Stream] complete: %d chunks, %dKB total, %.2fs, voice=%s",
            chunk_count, total_bytes // 1024, t_total, voice_label,
        )
        request_counter.add(1, {"voice": voice_label, "endpoint": "/speak/stream"})
        request_duration.record(t_total, {"voice": voice_label, "endpoint": "/speak/stream"})
        log.info("Stream complete %.2fs, voice=%s", t_total, voice_label)

    return StreamingResponse(
        _generate(),
        media_type="audio/mpeg",
        headers={
            "X-Summarize-Time": f"{t_summarize:.3f}",
            "X-Spoken-Text": urllib.parse.quote(text[:200]),
        },
    )


async def _hls_cleanup_loop(hls_mgr: HLSManager):
    """Periodically remove expired HLS sessions."""
    while True:
        await asyncio.sleep(60)
        n = hls_mgr.cleanup()
        if n:
            log.info("HLS cleanup: removed %d expired sessions", n)


async def _hls_worker(session_id, doc, req, tts, lock, hls_mgr):
    """Background task: generate audio segments and store in HLS session."""
    cancel = threading.Event()
    q: queue.Queue = queue.Queue(maxsize=2)
    SENTINEL = object()
    t_start = time.time()

    def _synth():
        try:
            init_data = generate_fmp4_init()
            q.put(("init", init_data))
            # Prepend 100ms silence to first chunk to absorb AAC priming delay
            silence_wav = generate_silence(100)
            first = True
            for wav_chunk in tts.synthesize_ssml_streaming(
                doc, speaker=req.speaker, language=req.language,
                instruct=req.instruct, speed=req.speed, voice=req.voice,
                cancel=cancel,
            ):
                if first:
                    wav_chunk = concatenate_wavs([silence_wav, wav_chunk])
                    first = False
                fmp4_bytes, duration = wav_to_aac_fmp4(wav_chunk)
                q.put((fmp4_bytes, duration))
        except Exception as e:
            q.put(e)
        finally:
            q.put(SENTINEL)

    async with lock:
        thread = threading.Thread(target=_synth, daemon=True)
        thread.start()
        first = True
        try:
            while True:
                item = await asyncio.to_thread(q.get)
                if item is SENTINEL:
                    break
                if isinstance(item, Exception):
                    log.error("[HLS] session %s error: %s", session_id, item)
                    hls_mgr.finish(session_id, error=str(item))
                    return
                if isinstance(item, tuple) and item[0] == "init":
                    hls_mgr.set_init(session_id, item[1])
                    log.info("[HLS] session %s: init segment (%dB)", session_id, len(item[1]))
                    continue
                fmp4_bytes, duration = item
                hls_mgr.add_segment(session_id, fmp4_bytes, duration)
                if first:
                    hls_ttfb.record(time.time() - t_start, {"voice": req.voice or req.speaker or "aiden"})
                    first = False
                log.info("[HLS] session %s: segment (%.1fs, %dKB, elapsed=%.2fs)",
                         session_id, duration, len(fmp4_bytes) // 1024, time.time() - t_start)
        finally:
            cancel.set()
            thread.join(timeout=10)

    hls_mgr.finish(session_id)
    log.info("[HLS] session %s complete (%.2fs)", session_id, time.time() - t_start)


@app.post("/speak/hls")
async def speak_hls(req: SpeakRequest, request: Request):
    _resolve_preset(req)

    summarizer = request.app.state.summarizer
    tts = request.app.state.tts
    lock = request.app.state.inference_lock
    hls_mgr = request.app.state.hls_manager

    voice_label = req.voice or req.speaker or "aiden"

    # Pre-processing (summarization) completes before returning
    text, doc, t_summarize = await _preprocess_text(req, summarizer, lock)

    hls_request_counter.add(1, {"voice": voice_label})
    input_chars.record(len(req.text), {"voice": voice_label})

    session_id = hls_mgr.create_session()

    # Background audio fallback: generate full audio as single segment
    if doc.background:
        async def _bg_fallback():
            async with lock:
                wav_bytes = await asyncio.to_thread(
                    tts.synthesize_ssml, doc,
                    speaker=req.speaker, language=req.language,
                    instruct=req.instruct, speed=req.speed, voice=req.voice,
                )
            init_data = await asyncio.to_thread(generate_fmp4_init)
            hls_mgr.set_init(session_id, init_data)
            fmp4_bytes, duration = await asyncio.to_thread(wav_to_aac_fmp4, wav_bytes)
            hls_mgr.add_segment(session_id, fmp4_bytes, duration)
            hls_mgr.finish(session_id)
        asyncio.create_task(_bg_fallback())
    else:
        asyncio.create_task(_hls_worker(session_id, doc, req, tts, lock, hls_mgr))

    return {
        "session_id": session_id,
        "playlist_url": f"/hls/{session_id}/playlist.m3u8",
        "summarize_time": round(t_summarize, 3),
        "spoken_text": text[:200],
    }


@app.get("/hls/{session_id}/playlist.m3u8")
async def hls_playlist(session_id: str, request: Request):
    hls_mgr = request.app.state.hls_manager
    playlist = hls_mgr.get_playlist(session_id)
    if playlist is None:
        raise HTTPException(404, "Session not found")
    return Response(
        content=playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/hls/{session_id}/init.m4s")
async def hls_init(session_id: str, request: Request):
    hls_mgr = request.app.state.hls_manager
    data = hls_mgr.get_init(session_id)
    if data is None:
        raise HTTPException(404, "Init segment not found")
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/hls/{session_id}/{index}.m4s")
async def hls_segment(session_id: str, index: int, request: Request):
    hls_mgr = request.app.state.hls_manager
    data = hls_mgr.get_segment(session_id, index)
    if data is None:
        raise HTTPException(404, "Segment not found")
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico")


# Mount static files last so routes take priority
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    # Suppress successful health check logs only
    import logging

    class HealthFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            return not ('"GET /health' in msg and '" 200 ' in msg)

    logging.getLogger("uvicorn.access").addFilter(HealthFilter())

    uvicorn.run(app, host=HOST, port=PORT)
