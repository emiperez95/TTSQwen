"""HLS session management — in-memory segment storage with TTL cleanup."""

import math
import threading
import time
import uuid
from dataclasses import dataclass, field


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
