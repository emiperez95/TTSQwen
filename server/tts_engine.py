import io
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS

from config import (
    PRESET_SPEAKERS, TTS_INSTRUCT, TTS_LANGUAGE, TTS_MODEL, TTS_MODEL_BASE,
    TTS_SPEAKER, TTS_SPEED, TTS_VOICE,
)
from model_manager import ModelManager
from ssml_parser import SSMLDocument, SpeechSegment, BreakSegment, AudioSegment
from audio_ops import generate_silence, load_sfx, concatenate_wavs, mix_background
from telemetry import tracer, generate_duration, audio_output_duration

torch.set_float32_matmul_precision("high")
torch.backends.cudnn.benchmark = True

log = logging.getLogger(__name__)

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
            pinned=True,
        )

        log.info("TTS engine registered. Voice: %s, Language: %s", TTS_VOICE, TTS_LANGUAGE)

    @staticmethod
    def _load_custom():
        log.info("Loading CustomVoice model: %s", TTS_MODEL)
        return FasterQwen3TTS.from_pretrained(
            TTS_MODEL,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

    @staticmethod
    def _load_base():
        log.info("Loading Base model: %s", TTS_MODEL_BASE)
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
        return self._synthesize_raw(text, speaker=speaker, language=language,
                                    instruct=instruct, speed=speed, voice=voice)

    def _synthesize_raw(
        self,
        text: str,
        speaker: str | None = None,
        language: str | None = None,
        instruct: str | None = None,
        speed: float | None = None,
        voice: str | None = None,
        ref_audio_override: str | None = None,
        ref_text_override: str | None = None,
    ) -> bytes:
        """Internal synthesize with optional reference audio override for chaining."""
        language = language or TTS_LANGUAGE
        instruct = instruct if instruct is not None else TTS_INSTRUCT
        speed = speed if speed is not None else TTS_SPEED

        # Resolve voice: explicit voice/speaker > defaults
        # voice = clone via Base model, speaker = preset via CustomVoice
        if not voice and not speaker:
            voice = TTS_VOICE  # Default to clone voice

        voice_label = f"preset:{speaker}" if speaker else f"clone:{voice or TTS_VOICE}"

        t0 = time.time()
        with tracer.start_as_current_span("tts.generate", attributes={"tts.voice": voice_label}):
            if speaker:
                wavs, sr = self._generate_custom(text, language, speaker, instruct)
            else:
                wavs, sr = self._generate_cloned(text, language, voice, instruct,
                                                  ref_audio_override=ref_audio_override,
                                                  ref_text_override=ref_text_override)
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
        generate_duration.record(t_generate, {"voice": voice_label})
        audio_output_duration.record(duration_s, {"voice": voice_label})

        log.info(
            "[TTS] generate=%.2fs encode=%.2fs speed_adj=%.2fs "
            "| audio=%.1fs %dKB | input=%d chars | voice=%s",
            t_generate, t_encode, t_speed,
            duration_s, len(wav_bytes) // 1024, len(text), voice_label,
        )

        return wav_bytes

    def _generate_custom(self, text, language, speaker, instruct):
        model = self._manager.get("custom_voice")
        kwargs = dict(text=text, language=language, speaker=speaker)
        if instruct:
            kwargs["instruct"] = instruct
        return model.generate_custom_voice(**kwargs)

    def _generate_cloned(self, text, language, voice, instruct, ref_audio_override=None, ref_text_override=None):
        model = self._manager.get("base")
        if ref_audio_override:
            ref_audio_path = ref_audio_override
            ref_text = ref_text_override or ""
        else:
            ref_audio_path = str(VOICES_DIR / f"{voice}.wav")
            if not Path(ref_audio_path).exists():
                raise FileNotFoundError(f"Voice file not found: {ref_audio_path}")
            ref_text_path = VOICES_DIR / f"{voice}.txt"
            ref_text = ref_text_path.read_text(encoding="utf-8").strip() if ref_text_path.exists() else ""
        kwargs = dict(
            text=text,
            language=language,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
            xvec_only=False,
        )
        return model.generate_voice_clone(**kwargs)

    @staticmethod
    def _resolve_segment_voice(
        seg_name: str | None,
        default_speaker: str | None,
        default_voice: str | None,
    ) -> tuple[str | None, str | None]:
        """Map a SpeechSegment's `name` override to (speaker, voice).

        - Preset name → (preset, None) routes to CustomVoice model.
        - Other name → (None, name) routes to clone model.
        - No override → fall back to request defaults.
        """
        if seg_name:
            if seg_name in PRESET_SPEAKERS:
                return seg_name, None
            return None, seg_name
        return default_speaker, default_voice

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

        # Per-voice chain state: clone voice name → (wav_path, text).
        # Each speaker chains against their own prior segment, not whoever spoke last.
        chain_state: dict[str, tuple[str, str]] = {}

        wav_parts: list[bytes] = []
        try:
            for seg in doc.segments:
                if isinstance(seg, SpeechSegment):
                    eff_speaker, eff_voice = self._resolve_segment_voice(seg.name, speaker, voice)
                    prior = chain_state.get(eff_voice) if eff_voice else None
                    ref_audio = prior[0] if prior else None
                    ref_text = prior[1] if prior else None

                    wav_bytes_seg = self._synthesize_raw(
                        seg.text,
                        speaker=eff_speaker,
                        language=language,
                        instruct=instruct,
                        speed=1.0,
                        voice=eff_voice,
                        ref_audio_override=ref_audio,
                        ref_text_override=ref_text,
                    )
                    wav_parts.append(wav_bytes_seg)

                    if eff_voice:
                        fd, tmp = tempfile.mkstemp(suffix=".wav")
                        with os.fdopen(fd, "wb") as f:
                            f.write(wav_bytes_seg)
                        if prior:
                            try:
                                os.remove(prior[0])
                            except OSError:
                                pass
                        chain_state[eff_voice] = (tmp, seg.text)
                elif isinstance(seg, BreakSegment):
                    wav_parts.append(generate_silence(seg.duration_ms))
                elif isinstance(seg, AudioSegment):
                    wav_parts.append(load_sfx(seg.name))
        finally:
            for path, _ in chain_state.values():
                try:
                    os.remove(path)
                except OSError:
                    pass

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

    def synthesize_ssml_streaming(
        self,
        doc: SSMLDocument,
        speaker: str | None = None,
        language: str | None = None,
        instruct: str | None = None,
        speed: float | None = None,
        voice: str | None = None,
        cancel: "threading.Event | None" = None,
    ) -> Generator[bytes, None, None]:
        """Yield WAV bytes per segment for streaming. Caller converts to MP3."""
        import threading
        effective_speed = speed if speed is not None else TTS_SPEED

        chain_state: dict[str, tuple[str, str]] = {}

        try:
            for seg in doc.segments:
                if cancel and cancel.is_set():
                    break

                if isinstance(seg, SpeechSegment):
                    eff_speaker, eff_voice = self._resolve_segment_voice(seg.name, speaker, voice)
                    prior = chain_state.get(eff_voice) if eff_voice else None

                    wav_raw = self._synthesize_raw(
                        seg.text, speaker=eff_speaker, language=language,
                        instruct=instruct, speed=1.0, voice=eff_voice,
                        ref_audio_override=prior[0] if prior else None,
                        ref_text_override=prior[1] if prior else None,
                    )

                    # Update chaining ref with pre-speed WAV
                    if eff_voice:
                        fd, tmp = tempfile.mkstemp(suffix=".wav")
                        with os.fdopen(fd, "wb") as f:
                            f.write(wav_raw)
                        if prior:
                            try:
                                os.remove(prior[0])
                            except OSError:
                                pass
                        chain_state[eff_voice] = (tmp, seg.text)

                    # Yield speed-adjusted chunk
                    if effective_speed != 1.0:
                        yield self._apply_speed(wav_raw, effective_speed)
                    else:
                        yield wav_raw

                elif isinstance(seg, BreakSegment):
                    yield generate_silence(seg.duration_ms)

                elif isinstance(seg, AudioSegment):
                    yield load_sfx(seg.name)
        finally:
            for path, _ in chain_state.values():
                try:
                    os.remove(path)
                except OSError:
                    pass

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
