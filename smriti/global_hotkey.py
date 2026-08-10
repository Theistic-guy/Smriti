"""
global_hotkey.py — Thin wrapper around the optional 'keyboard' package.

Global hotkeys need OS-level hooks; on Linux this may need extra
permissions, and on some systems the 'keyboard' package needs to be
run as root. We degrade gracefully: if registration fails, the app
keeps working, it just won't respond to the dismiss hotkey (the popup
can always be closed by right-click or the tray menu instead).
"""

from __future__ import annotations
from typing import Callable, Optional

try:
    import keyboard  # type: ignore
    _KEYBOARD_AVAILABLE = True
except Exception:
    _KEYBOARD_AVAILABLE = False


class HotkeyManager:
    def __init__(self):
        self._registered_hotkey: Optional[str] = None
        self.last_error: Optional[str] = None

    @property
    def available(self) -> bool:
        return _KEYBOARD_AVAILABLE

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        self.unregister()
        if not _KEYBOARD_AVAILABLE or not hotkey:
            return False
        try:
            keyboard.add_hotkey(hotkey, callback)
            self._registered_hotkey = hotkey
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def unregister(self) -> None:
        if _KEYBOARD_AVAILABLE and self._registered_hotkey:
            try:
                keyboard.remove_hotkey(self._registered_hotkey)
            except Exception:
                pass
            self._registered_hotkey = None
