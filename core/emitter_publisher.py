# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

from PySide6.QtCore import QObject, Signal


class EmitterPublisher(QObject):
    """Qt signal bridge for emitter updates/closures from engine to UI."""

    emitter_updated = Signal(object)  # Emitter
    emitter_closed = Signal(object)  # Emitter

    def __init__(self, parent=None):
        super().__init__(parent)
