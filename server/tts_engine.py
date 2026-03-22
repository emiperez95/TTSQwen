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

from config import (
    TTS_INSTRUCT, TTS_LANGUAGE, TTS_MODEL, TTS_MODEL_BASE, TTS_SPEED, TTS_VOICE,
)
from model_manager import ModelManager
from ssml_parser import SSMLDocument, SpeechSegment, BreakSegment, AudioSegment
from audio_ops import generate_silence, load_sfx, concatenate_wavs, mix_background

torch.set_float32_matmul_precision("high")
torch.backends.cudnn.benchmark = True

VOICES_DIR = Path(__file__).parent / "voices"


class TTSEngine:
    def __init__(self, manager: ModelManager):
        self._manager = manager

        manager.register(
            "custom_voice",
            load_fn=self._load_custom,
            warmup_fn=self._warmup_custom,
        )
        manager.register(
            "base",
            load_fn=self._load_base,
            warmup_fn=self._warmup_base,
        )

        print(f"TTS engine registered. Voice: {TTS_VOICE}, Language: {TTS_LANGUAGE}")

    @staticmethod
    def _load_custom():
        print(f"Loading CustomVoice model: {TTS_MODEL}")
        return FasterQwen3TTS.from_pretrained(
            TTS_MODEL,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

    @staticmethod
    def _load_base():
        print(f"Loading Base model: {TTS_MODEL_BASE}")
        return FasterQwen3TTS.from_pretrained(
            TTS_MODEL_BASE,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

    @staticmethod
    def _warmup_custom(model):
        model.generate_custom_voice(
            text="Warmup.",
            language=TTS_LANGUAGE,
            speaker=TTS_VOICE,
        )

    @staticmethod
    def _warmup_base(model):
        voices = list(VOICES_DIR.glob("*.wav"))
        if not voices:
            return
        ref = voices[0]
        ref_text_path = ref.with_suffix(".txt")
        ref_text = ref_text_path.read_text(encoding="utf-8").strip() if ref_text_path.exists() else ""
        model.generate_voice_clone(
            text="Warmup.",
            language=TTS_LANGUAGE,
            ref_audio=str(ref),
            ref_text=ref_text,
        )

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

        t0 = time.time()
        if voice:
            wavs, sr = self._generate_cloned(text, language, voice, instruct)
        else:
            wavs, sr = self._generate_custom(text, language, speaker or TTS_VOICE, instruct)
        t_generate = time.time() - t0

        t1 = time.time()
        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()

        # Normalize to int16 range
        audio = audio / (np.abs(audio).max() + 1e-7)
        audio = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        wav_bytes = buf.getvalue()
        t_encode = time.time() - t1

        t_speed = 0.0
        if speed != 1.0:
            t2 = time.time()
            wav_bytes = self._apply_speed(wav_bytes, speed)
            t_speed = time.time() - t2

        duration_s = len(audio) / sr
        print(
            f"[TTS] generate={t_generate:.2f}s encode={t_encode:.2f}s speed_adj={t_speed:.2f}s "
            f"| audio={duration_s:.1f}s {len(wav_bytes)//1024}KB "
            f"| input={len(text)} chars | voice={'clone:'+voice if voice else speaker or TTS_VOICE}"
        )

        return wav_bytes

    def _generate_custom(self, text, language, speaker, instruct):
        model = self._manager.get("custom_voice")
        kwargs = dict(text=text, language=language, speaker=speaker)
        if instruct:
            kwargs["instruct"] = instruct
        return model.generate_custom_voice(**kwargs)

    def _generate_cloned(self, text, language, voice, instruct):
        model = self._manager.get("base")
        ref_audio = VOICES_DIR / f"{voice}.wav"
        ref_text_path = VOICES_DIR / f"{voice}.txt"
        if not ref_audio.exists():
            raise FileNotFoundError(f"Voice file not found: {ref_audio}")
        ref_text = ref_text_path.read_text(encoding="utf-8").strip() if ref_text_path.exists() else ""
        kwargs = dict(
            text=text,
            language=language,
            ref_audio=str(ref_audio),
            ref_text=ref_text,
            xvec_only=False,
        )
        # Note: generate_voice_clone does not support instruct
        return model.generate_voice_clone(**kwargs)

    def synthesize_ssml(
        self,
        doc: SSMLDocument,
        speaker: str | None = None,
        language: str | None = None,
        instruct: str | None = None,
        speed: float | None = None,
        voice: str | None = None,
    ) -> bytes:
        """Synthesize an SSML document: speech segments via TTS, breaks as silence, audio as SFX."""
        effective_speed = speed if speed is not None else TTS_SPEED

        wav_parts: list[bytes] = []
        for seg in doc.segments:
            if isinstance(seg, SpeechSegment):
                # Synthesize at speed=1.0; we apply speed to the final result
                wav_parts.append(
                    self.synthesize(
                        seg.text,
                        speaker=speaker,
                        language=language,
                        instruct=instruct,
                        speed=1.0,
                        voice=voice,
                    )
                )
            elif isinstance(seg, BreakSegment):
                wav_parts.append(generate_silence(seg.duration_ms))
            elif isinstance(seg, AudioSegment):
                wav_parts.append(load_sfx(seg.name))

        if not wav_parts:
            wav_parts.append(generate_silence(100))

        result = concatenate_wavs(wav_parts)

        # Mix background if present
        if doc.background:
            bg_wav = load_sfx(doc.background.name)
            result = mix_background(result, bg_wav, volume=doc.background.volume)

        # Apply speed to final combined audio
        if effective_speed != 1.0:
            result = self._apply_speed(result, effective_speed)

        return result

    @staticmethod
    def _apply_speed(wav_bytes: bytes, speed: float) -> bytes:
        """Apply tempo change using ffmpeg's rubberband filter."""
        in_fd, inpath = tempfile.mkstemp(suffix=".wav")
        out_fd, outpath = tempfile.mkstemp(suffix=".wav")
        try:
            os.close(out_fd)
            with os.fdopen(in_fd, "wb") as f:
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
