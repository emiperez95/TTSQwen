import io
import time

import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS

from config import TTS_LANGUAGE, TTS_MODEL, TTS_VOICE

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

    def synthesize(self, text: str) -> bytes:
        """Synthesize text to WAV bytes."""
        wavs, sr = self.model.generate_custom_voice(
            text=text,
            language=TTS_LANGUAGE,
            speaker=TTS_VOICE,
        )

        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()

        # Normalize to int16 range
        audio = audio / (np.abs(audio).max() + 1e-7)
        audio = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()
