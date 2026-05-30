"""Settings persistence for RF Inspector UI.

Stores user preferences for waterfall visualization and other UI settings
in a JSON file in the user's home directory.
"""

import json
import os
from pathlib import Path


def _get_settings_path() -> Path:
    """Get the path to the settings file."""
    home = Path.home()
    config_dir = home / ".rfwatch"
    config_dir.mkdir(exist_ok=True, parents=True)
    return config_dir / "settings.json"


def load_settings() -> dict:
    """Load settings from file or return defaults.
    
    Returns:
        dict: Settings dictionary with keys:
            - waterfall: {enabled, palette, range_db}
            - spectrum: {rgba, line_width, fill_enabled, fill_alpha}
            - other UI state
    """
    settings_file = _get_settings_path()
    
    defaults = {
        "waterfall": {
            "enabled": False,  # Waterfall OFF by default (safe)
            "palette": "viridis",  # Perceptually uniform default
            "range_db": 60.0,
        },
        "spectrum": {
            "rgba": [88, 166, 255, 255],
            "line_width": 1.5,
            "fill_enabled": False,
            "fill_alpha": 60,
        },
    }
    
    if not settings_file.exists():
        return defaults
    
    try:
        with open(settings_file, "r") as f:
            loaded = json.load(f)
        # Merge with defaults to ensure all keys exist
        settings = defaults.copy()
        settings.update(loaded)
        return settings
    except Exception as e:
        print(f"[SETTINGS] Error loading settings: {e}, using defaults")
        return defaults


def save_settings(settings: dict) -> None:
    """Save settings to file.
    
    Args:
        settings: Dictionary of settings to persist
    """
    settings_file = _get_settings_path()
    
    try:
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[SETTINGS] Error saving settings: {e}")
