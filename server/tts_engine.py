import io
import os
import subprocess
import tempfile
import time

import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS

from config import TTS_INSTRUCT, TTS_LANGUAGE, TTS_MODEL, TTS_SPEED, TTS_VOICE

torch.set_float32_matmul_precision("high")
torch.backends.cudnn.benchmark = True


class TTSEngine:
    def __init__(self):
        print(f"Loading TTS model: {TTS_MODEL}")
        self.model = FasterQwen3TTS.from_pretrained(
            TTS_MODEL,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        print(f"TTS ready. Voice: {TTS_VOICE}, Language: {TTS_LANGUAGE}")
        self._warmup()

    def _warmup(self):
        """Run warmup inference to capture CUDA graphs."""
        print("Warming up TTS (CUDA graph capture)...")
        t0 = time.time()
        self.model.generate_custom_voice(
            text="Warmup.",
            language=TTS_LANGUAGE,
            speaker=TTS_VOICE,
        )
        print(f"Warmup done in {time.time() - t0:.1f}s")

    def synthesize(
        self,
        text: str,
        speaker: str | None = None,
        language: str | None = None,
        instruct: str | None = None,
        speed: float | None = None,
    ) -> bytes:
        """Synthesize text to WAV bytes with optional per-request overrides."""
        speaker = speaker or TTS_VOICE
        language = language or TTS_LANGUAGE
        instruct = instruct if instruct is not None else TTS_INSTRUCT
        speed = speed if speed is not None else TTS_SPEED

        kwargs = dict(text=text, language=language, speaker=speaker)
        if instruct:
            kwargs["instruct"] = instruct

        wavs, sr = self.model.generate_custom_voice(**kwargs)

        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()

        # Normalize to int16 range
        audio = audio / (np.abs(audio).max() + 1e-7)
        audio = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        wav_bytes = buf.getvalue()

        if speed != 1.0:
            wav_bytes = self._apply_speed(wav_bytes, speed)

        return wav_bytes

    @staticmethod
    def _apply_speed(wav_bytes: bytes, speed: float) -> bytes:
        """Apply tempo change using ffmpeg's rubberband filter."""
        inpath = tempfile.mktemp(suffix=".wav")
        outpath = tempfile.mktemp(suffix=".wav")
        try:
            with open(inpath, "wb") as f:
                f.write(wav_bytes)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", inpath,
                    "-af", f"rubberband=tempo={speed}",
                    outpath,
                ],
                capture_output=True,
                check=True,
            )
            with open(outpath, "rb") as f:
                return f.read()
        finally:
            for p in (inpath, outpath):
                try:
                    os.remove(p)
                except OSError:
                    pass
