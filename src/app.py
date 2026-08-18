"""
app.py — Wires together the tray icon, popup, settings dialog, shloka
source and timers into a running application. This is the "controller"
layer; main.py just constructs a QApplication and this class.

Timing model (deliberately simple, two knobs only):
  - timing/display_seconds  — how long a popup stays visible once shown.
  - timing/interval_seconds — how long to wait, after a popup has
    disappeared, before the next one appears.
These are sequential, not parallel: show -> wait display_seconds ->
disappear -> wait interval_seconds -> show next -> ... A single
QTimer (`cycle_timer`) is (re)armed only once a popup is actually gone,
so the two settings can't fight each other or drift out of sync.
"""

from __future__ import annotations
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QObject, Signal

from .config import config
from .shloka_source import ShlokaSource
from .popup import PopupWindow
from .tray import SmritiTray
from .settings_dialog import SettingsDialog
from .global_hotkey import HotkeyManager


class _HotkeyBridge(QObject):
    """
    The 'keyboard' library fires callbacks on its own OS-hook thread.
    Touching widgets from there is unsafe, so the callback just emits
    this signal; Qt automatically queues delivery to the main thread
    since the receiver lives on the GUI thread.
    """
    dismiss_requested = Signal()


class SmritiApp:
    def __init__(self, app: QApplication):
        self.app = app
        app.setQuitOnLastWindowClosed(False)  # tray-only app: closing popup != quitting

        # Reset the master pause state on launch based on the startup preference.
        # This prevents a pause from a previous session from getting stuck and
        # causing the app to launch paused every time.
        config.set("timing/enabled", not config.get("startup/start_paused"))

        self.source = ShlokaSource()
        self.popup = PopupWindow()
        self.tray = SmritiTray(config)
        self.settings_dialog: SettingsDialog | None = None
        self.hotkeys = HotkeyManager()
        self._hotkey_bridge = _HotkeyBridge()
        self._hotkey_bridge.dismiss_requested.connect(lambda: self.popup.dismiss())

        # --- Timers ---
        # hide_timer: counts down while a popup is visible; on timeout,
        # auto-hides it.
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._auto_hide)

        # cycle_timer: counts down while nothing is visible; on timeout,
        # shows the next popup. Only ever armed once a popup has
        # actually disappeared (see _schedule_next_cycle), never while
        # one is showing — that's what keeps "time between popups"
        # meaning exactly what it says instead of racing display_seconds.
        self.cycle_timer = QTimer()
        self.cycle_timer.setSingleShot(True)
        self.cycle_timer.timeout.connect(lambda: self._spawn_popup(advance=True))

        # --- Wiring ---
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.show_now_requested.connect(lambda: self._spawn_popup(advance=True))
        self.tray.next_requested.connect(self._show_next)
        self.tray.pause_toggled.connect(self._on_pause_toggled)
        self.tray.quit_requested.connect(self.quit)

        self.popup.dismissed.connect(self._on_popup_dismissed)
        self.popup.next_requested.connect(self._show_next)
        self.popup.prev_requested.connect(self._show_prev)
        self.popup.pause_requested.connect(lambda: self.tray.action_pause.setChecked(True))
        self.popup.settings_requested.connect(self.open_settings)
        self.popup.meaning_toggled.connect(self._on_meaning_toggled)

        config.changed.connect(self._on_config_changed)

        self._register_hotkey()

        if not config.get("startup/start_paused"):
            # Show one immediately so the app doesn't feel dead on launch.
            # advance=False: resume on whatever the cycle left off at,
            # don't skip ahead before the user has seen anything.
            QTimer.singleShot(800, lambda: self._spawn_popup(advance=False))

        if not self.tray.show():
            print("Warning: system tray is not available on this system.")

        if not config.get("timing/enabled"):
            # This is persisted across restarts via QSettings, so a
            # "Pause" left on from a previous session otherwise makes
            # every future launch look dead with zero explanation.
            print("[Smriti] Starting paused (resume from the tray menu).")
            QTimer.singleShot(
                1200,
                lambda: self.tray.notify(
                    "Smriti is paused",
                    "Right-click the tray icon and hit Resume to see popups again.",
                ),
            )

    # ------------------------------------------------------------------
    # Popup lifecycle
    # ------------------------------------------------------------------
    def _spawn_popup(self, advance: bool = True):
        """Show a shloka right now. advance=True (the default) moves to
        the next item in the cycle first; advance=False re-shows
        whatever's currently selected (used for the first popup on
        launch and right after a fresh reshuffle)."""
        if not config.get("timing/enabled"):
            return
        shloka = self.source.next() if advance else self.source.current()
        if shloka is None:
            return
        # This show supersedes any pending "show the next one" wait.
        self.cycle_timer.stop()
        self.popup.show_shloka(shloka)
        self.hide_timer.start(config.get("timing/display_seconds") * 1000)

    def _auto_hide(self):
        # emit_signal=False: this path already knows it's disappearing
        # because display_seconds elapsed, so it schedules the next
        # cycle itself rather than round-tripping through the
        # `dismissed` signal.
        self.popup.dismiss(emit_signal=False)
        self._schedule_next_cycle()

    def _on_popup_dismissed(self):
        # Fired when the popup is closed some other way (× button,
        # global hotkey). Either way, it's now gone, so start counting
        # down interval_seconds until the next one — same as auto-hide.
        self.hide_timer.stop()
        self._schedule_next_cycle()

    def _show_next(self):
        shloka = self.source.next()
        if shloka:
            self.cycle_timer.stop()
            self.popup.show_shloka(shloka)
            self.hide_timer.start(config.get("timing/display_seconds") * 1000)

    def _show_prev(self):
        shloka = self.source.previous()
        if shloka:
            self.cycle_timer.stop()
            self.popup.show_shloka(shloka)
            self.hide_timer.start(config.get("timing/display_seconds") * 1000)

    def _on_meaning_toggled(self, is_open: bool):
        # Never let the auto-hide timer cut off someone mid-read.
        if is_open:
            self.hide_timer.stop()
        else:
            self.hide_timer.start(config.get("timing/display_seconds") * 1000)

    def _restart_cycle(self):
        self.source.reshuffle(force_random=True)
        # advance=False: show the fresh shuffle's actual first item,
        # rather than immediately skipping past it to the second.
        self._spawn_popup(advance=False)

    # ------------------------------------------------------------------
    # Timer control
    # ------------------------------------------------------------------
    def _schedule_next_cycle(self):
        """Called only once a popup has actually disappeared. Arms the
        wait for interval_seconds before the next one shows."""
        self.cycle_timer.stop()
        if config.get("timing/enabled"):
            self.cycle_timer.start(config.get("timing/interval_seconds") * 1000)

    def _on_pause_toggled(self, paused: bool):
        if paused:
            # We don't touch the hide_timer or dismiss the popup here.
            # If a popup is showing, it will just finish its normal duration
            # and disappear. After it does, _schedule_next_cycle won't start
            # the next timer because timing/enabled is False.
            self.cycle_timer.stop()
        else:
            # If a popup is already on screen, it will schedule the next cycle
            # automatically when it hides. We only need to manually kickstart
            # the cycle timer if there is no popup currently showing.
            if not self.popup.isVisible():
                self._schedule_next_cycle()

    def _on_config_changed(self, key: str, value):
        if key == "timing/interval_seconds":
            # Only reschedule if we're actually in the waiting gap —
            # if a popup is currently showing, this setting applies the
            # next time the wait starts, not retroactively.
            if self.cycle_timer.isActive():
                self._schedule_next_cycle()
        elif key == "timing/enabled":
            # If the user toggled the "Active" checkbox in the Settings Dialog,
            # we need to sync that state to the tray menu. Setting the tray
            # menu's checked state will automatically trigger the real pause
            # logic (stopping timers and hiding the current popup).
            self.tray.action_pause.setChecked(not value)
        elif key == "content/csv_path":
            self.source.reload()
        elif key in ("hotkeys/dismiss", "hotkeys/enabled"):
            self._register_hotkey()

        if key in ("appearance/width", "appearance/height"):
            self.popup.refresh_geometry()
        elif key.startswith("appearance/"):
            self.popup.refresh_appearance()

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------
    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog()
            self.settings_dialog.preview_requested.connect(lambda: self._spawn_popup(advance=True))
            self.settings_dialog.restart_cycle_requested.connect(self._restart_cycle)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    # ------------------------------------------------------------------
    # Hotkey
    # ------------------------------------------------------------------
    def _register_hotkey(self):
        if not config.get("hotkeys/enabled"):
            self.hotkeys.unregister()
            return

        if not self.hotkeys.available:
            print(
                "[Smriti] WARNING: the 'keyboard' package isn't installed in this "
                "environment, so the dismiss hotkey can't be registered. "
                "Run: pip install keyboard"
            )
            return

        hotkey = config.get("hotkeys/dismiss")
        ok = self.hotkeys.register(hotkey, self._on_hotkey_dismiss)
        if not ok:
            print(
                f"[Smriti] WARNING: failed to register hotkey '{hotkey}' "
                f"({self.hotkeys.last_error or 'unknown error'}). "
                f"On Windows, the 'keyboard' package's global hook usually "
                f"needs the app to be run as Administrator, and the hotkey "
                f"may also be taken by another running app."
            )

    def _on_hotkey_dismiss(self):
        # Called on the 'keyboard' library's own OS-hook thread.
        # Emit a signal instead of touching the popup directly so Qt
        # marshals the call onto the GUI thread safely.
        self._hotkey_bridge.dismiss_requested.emit()

    # ------------------------------------------------------------------
    def quit(self):
        self.hotkeys.unregister()
        config.sync()
        self.app.quit()
