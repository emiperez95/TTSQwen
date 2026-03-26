"""HLS session management — in-memory segment storage with TTL cleanup."""

import math
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field

TIMESCALE = 44100  # AAC at 44100 Hz


def _patch_tfdt(data: bytes, base_decode_time: int) -> bytes:
    """Patch the tfdt box's baseMediaDecodeTime in an fMP4 segment."""
    pos = data.find(b"tfdt")
    if pos < 0:
        return data
    data = bytearray(data)
    version = data[pos + 4]
    if version == 1:
        # 64-bit baseMediaDecodeTime
        struct.pack_into(">Q", data, pos + 5, base_decode_time)
    else:
        # 32-bit baseMediaDecodeTime
        struct.pack_into(">I", data, pos + 5, base_decode_time)
    return bytes(data)


@dataclass
class HLSSegment:
    data: bytes
    duration: float  # seconds


@dataclass
class HLSSession:
    init_segment: bytes | None = None
    segments: list[HLSSegment] = field(default_factory=list)
    done: bool = False
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)


class HLSManager:
    def __init__(self, ttl: int = 300):
        self._sessions: dict[str, HLSSession] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._sessions[session_id] = HLSSession()
        return session_id

    def get_cancel(self, session_id: str) -> threading.Event | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.cancel if session else None

    def cancel_session(self, session_id: str) -> bool:
        """Signal cancellation and mark session done. Returns True if session existed."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.cancel.set()
            session.done = True
            return True

    def remove_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def set_init(self, session_id: str, data: bytes):
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.init_segment = data

    def get_init(self, session_id: str) -> bytes | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.init_segment

    def add_segment(self, session_id: str, data: bytes, duration: float):
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                # Compute cumulative decode time for this segment
                cumulative = sum(s.duration for s in session.segments)
                base_decode_time = int(cumulative * TIMESCALE)
                data = _patch_tfdt(data, base_decode_time)
                session.segments.append(HLSSegment(data=data, duration=duration))

    def finish(self, session_id: str, error: str | None = None):
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.done = True
                session.error = error

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def get_playlist(self, session_id: str) -> str | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            segments = list(session.segments)
            done = session.done

        max_dur = max((s.duration for s in segments), default=10.0)

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:7",
            f"#EXT-X-TARGETDURATION:{math.ceil(max_dur)}",
            "#EXT-X-PLAYLIST-TYPE:EVENT",
            "#EXT-X-MEDIA-SEQUENCE:0",
            '#EXT-X-MAP:URI="init.m4s"',
        ]
        for i, seg in enumerate(segments):
            lines.append(f"#EXTINF:{seg.duration:.3f},")
            lines.append(f"{i}.m4s")

        if done:
            lines.append("#EXT-X-ENDLIST")

        return "\n".join(lines) + "\n"

    def get_segment(self, session_id: str, index: int) -> bytes | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or index < 0 or index >= len(session.segments):
                return None
            return session.segments[index].data

    def cleanup(self):
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.created_at > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
        return len(expired)
