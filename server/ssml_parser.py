"""
SSML-like markup parser for TTS.

Supported tags (self-closing only):
  <audio src="name"/>     — insert sound effect from server/sfx/
  <break time="500ms"/>   — insert silence (ms or s units)
  <bg src="name" vol="0.15"/> — mix background audio under entire output (looped)
"""

import re
from dataclasses import dataclass

MAX_BREAK_MS = 10_000
MAX_SEGMENTS = 20

_TAG_RE = re.compile(
    r'<(audio|break|bg)\s+([^>]*?)\s*/>', re.IGNORECASE
)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_SSML_DETECT_RE = re.compile(r'<(?:audio|break|bg)\s', re.IGNORECASE)


@dataclass
class SpeechSegment:
    text: str


@dataclass
class BreakSegment:
    duration_ms: int


@dataclass
class AudioSegment:
    name: str


@dataclass
class BackgroundAudio:
    name: str
    volume: float = 0.15


@dataclass
class SSMLDocument:
    segments: list  # list of SpeechSegment | BreakSegment | AudioSegment
    background: BackgroundAudio | None = None

    def plain_text(self) -> str:
        """Return concatenated speech text with tags stripped."""
        parts = [seg.text for seg in self.segments if isinstance(seg, SpeechSegment)]
        return " ".join(parts)


def is_ssml(text: str) -> bool:
    return bool(_SSML_DETECT_RE.search(text))


def _parse_attrs(attr_str: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(attr_str))


def _parse_duration(time_str: str) -> int:
    """Parse '500ms' or '1.5s' into milliseconds."""
    time_str = time_str.strip().lower()
    if time_str.endswith("ms"):
        ms = int(float(time_str[:-2]))
    elif time_str.endswith("s"):
        ms = int(float(time_str[:-1]) * 1000)
    else:
        ms = int(float(time_str))
    return min(max(ms, 0), MAX_BREAK_MS)


def parse_ssml(text: str) -> SSMLDocument:
    """Parse SSML-like markup into an SSMLDocument."""
    segments: list = []
    background: BackgroundAudio | None = None

    # Split text around tags, keeping the tags as captured groups
    parts = _TAG_RE.split(text)
    # parts alternates: [text, tag_name, attrs, text, tag_name, attrs, ...]

    i = 0
    while i < len(parts):
        if i % 3 == 0:
            # Text segment
            chunk = parts[i].strip()
            if chunk:
                segments.append(SpeechSegment(text=chunk))
        elif i % 3 == 1:
            tag_name = parts[i].lower()
            attrs = _parse_attrs(parts[i + 1])

            if tag_name == "audio":
                name = attrs.get("src", "")
                if name:
                    segments.append(AudioSegment(name=name))
            elif tag_name == "break":
                time_str = attrs.get("time", "500ms")
                segments.append(BreakSegment(duration_ms=_parse_duration(time_str)))
            elif tag_name == "bg":
                name = attrs.get("src", "")
                if name:
                    vol = float(attrs.get("vol", "0.15"))
                    background = BackgroundAudio(name=name, volume=vol)
            i += 1  # skip attrs part (consumed here)
        i += 1

    # Enforce segment limit
    if len(segments) > MAX_SEGMENTS:
        segments = segments[:MAX_SEGMENTS]

    return SSMLDocument(segments=segments, background=background)
