import asyncio
import gc
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from config import (
    CORS_ORIGINS, HOST, PORT, MAX_TEXT_LENGTH, MIN_SPEED, MAX_SPEED,
    PRESET_SPEAKERS, VALID_LANGUAGES,
)
from summarizer import Summarizer
from tts_engine import TTSEngine
from voice_manager import VoiceManager
from history import HistoryManager
from api_routes import router as api_router

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.summarizer = Summarizer()
    app.state.tts = TTSEngine()
    app.state.voice_mgr = VoiceManager()
    app.state.history_mgr = HistoryManager()
    app.state.inference_lock = asyncio.Semaphore(1)
    yield
    # Shutdown — free CUDA memory
    import torch
    del app.state.tts
    del app.state.summarizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("CUDA memory released.")


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


@app.post("/speak")
async def speak(req: SpeakRequest, request: Request):
    summarizer = request.app.state.summarizer
    tts = request.app.state.tts
    lock = request.app.state.inference_lock

    async with lock:
        t0 = time.time()

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
