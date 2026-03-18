import asyncio
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
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
from ssml_parser import is_ssml, parse_ssml

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    manager = ModelManager(idle_timeout=MODEL_IDLE_TIMEOUT)
    app.state.model_manager = manager
    app.state.summarizer = Summarizer(manager)
    app.state.tts = TTSEngine(manager)
    app.state.voice_mgr = VoiceManager()
    app.state.history_mgr = HistoryManager()
    app.state.inference_lock = asyncio.Semaphore(1)

    idle_task = asyncio.create_task(manager.idle_checker(app.state.inference_lock))

    print(f"Server ready (models load on first use, idle timeout: {MODEL_IDLE_TIMEOUT}s)")
    yield

    # Shutdown
    idle_task.cancel()
    manager.shutdown()
    print("All models unloaded.")


app = FastAPI(title="TTSQwen", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


class SpeakRequest(BaseModel):
    text: str
    preset: str | None = None
    summarize: bool = True
    speaker: str | None = None
    language: str | None = None
    instruct: str | None = None
    speed: float | None = None
    voice: str | None = None

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
    # Resolve preset: preset fields are defaults, explicit fields override
    if req.preset:
        from api_routes import _load_presets
        presets = _load_presets()
        p = next((p for p in presets if p["name"] == req.preset), None)
        if p:
            if req.speaker is None and req.voice is None:
                req.voice = p.get("voice")
                req.speaker = p.get("speaker")
            if req.language is None:
                req.language = p.get("language")
            if req.instruct is None:
                req.instruct = p.get("instruct", "")
            if req.speed is None:
                req.speed = p.get("speed")
            req.summarize = p.get("summarize", req.summarize)

    summarizer = request.app.state.summarizer
    tts = request.app.state.tts
    lock = request.app.state.inference_lock

    ssml_mode = is_ssml(req.text)
    if ssml_mode:
        req.summarize = False

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
                text = await asyncio.to_thread(summarizer.summarize, req.text)
                t_summarize = time.time() - t0
                print(f"Summarized in {t_summarize:.2f}s: {text[:100]}...")
            else:
                text = req.text
                t_summarize = 0

            t1 = time.time()
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

    print(f"TTS in {t_tts:.2f}s, {len(wav_bytes)} bytes")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Summarize-Time": f"{t_summarize:.3f}",
            "X-TTS-Time": f"{t_tts:.3f}",
            "X-Spoken-Text": urllib.parse.quote(text[:200]),
        },
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
