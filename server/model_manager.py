import asyncio
import gc
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import torch

from telemetry import tracer, model_load_duration, model_loaded_gauge

log = logging.getLogger(__name__)


@dataclass
class ModelSlot:
    name: str
    load_fn: Callable[[], Any]
    warmup_fn: Callable[[Any], None] | None = None
    model: Any = None
    last_used: float = 0.0
    loaded: bool = False
    pinned: bool = False  # If True, never idle-unloaded


class ModelManager:
    def __init__(self, idle_timeout: int = 120):
        self._slots: dict[str, ModelSlot] = {}
        self._idle_timeout = idle_timeout
        self._keep_alive_until: float = 0.0
        self._shutdown = False

    def register(
        self,
        name: str,
        load_fn: Callable[[], Any],
        warmup_fn: Callable[[Any], None] | None = None,
        pinned: bool = False,
    ):
        self._slots[name] = ModelSlot(name=name, load_fn=load_fn, warmup_fn=warmup_fn, pinned=pinned)

    def get(self, name: str) -> Any:
        """Return the loaded model, loading + warming up if needed.

        Must be called from within the inference_lock.
        """
        slot = self._slots[name]
        if not slot.loaded:
            with tracer.start_as_current_span("model.load", attributes={"model.name": name}):
                log.info("Loading %s...", name)
                t0 = time.time()
                slot.model = slot.load_fn()
                log.info("%s loaded in %.1fs", name, time.time() - t0)
                if slot.warmup_fn:
                    log.info("Warming up %s...", name)
                    t0_warmup = time.time()
                    slot.warmup_fn(slot.model)
                    log.info("%s warmup done in %.1fs", name, time.time() - t0_warmup)
                model_load_duration.record(time.time() - t0, {"model": name})
            slot.loaded = True
            model_loaded_gauge.add(1, {"model": name})
        slot.last_used = time.time()
        return slot.model

    def unload(self, name: str):
        slot = self._slots[name]
        if not slot.loaded:
            return
        log.info("Unloading %s...", name)
        del slot.model
        slot.model = None
        slot.loaded = False
        model_loaded_gauge.add(-1, {"model": name})
        slot.last_used = 0.0
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log.info("%s unloaded, VRAM freed.", name)

    def keep_alive(self, hours: float):
        """Prevent unloading for the given number of hours."""
        self._keep_alive_until = time.time() + hours * 3600
        remaining = self.keep_alive_remaining()
        log.info("Keep-alive set for %sh (%.0fs)", hours, remaining)

    def keep_alive_remaining(self) -> float:
        """Seconds remaining on keep-alive, 0 if expired."""
        return max(0.0, self._keep_alive_until - time.time())

    def cancel_keep_alive(self):
        self._keep_alive_until = 0.0
        log.info("Keep-alive cancelled.")

    def status(self) -> list[dict]:
        now = time.time()
        result = []
        for name, slot in self._slots.items():
            info = {"name": name, "loaded": slot.loaded}
            if slot.loaded:
                info["idle_seconds"] = round(now - slot.last_used, 1)
            result.append(info)
        return result

    async def idle_checker(self, inference_lock: asyncio.Semaphore):
        """Background task: check every 10s, unload idle models."""
        if self._idle_timeout == 0:
            return  # Never unload
        while not self._shutdown:
            await asyncio.sleep(10)
            if self._shutdown:
                break
            if time.time() < self._keep_alive_until:
                continue
            now = time.time()
            for slot in self._slots.values():
                if slot.pinned:
                    continue
                if slot.loaded and (now - slot.last_used) >= self._idle_timeout:
                    async with inference_lock:
                        # Re-check inside lock — model may have been used
                        if slot.loaded and (time.time() - slot.last_used) >= self._idle_timeout:
                            await asyncio.to_thread(self.unload, slot.name)

    def shutdown(self):
        self._shutdown = True
        for name in list(self._slots):
            self.unload(name)
