import asyncio
import json
import secrets
import time
import wave
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from config import (
    MAX_TEXT_LENGTH, MIN_SPEED, MAX_SPEED, PRESET_SPEAKERS,
    TTS_INSTRUCT, TTS_LANGUAGE, TTS_SPEED, TTS_VOICE, VALID_LANGUAGES,
)
from ssml_parser import is_ssml, inject_breaks, parse_ssml
from audio_ops import list_sfx

router = APIRouter(prefix="/api")

PRESETS_FILE = Path(__file__).parent / "presets.json"


def _load_presets() -> list[dict]:
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_presets(presets: list[dict]):
    PRESETS_FILE.write_text(
        json.dumps(presets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _wav_duration(wav_bytes: bytes) -> float:
    import io
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / w.getframerate()


# ─── Config ───

@router.get("/config")
async def get_config():
    return {
        "default_speaker": TTS_VOICE,
        "default_language": TTS_LANGUAGE,
        "default_speed": TTS_SPEED,
        "default_instruct": TTS_INSTRUCT,
        "speakers": list(PRESET_SPEAKERS.keys()),
        "languages": ["English", "Chinese", "Japanese", "Korean", "Spanish"],
    }


# ─── SFX ───

@router.get("/sfx")
async def get_sfx():
    """List available sound effect names for SSML <audio> and <bg> tags."""
    return list_sfx()


# ─── Speak ───

@router.post("/speak")
async def api_speak(
    request: Request,
    text: str = Form(...),
    summarize: bool = Form(True),
    speaker: str = Form(None),
    language: str = Form(None),
    instruct: str = Form(""),
    speed: float = Form(1.0),
    voice: str = Form(None),
    preset: str = Form(None),
    summarize_prompt: str = Form(None),
):
    # Resolve preset defaults
    if preset:
        presets = _load_presets()
        p = next((px for px in presets if px["name"] == preset), None)
        if p:
            if not speaker and not voice:
                voice = p.get("voice")
                speaker = p.get("speaker")
            if not language:
                language = p.get("language")
            if not instruct:
                instruct = p.get("instruct", "")
            if speed == 1.0:
                speed = p.get("speed", 1.0)
            if not summarize_prompt:
                summarize_prompt = p.get("summarize_prompt")
            summarize = p.get("summarize", summarize)

    # Validate inputs
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=422, detail=f"text exceeds maximum length of {MAX_TEXT_LENGTH}")
    if not (MIN_SPEED <= speed <= MAX_SPEED):
        raise HTTPException(status_code=422, detail=f"speed must be between {MIN_SPEED} and {MAX_SPEED}")
    if speaker and speaker not in PRESET_SPEAKERS:
        raise HTTPException(status_code=422, detail=f"unknown speaker: {speaker}")
    if language and language not in VALID_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"unsupported language: {language}")

    tts = request.app.state.tts
    summarizer = request.app.state.summarizer
    history_mgr = request.app.state.history_mgr
    lock = request.app.state.inference_lock

    ssml_mode = is_ssml(text)
    if ssml_mode:
        summarize = False

    async with lock:
        t0 = time.time()
        text_input = text

        if ssml_mode:
            doc = parse_ssml(text)
            text_spoken = doc.plain_text()
            t_summarize = 0.0

            t1 = time.time()
            wav_bytes = await asyncio.to_thread(
                tts.synthesize_ssml,
                doc,
                speaker=speaker,
                language=language,
                instruct=instruct or None,
                speed=speed,
                voice=voice,
            )
            t_tts = time.time() - t1
        else:
            if summarize and summarizer:
                text_spoken = await asyncio.to_thread(summarizer.summarize, text, language, summarize_prompt)
                t_summarize = time.time() - t0
            else:
                text_spoken = text
                t_summarize = 0.0

            # Auto-insert pauses at paragraph breaks
            text_spoken = inject_breaks(text_spoken)

            t1 = time.time()
            if is_ssml(text_spoken):
                doc = parse_ssml(text_spoken)
                wav_bytes = await asyncio.to_thread(
                    tts.synthesize_ssml,
                    doc,
                    speaker=speaker,
                    language=language,
                    instruct=instruct or None,
                    speed=speed,
                    voice=voice,
                )
                text_spoken = doc.plain_text()
            else:
                wav_bytes = await asyncio.to_thread(
                    tts.synthesize,
                    text_spoken,
                    speaker=speaker,
                    language=language,
                    instruct=instruct or None,
                    speed=speed,
                    voice=voice,
                )
            t_tts = time.time() - t1

    entry_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{secrets.token_hex(4)}"
    duration = _wav_duration(wav_bytes)

    metadata = {
        "text_input": text_input[:500],
        "text_spoken": text_spoken[:2000],
        "preset": preset,
        "speaker": None if voice else (speaker or TTS_VOICE),
        "voice": voice,
        "language": language or TTS_LANGUAGE,
        "speed": speed,
        "instruct": instruct or "",
        "summarized": summarize and summarizer is not None,
        "summarize_time": round(t_summarize, 3),
        "tts_time": round(t_tts, 3),
        "duration": round(duration, 2),
        "audio_url": f"/api/history/{entry_id}/audio",
    }

    history_mgr.add(entry_id, metadata, wav_bytes)

    return {"id": entry_id, **metadata}


# ─── Presets ───

@router.get("/presets")
async def list_presets():
    return _load_presets()


@router.post("/presets")
async def save_preset(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Preset name is required")

    preset = {
        "name": name,
        "speaker": body.get("speaker"),
        "voice": body.get("voice"),
        "language": body.get("language", "English"),
        "instruct": body.get("instruct", ""),
        "speed": body.get("speed", 1.0),
        "summarize": body.get("summarize", True),
    }

    presets = _load_presets()
    # Update existing or append
    idx = next((i for i, p in enumerate(presets) if p["name"] == name), None)
    if idx is not None:
        presets[idx] = preset
    else:
        presets.append(preset)
    _save_presets(presets)
    return {"status": "ok", "preset": preset}


@router.delete("/presets/{name}")
async def delete_preset(name: str):
    presets = _load_presets()
    new_presets = [p for p in presets if p["name"] != name]
    if len(new_presets) == len(presets):
        raise HTTPException(status_code=404, detail="Preset not found")
    _save_presets(new_presets)
    return {"status": "ok"}


# ─── Voices ───

@router.get("/voices")
async def list_voices(request: Request):
    return request.app.state.voice_mgr.list_voices()


@router.post("/voices")
async def upload_voice(
    request: Request,
    name: str = Form(...),
    audio: UploadFile = File(...),
    transcript: str = Form(""),
):
    voice_mgr = request.app.state.voice_mgr
    wav_bytes = await audio.read()
    try:
        voice_mgr.add_voice(name, wav_bytes, transcript or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "name": name}


@router.delete("/voices/{name}")
async def delete_voice(request: Request, name: str):
    voice_mgr = request.app.state.voice_mgr
    try:
        voice_mgr.delete_voice(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok"}


@router.get("/voices/{name}/preview")
async def preview_voice(request: Request, name: str):
    try:
        audio = request.app.state.voice_mgr.get_voice_audio(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=audio, media_type="audio/wav")


# ─── History ───

@router.get("/history")
async def list_history(request: Request, limit: int = 50):
    return request.app.state.history_mgr.list(limit)


@router.get("/history/{entry_id}/audio")
async def get_history_audio(request: Request, entry_id: str):
    try:
        audio = request.app.state.history_mgr.get_audio(entry_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=audio, media_type="audio/wav")


@router.post("/history/{entry_id}/pin")
async def pin_history_entry(request: Request, entry_id: str):
    try:
        request.app.state.history_mgr.pin(entry_id, pinned=True)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok"}


@router.post("/history/{entry_id}/unpin")
async def unpin_history_entry(request: Request, entry_id: str):
    try:
        request.app.state.history_mgr.pin(entry_id, pinned=False)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok"}


@router.delete("/history/{entry_id}")
async def delete_history_entry(request: Request, entry_id: str):
    request.app.state.history_mgr.delete(entry_id)
    return {"status": "ok"}


@router.delete("/history")
async def clear_history(request: Request):
    request.app.state.history_mgr.clear()
    return {"status": "ok"}
