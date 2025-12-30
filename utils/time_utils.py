"""
Time utilities for event management.
"""

import time
from datetime import datetime, timedelta


def get_timestamp() -> float:
    """Get current absolute timestamp."""
    return time.time()


def format_timestamp(timestamp: float) -> str:
    """Format timestamp as readable string."""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def duration_to_string(seconds: float) -> str:
    """Convert duration to human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    else:
        minutes = seconds / 60
        return f"{minutes:.2f} m"
