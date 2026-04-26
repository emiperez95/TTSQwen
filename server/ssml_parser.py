"""
SSML-like markup parser for TTS.

Supported tags:
  Self-closing:
    <audio src="name"/>     — insert sound effect from server/sfx/
    <break time="500ms"/>   — insert silence (ms or s units)
    <bg src="name" vol="0.15"/> — mix background audio under entire output (looped)
  Paired:
    <voice name="aiden">...</voice> — render the wrapped text in a different voice
                                       (preset speaker name or cloned voice name)
"""

import re
from dataclasses import dataclass

MAX_BREAK_MS = 10_000
MAX_SEGMENTS = 200

_TAG_RE = re.compile(
    r'<(audio|break|bg)\s+([^>]*?)\s*/>', re.IGNORECASE
)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_SSML_DETECT_RE = re.compile(r'<(?:audio|break|bg|voice)\b', re.IGNORECASE)
_VOICE_BLOCK_RE = re.compile(
    r'<voice\s+([^>]*?)\s*>(.*?)</voice\s*>',
    re.IGNORECASE | re.DOTALL,
)
_VOICE_TAG_DETECT_RE = re.compile(r'</?voice\b', re.IGNORECASE)


@dataclass
class SpeechSegment:
    text: str
    name: str | None = None  # voice/speaker override from <voice name="..."> block


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

    def voice_names(self) -> set[str]:
        """Return distinct voice/speaker names referenced by <voice> blocks."""
        return {
            seg.name for seg in self.segments
            if isinstance(seg, SpeechSegment) and seg.name
        }


_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')

def inject_breaks(text: str, sentence_ms: int = 300, paragraph_ms: int = 700) -> str:
    """Insert <break> tags at paragraph and sentence boundaries.

    - Paragraph breaks (double newlines): longer pause
    - Sentence endings (. ! ?): shorter breath pause
    """
    # First, replace paragraph breaks with a longer pause
    result = re.sub(r'\n\s*\n', f' <break time="{paragraph_ms}ms"/> ', text)
    # Then, insert short pauses between sentences
    result = _SENTENCE_END_RE.sub(f' <break time="{sentence_ms}ms"/> ', result)
    return result.strip()


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


def _parse_simple(text: str, voice_name: str | None) -> tuple[list, "BackgroundAudio | None"]:
    """Parse text containing only self-closing tags (audio/break/bg).

    Speech segments inherit `voice_name` (None outside any <voice> block).
    """
    if _VOICE_TAG_DETECT_RE.search(text):
        raise ValueError("nested or unbalanced <voice> tag")

    segments: list = []
    background: BackgroundAudio | None = None

    parts = _TAG_RE.split(text)
    # parts alternates: [text, tag_name, attrs, text, tag_name, attrs, ...]
    i = 0
    while i < len(parts):
        if i % 3 == 0:
            chunk = parts[i].strip()
            if chunk:
                segments.append(SpeechSegment(text=chunk, name=voice_name))
        elif i % 3 == 1:
            tag_name = parts[i].lower()
            attrs = _parse_attrs(parts[i + 1])

            if tag_name == "audio":
                src = attrs.get("src", "")
                if src:
                    segments.append(AudioSegment(name=src))
            elif tag_name == "break":
                time_str = attrs.get("time", "500ms")
                segments.append(BreakSegment(duration_ms=_parse_duration(time_str)))
            elif tag_name == "bg":
                src = attrs.get("src", "")
                if src:
                    vol = float(attrs.get("vol", "0.15"))
                    background = BackgroundAudio(name=src, volume=vol)
            i += 1  # skip attrs part (consumed here)
        i += 1

    return segments, background


def parse_ssml(text: str) -> SSMLDocument:
    """Parse SSML-like markup into an SSMLDocument."""
    segments: list = []
    background: BackgroundAudio | None = None

    last_end = 0
    for m in _VOICE_BLOCK_RE.finditer(text):
        outer = text[last_end:m.start()]
        if outer.strip():
            seg, bg = _parse_simple(outer, None)
            segments.extend(seg)
            if bg and not background:
                background = bg

        attrs = _parse_attrs(m.group(1))
        voice_name = attrs.get("name", "").strip()
        if not voice_name:
            raise ValueError('<voice> tag missing or empty "name" attribute')

        body = m.group(2)
        seg, bg = _parse_simple(body, voice_name)
        segments.extend(seg)
        if bg and not background:
            background = bg

        last_end = m.end()

    tail = text[last_end:]
    if tail.strip():
        seg, bg = _parse_simple(tail, None)
        segments.extend(seg)
        if bg and not background:
            background = bg

    if len(segments) > MAX_SEGMENTS:
        raise ValueError(
            f"document exceeds max {MAX_SEGMENTS} segments (got {len(segments)}); "
            "split into multiple requests or remove redundant <break>/<audio> tags"
        )

    return SSMLDocument(segments=segments, background=background)
