"""
Audio utilities for SSML pipeline: silence generation, SFX loading,
WAV concatenation, and background mixing via ffmpeg.
"""

import io
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from config import TTS_SAMPLE_RATE

SFX_DIR = Path(__file__).parent / "sfx"


def generate_silence(duration_ms: int, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
    """Generate WAV bytes of silence for the given duration."""
    n_samples = int(sample_rate * duration_ms / 1000)
    silence = np.zeros(n_samples, dtype=np.int16)
    buf = io.BytesIO()
    sf.write(buf, silence, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def load_sfx(name: str) -> bytes:
    """Load a sound effect by name from SFX_DIR, converting to 24kHz mono WAV if needed."""
    # Try common extensions
    for ext in ("wav", "mp3", "ogg", "flac"):
        path = SFX_DIR / f"{name}.{ext}"
        if path.exists():
            break
    else:
        raise FileNotFoundError(
            f"Sound effect '{name}' not found in {SFX_DIR}. "
            f"Available: {list_sfx()}"
        )

    # If already WAV, check if it needs resampling
    if path.suffix == ".wav":
        info = sf.info(str(path))
        if info.samplerate == TTS_SAMPLE_RATE and info.channels == 1:
            return path.read_bytes()

    # Convert to 24kHz mono WAV via ffmpeg
    out_fd, outpath = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(out_fd)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-ar", str(TTS_SAMPLE_RATE), "-ac", "1",
                "-sample_fmt", "s16",
                outpath,
            ],
            capture_output=True, check=True,
        )
        with open(outpath, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(outpath)
        except OSError:
            pass


def list_sfx() -> list[str]:
    """List available sound effect names (without extension)."""
    if not SFX_DIR.exists():
        return []
    exts = {".wav", ".mp3", ".ogg", ".flac"}
    return sorted({
        p.stem for p in SFX_DIR.iterdir()
        if p.suffix.lower() in exts
    })


def concatenate_wavs(wav_list: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte buffers using ffmpeg concat demuxer."""
    if not wav_list:
        return generate_silence(0)
    if len(wav_list) == 1:
        return wav_list[0]

    tmp_files = []
    out_fd, outpath = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(out_fd)

        # Write each WAV to a temp file
        for wav_bytes in wav_list:
            fd, path = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes)
            tmp_files.append(path)

        # Write concat list file
        list_fd, listpath = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(list_fd, "w") as f:
            for p in tmp_files:
                f.write(f"file '{p}'\n")
        tmp_files.append(listpath)

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", listpath, "-c", "copy", outpath,
            ],
            capture_output=True, check=True,
        )
        with open(outpath, "rb") as f:
            return f.read()
    finally:
        for p in tmp_files:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.remove(outpath)
        except OSError:
            pass


def wav_to_mp3(wav_bytes: bytes, bitrate: str = "192k") -> bytes:
    """Convert WAV bytes to MP3 bytes using ffmpeg."""
    in_fd, inpath = tempfile.mkstemp(suffix=".wav")
    out_fd, outpath = tempfile.mkstemp(suffix=".mp3")
    try:
        os.close(out_fd)
        with os.fdopen(in_fd, "wb") as f:
            f.write(wav_bytes)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", inpath,
                "-codec:a", "libmp3lame", "-b:a", bitrate,
                outpath,
            ],
            capture_output=True, check=True,
        )
        with open(outpath, "rb") as f:
            return f.read()
    finally:
        for p in (inpath, outpath):
            try:
                os.remove(p)
            except OSError:
                pass


def mix_background(fg_bytes: bytes, bg_bytes: bytes, volume: float = 0.15) -> bytes:
    """Mix looped background audio underneath foreground using ffmpeg."""
    fg_fd, fg_path = tempfile.mkstemp(suffix=".wav")
    bg_fd, bg_path = tempfile.mkstemp(suffix=".wav")
    out_fd, out_path = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(out_fd)
        with os.fdopen(fg_fd, "wb") as f:
            f.write(fg_bytes)
        with os.fdopen(bg_fd, "wb") as f:
            f.write(bg_bytes)

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", fg_path,
                "-stream_loop", "-1", "-i", bg_path,
                "-filter_complex",
                f"[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2",
                "-ar", str(TTS_SAMPLE_RATE), "-ac", "1",
                "-sample_fmt", "s16",
                out_path,
            ],
            capture_output=True, check=True,
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in (fg_path, bg_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass
