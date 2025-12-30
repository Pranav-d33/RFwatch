from PySide6.QtCore import QObject, Signal


class EventPublisher(QObject):
    """Qt signal bridge for event updates/closures from engine to UI."""

    event_updated = Signal(object)  # SignalEvent
    event_closed = Signal(object)   # SignalEvent

    def __init__(self, parent=None):
        # Proper QObject initialisation so signals/slots are safe.
        super().__init__(parent)
