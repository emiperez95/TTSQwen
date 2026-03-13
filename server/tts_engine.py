import io

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

from config import TTS_LANGUAGE, TTS_MODEL, TTS_VOICE


class TTSEngine:
    def __init__(self):
        print(f"Loading TTS model: {TTS_MODEL}")
        self.model = Qwen3TTSModel.from_pretrained(
            TTS_MODEL,
            device_map="cuda:0",
            dtype=torch.bfloat16,
        )
        print(f"TTS ready. Voice: {TTS_VOICE}, Language: {TTS_LANGUAGE}")

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
