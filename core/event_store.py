"""
Central event storage and history management.

Responsibilities:
- Store active and completed events
- Provide thread-safe access
- Manage event lifecycle

UI reads from here.
Detector writes to here.
"""

import threading
from typing import List, Optional, Dict
from collections import deque
from .event import SignalEvent


class EventStore:
    """Thread-safe central storage for signal events."""

    def __init__(self, max_history: int = 1000):
        """
        Initialize event store.

        Args:
            max_history: Maximum number of completed events to retain
        """
        self.active_events: Dict[str, SignalEvent] = {}
        self.history: deque = deque(maxlen=max_history)
        self.lock = threading.RLock()
        self.event_callbacks = []  # List of callbacks on event changes

    def add(self, event: SignalEvent) -> None:
        """
        Add or update an event.

        Args:
            event: SignalEvent to add/update
        """
        with self.lock:
            self.active_events[event.id] = event
            self._notify_callbacks("added", event)

    def close(self, event_id: str, end_time: float) -> Optional[SignalEvent]:
        """
        Close an active event and move to history.

        Args:
            event_id: ID of event to close
            end_time: Absolute end time

        Returns:
            The closed event, or None if not found
        """
        with self.lock:
            event = self.active_events.pop(event_id, None)
            if event:
                event.close(end_time)
                self.history.append(event)
                self._notify_callbacks("closed", event)
                return event
            return None

    def get_active(self) -> List[SignalEvent]:
        """Get list of active events."""
        with self.lock:
            return list(self.active_events.values())

    def get_history(self, limit: Optional[int] = None) -> List[SignalEvent]:
        """
        Get completed event history.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of completed events (most recent first)
        """
        with self.lock:
            if limit is None:
                return list(reversed(self.history))
            else:
                return list(reversed(list(self.history)[-limit:]))

    def get_event(self, event_id: str) -> Optional[SignalEvent]:
        """Get event by ID from active or history."""
        with self.lock:
            # Check active first
            if event_id in self.active_events:
                return self.active_events[event_id]

            # Search history
            for event in self.history:
                if event.id == event_id:
                    return event
            return None

    def clear_history(self) -> None:
        """Clear all historical events."""
        with self.lock:
            self.history.clear()

    def clear_all(self) -> None:
        """Clear active events and history."""
        with self.lock:
            self.active_events.clear()
            self.history.clear()

    def export_dict(self) -> dict:
        """Return a JSON-serializable snapshot of current events."""
        with self.lock:
            active = [e.to_dict() for e in self.active_events.values()]
            history = [e.to_dict() for e in list(self.history)]
        return {
            "active": active,
            "history": history,
        }

    def register_callback(self, callback) -> None:
        """
        Register callback for event changes.

        Callback signature: callback(action, event)
        where action is 'added' or 'closed'
        """
        with self.lock:
            self.event_callbacks.append(callback)

    def _notify_callbacks(self, action: str, event: SignalEvent) -> None:
        """Internal: notify all registered callbacks."""
        for callback in self.event_callbacks:
            try:
                callback(action, event)
            except Exception as e:
                print(f"Error in event callback: {e}")
