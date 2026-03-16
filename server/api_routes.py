import time
import wave
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from config import (
    PRESET_SPEAKERS, TTS_INSTRUCT, TTS_LANGUAGE, TTS_SPEED, TTS_VOICE,
)

router = APIRouter(prefix="/api")


def _get_deps():
    """Get shared server instances (set by server.py on startup)."""
    from server import tts, summarizer, voice_mgr, history_mgr
    return tts, summarizer, voice_mgr, history_mgr


def _wav_duration(wav_bytes: bytes) -> float:
    import io
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / w.getframerate()


# ─── Config ───

@router.get("/config")
async def get_config():
    tts, *_ = _get_deps()
    return {
        "default_speaker": TTS_VOICE,
        "default_language": TTS_LANGUAGE,
        "default_speed": TTS_SPEED,
        "default_instruct": TTS_INSTRUCT,
        "speakers": list(PRESET_SPEAKERS.keys()),
        "languages": ["English", "Chinese", "Japanese", "Korean"],
    }


# ─── Speak ───

@router.post("/speak")
async def api_speak(
    text: str = Form(...),
    summarize: bool = Form(True),
    speaker: str = Form(None),
    language: str = Form(None),
    instruct: str = Form(""),
    speed: float = Form(1.0),
    voice: str = Form(None),
):
    tts, summarizer, _, history_mgr = _get_deps()

    t0 = time.time()
    text_input = text

    if summarize and summarizer:
        text_spoken = summarizer.summarize(text)
        t_summarize = time.time() - t0
    else:
        text_spoken = text
        t_summarize = 0.0

    t1 = time.time()
    wav_bytes = tts.synthesize(
        text_spoken,
        speaker=speaker,
        language=language,
        instruct=instruct or None,
        speed=speed,
        voice=voice,
    )
    t_tts = time.time() - t1

    entry_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{id(wav_bytes) % 0xFFFF:04x}"
    duration = _wav_duration(wav_bytes)

    metadata = {
        "text_input": text_input[:500],
        "text_spoken": text_spoken[:500],
        "speaker": speaker or TTS_VOICE,
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


# ─── Voices ───

@router.get("/voices")
async def list_voices():
    _, _, voice_mgr, _ = _get_deps()
    return voice_mgr.list_voices()


@router.post("/voices")
async def upload_voice(
    name: str = Form(...),
    audio: UploadFile = File(...),
    transcript: str = Form(""),
):
    _, _, voice_mgr, _ = _get_deps()
    wav_bytes = await audio.read()
    try:
        voice_mgr.add_voice(name, wav_bytes, transcript or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "name": name}


@router.delete("/voices/{name}")
async def delete_voice(name: str):
    _, _, voice_mgr, _ = _get_deps()
    try:
        voice_mgr.delete_voice(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok"}


@router.get("/voices/{name}/preview")
async def preview_voice(name: str):
    _, _, voice_mgr, _ = _get_deps()
    try:
        audio = voice_mgr.get_voice_audio(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=audio, media_type="audio/wav")


# ─── History ───

@router.get("/history")
async def list_history(limit: int = 50):
    _, _, _, history_mgr = _get_deps()
    return history_mgr.list(limit)


@router.get("/history/{entry_id}/audio")
async def get_history_audio(entry_id: str):
    _, _, _, history_mgr = _get_deps()
    try:
        audio = history_mgr.get_audio(entry_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=audio, media_type="audio/wav")


@router.delete("/history/{entry_id}")
async def delete_history_entry(entry_id: str):
    _, _, _, history_mgr = _get_deps()
    history_mgr.delete(entry_id)
    return {"status": "ok"}


@router.delete("/history")
async def clear_history():
    _, _, _, history_mgr = _get_deps()
    history_mgr.clear()
    return {"status": "ok"}
