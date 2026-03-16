import time
import urllib.parse
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import HOST, PORT
from summarizer import Summarizer
from tts_engine import TTSEngine
from voice_manager import VoiceManager
from history import HistoryManager
from api_routes import router as api_router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="TTSQwen")
app.include_router(api_router)

summarizer: Summarizer | None = None
tts: TTSEngine | None = None
voice_mgr: VoiceManager | None = None
history_mgr: HistoryManager | None = None


class SpeakRequest(BaseModel):
    text: str
    summarize: bool = True
    speaker: str | None = None
    language: str | None = None
    instruct: str | None = None
    speed: float | None = None
    voice: str | None = None


@app.on_event("startup")
async def startup():
    global summarizer, tts, voice_mgr, history_mgr
    summarizer = Summarizer()
    tts = TTSEngine()
    voice_mgr = VoiceManager()
    history_mgr = HistoryManager()
    # Store on app.state so api_routes can access them
    # (module globals differ between __main__ and server module)
    app.state.summarizer = summarizer
    app.state.tts = tts
    app.state.voice_mgr = voice_mgr
    app.state.history_mgr = history_mgr


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/speak")
async def speak(req: SpeakRequest):
    t0 = time.time()

    if req.summarize and summarizer:
        text = summarizer.summarize(req.text)
        t_summarize = time.time() - t0
        print(f"Summarized in {t_summarize:.2f}s: {text[:100]}...")
    else:
        text = req.text
        t_summarize = 0

    t1 = time.time()
    wav_bytes = tts.synthesize(
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
    uvicorn.run(app, host=HOST, port=PORT)
