import re
from pathlib import Path

from config import PRESET_SPEAKERS

VOICES_DIR = Path(__file__).parent / "voices"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


class VoiceManager:
    def __init__(self):
        VOICES_DIR.mkdir(exist_ok=True)

    def is_known(self, name: str) -> bool:
        """True if `name` is a preset speaker or an existing cloned voice file."""
        if name in PRESET_SPEAKERS:
            return True
        return (VOICES_DIR / f"{name}.wav").exists()

    def list_voices(self) -> dict:
        preset = [
            {"name": name, **meta}
            for name, meta in PRESET_SPEAKERS.items()
        ]
        preset_lower = {n.lower() for n in PRESET_SPEAKERS}

        cloned = []
        for wav in sorted(VOICES_DIR.glob("*.wav")):
            name = wav.stem
            if name in preset_lower:
                continue
            cloned.append({
                "name": name,
                "has_transcript": wav.with_suffix(".txt").exists(),
            })

        return {"preset": preset, "cloned": cloned}

    def add_voice(self, name: str, wav_bytes: bytes, transcript: str | None = None):
        if not NAME_RE.match(name):
            raise ValueError(f"Invalid voice name: must match {NAME_RE.pattern}")
        if name in {n.lower() for n in PRESET_SPEAKERS}:
            raise ValueError(f"Cannot overwrite preset voice: {name}")

        wav_path = VOICES_DIR / f"{name}.wav"
        wav_path.write_bytes(wav_bytes)

        if transcript:
            txt_path = VOICES_DIR / f"{name}.txt"
            txt_path.write_text(transcript.strip(), encoding="utf-8")

    def delete_voice(self, name: str):
        if name in {n.lower() for n in PRESET_SPEAKERS}:
            raise ValueError(f"Cannot delete preset voice: {name}")

        wav_path = VOICES_DIR / f"{name}.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"Voice not found: {name}")

        wav_path.unlink()
        txt_path = VOICES_DIR / f"{name}.txt"
        if txt_path.exists():
            txt_path.unlink()

    def get_voice_audio(self, name: str) -> bytes:
        # Check cloned voices first
        wav_path = VOICES_DIR / f"{name}.wav"
        if wav_path.exists():
            return wav_path.read_bytes()
        # Check preset voices (lowercase match)
        wav_path = VOICES_DIR / f"{name.lower()}.wav"
        if wav_path.exists():
            return wav_path.read_bytes()
        raise FileNotFoundError(f"Voice audio not found: {name}")
