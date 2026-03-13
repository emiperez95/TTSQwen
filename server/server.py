import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

from config import HOST, PORT
from summarizer import Summarizer
from tts_engine import TTSEngine

app = FastAPI(title="TTSQwen")

summarizer: Summarizer | None = None
tts: TTSEngine | None = None


class SpeakRequest(BaseModel):
    text: str
    summarize: bool = True


@app.on_event("startup")
async def startup():
    global summarizer, tts
    summarizer = Summarizer()
    tts = TTSEngine()


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
    wav_bytes = tts.synthesize(text)
    t_tts = time.time() - t1

    print(f"TTS in {t_tts:.2f}s, {len(wav_bytes)} bytes")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Summarize-Time": f"{t_summarize:.3f}",
            "X-TTS-Time": f"{t_tts:.3f}",
            "X-Spoken-Text": text[:200],
        },
    )


@app.post("/tts")
async def tts_only(req: SpeakRequest):
    """Direct TTS without summarization."""
    t0 = time.time()
    wav_bytes = tts.synthesize(req.text)
    t_tts = time.time() - t0
    print(f"TTS in {t_tts:.2f}s, {len(wav_bytes)} bytes")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"X-TTS-Time": f"{t_tts:.3f}"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
