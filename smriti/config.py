"""
config.py — Central configuration store for Smriti.

Wraps QSettings so the rest of the app never touches raw ini/registry
keys directly. Add a new setting by adding one line to DEFAULTS and,
if it needs a dedicated accessor, one get_x/set_x pair below.
"""

from __future__ import annotations
from PySide6.QtCore import QSettings, QObject, Signal

ORG_NAME = "AryamanTools"
APP_NAME = "Smriti"

# Every setting the app knows about, with its default value.
# Types are inferred from the default's Python type.
DEFAULTS = {
    # --- Timing ---
    "timing/display_seconds": 50,        # how long a popup stays visible
    "timing/interval_seconds": 200,       # gap between popups
    "timing/enabled": True,               # master pause/resume switch

    # --- Appearance ---
    "appearance/width": 460,
    "appearance/height": 190,
    "appearance/corner_radius": 18,
    "appearance/bg_color": "#1e1f29",
    "appearance/bg_opacity": 0.94,         # 0.0 - 1.0
    "appearance/accent_color": "#c9a15a",  # gold-ish accent
    "appearance/text_color": "#f2ede3",
    "appearance/font_family": "Georgia",
    "appearance/font_size": 20,
    "appearance/show_border": True,
    "appearance/border_width": 1,
    "appearance/blur_shadow": True,
    "appearance/theme": "dark",            # "dark" or "light"

    # --- Behaviour ---
    "behaviour/click_through": False,
    "behaviour/remember_position": True,
    "behaviour/last_x": -1,                # -1 == "not set yet"
    "behaviour/last_y": -1,
    "behaviour/order": "shuffle",          # "sequential" or "shuffle"
    "behaviour/fade_ms": 350,
    "behaviour/max_meaning_height": 520,

    # --- Content ---
    "content/csv_path": "shlokas.csv",
    "content/last_index": 0,

    # --- Hotkeys ---
    "hotkeys/dismiss": "ctrl+alt+x",
    "hotkeys/enabled": True,

    # --- Startup ---
    "startup/launch_with_windows": False,
    "startup/start_paused": False,
}


class Config(QObject):
    """Typed, signal-emitting wrapper around QSettings."""

    changed = Signal(str, object)  # key, new_value

    def __init__(self):
        super().__init__()
        self._settings = QSettings(ORG_NAME, APP_NAME)

    def get(self, key: str):
        default = DEFAULTS.get(key)
        value = self._settings.value(key, default)
        # QSettings returns strings for everything on some platforms;
        # coerce back to the type of the default.
        if default is not None and value is not None:
            if isinstance(default, bool):
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                else:
                    value = bool(value)
            elif isinstance(default, int) and not isinstance(default, bool):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            elif isinstance(default, float):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = default
        return value

    def set(self, key: str, value) -> None:
        self._settings.setValue(key, value)
        self.changed.emit(key, value)

    def reset_all(self) -> None:
        for key, value in DEFAULTS.items():
            self._settings.setValue(key, value)
            self.changed.emit(key, value)

    def reset_key(self, key: str) -> None:
        default = DEFAULTS.get(key)
        self._settings.setValue(key, default)
        self.changed.emit(key, default)

    def sync(self) -> None:
        self._settings.sync()


# Single shared instance used across the whole app.
config = Config()
