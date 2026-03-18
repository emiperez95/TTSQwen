import json
import threading
from pathlib import Path

from config import HISTORY_MAX_ENTRIES

HISTORY_DIR = Path(__file__).parent / "history"


class HistoryManager:
    def __init__(self):
        HISTORY_DIR.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._index_path = HISTORY_DIR / "index.json"
        if not self._index_path.exists():
            self._save_index([])

    def _load_index(self) -> list[dict]:
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_index(self, entries: list[dict]):
        self._index_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, entry_id: str, metadata: dict, wav_bytes: bytes):
        wav_path = HISTORY_DIR / f"{entry_id}.wav"
        wav_path.write_bytes(wav_bytes)

        with self._lock:
            entries = self._load_index()
            entries.insert(0, {"id": entry_id, "pinned": False, **metadata})

            # Evict oldest unpinned entries beyond limit
            unpinned = [e for e in entries if not e.get("pinned")]
            while len(unpinned) > HISTORY_MAX_ENTRIES:
                old = unpinned.pop()
                entries.remove(old)
                old_wav = HISTORY_DIR / f"{old['id']}.wav"
                if old_wav.exists():
                    old_wav.unlink()

            self._save_index(entries)

    def list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            entries = self._load_index()
        return entries[:limit]

    def get_audio(self, entry_id: str) -> bytes:
        wav_path = HISTORY_DIR / f"{entry_id}.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"History audio not found: {entry_id}")
        return wav_path.read_bytes()

    def pin(self, entry_id: str, pinned: bool = True):
        with self._lock:
            entries = self._load_index()
            for e in entries:
                if e["id"] == entry_id:
                    e["pinned"] = pinned
                    break
            else:
                raise FileNotFoundError(f"History entry not found: {entry_id}")
            self._save_index(entries)

    def delete(self, entry_id: str):
        with self._lock:
            entries = self._load_index()
            entries = [e for e in entries if e["id"] != entry_id]
            self._save_index(entries)

        wav_path = HISTORY_DIR / f"{entry_id}.wav"
        if wav_path.exists():
            wav_path.unlink()

    def clear(self):
        with self._lock:
            entries = self._load_index()
            # Only clear unpinned entries
            pinned = [e for e in entries if e.get("pinned")]
            for e in entries:
                if not e.get("pinned"):
                    wav_path = HISTORY_DIR / f"{e['id']}.wav"
                    if wav_path.exists():
                        wav_path.unlink()
            self._save_index(pinned)
