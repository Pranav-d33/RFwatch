"""Thread-safe storage for inferred emitters.

Emitters are identity hypotheses built from many closed events.
The UI reads from here; the engine writes to here.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Dict, List, Optional


class EmitterStore:
    """Thread-safe central storage for emitters."""

    def __init__(self, max_history: int = 1000):
        self.active_emitters: Dict[str, object] = {}
        self.history: deque = deque(maxlen=max_history)
        self.lock = threading.RLock()
        self.emitter_callbacks = []  # callback(action, emitter)

    def add(self, emitter) -> None:
        with self.lock:
            self.active_emitters[getattr(emitter, "id")] = emitter
            self._notify_callbacks("added", emitter)

    def close(self, emitter_id: str) -> Optional[object]:
        with self.lock:
            emitter = self.active_emitters.pop(emitter_id, None)
            if emitter is None:
                return None
            self.history.append(emitter)
            self._notify_callbacks("closed", emitter)
            return emitter

    def get_active(self) -> List[object]:
        with self.lock:
            return list(self.active_emitters.values())

    def get_history(self, limit: Optional[int] = None) -> List[object]:
        with self.lock:
            if limit is None:
                return list(reversed(self.history))
            return list(reversed(list(self.history)[-limit:]))

    def get_emitter(self, emitter_id: str) -> Optional[object]:
        with self.lock:
            if emitter_id in self.active_emitters:
                return self.active_emitters[emitter_id]
            for emitter in self.history:
                if getattr(emitter, "id", None) == emitter_id:
                    return emitter
            return None

    def clear_all(self) -> None:
        with self.lock:
            self.active_emitters.clear()
            self.history.clear()

    def export_dict(self) -> dict:
        with self.lock:
            active = [getattr(e, "to_dict")() for e in self.active_emitters.values() if hasattr(e, "to_dict")]
            history = [getattr(e, "to_dict")() for e in list(self.history) if hasattr(e, "to_dict")]
        return {"active": active, "history": history}

    def register_callback(self, callback) -> None:
        with self.lock:
            self.emitter_callbacks.append(callback)

    def _notify_callbacks(self, action: str, emitter) -> None:
        for cb in self.emitter_callbacks:
            try:
                cb(action, emitter)
            except Exception as e:
                print(f"Error in emitter callback: {e}")
