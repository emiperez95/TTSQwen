import io
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS

from config import TTS_INSTRUCT, TTS_LANGUAGE, TTS_MODEL, TTS_SPEED, TTS_VOICE

torch.set_float32_matmul_precision("high")
torch.backends.cudnn.benchmark = True

VOICES_DIR = Path(__file__).parent / "voices"


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
        voice: str | None = None,
    ) -> bytes:
        """Synthesize text to WAV bytes with optional per-request overrides."""
        language = language or TTS_LANGUAGE
        instruct = instruct if instruct is not None else TTS_INSTRUCT
        speed = speed if speed is not None else TTS_SPEED

        if voice:
            wavs, sr = self._generate_cloned(text, language, voice, instruct)
        else:
            wavs, sr = self._generate_custom(text, language, speaker or TTS_VOICE, instruct)

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

    def _generate_custom(self, text, language, speaker, instruct):
        kwargs = dict(text=text, language=language, speaker=speaker)
        if instruct:
            kwargs["instruct"] = instruct
        return self.model.generate_custom_voice(**kwargs)

    def _generate_cloned(self, text, language, voice, instruct):
        ref_audio = VOICES_DIR / f"{voice}.wav"
        ref_text_path = VOICES_DIR / f"{voice}.txt"
        if not ref_audio.exists():
            raise FileNotFoundError(f"Voice file not found: {ref_audio}")
        ref_text = ref_text_path.read_text().strip() if ref_text_path.exists() else ""
        kwargs = dict(
            text=text,
            language=language,
            ref_audio=str(ref_audio),
            ref_text=ref_text,
        )
        if instruct:
            kwargs["instruct"] = instruct
        return self.model.generate_voice_clone(**kwargs)

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
