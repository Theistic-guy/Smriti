"""
tray.py — System tray icon + context menu.

This is the app's only persistent UI chrome. Everything else (popup,
settings) is opened from here.
"""

from __future__ import annotations
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import Qt, Signal, QObject


import os

def get_icon() -> QIcon:
    """Load the Smriti logo."""
    icon_path = os.path.join(os.path.dirname(__file__), "smriti_icon.svg")
    return QIcon(icon_path)


class SmritiTray(QObject):
    settings_requested = Signal()
    show_now_requested = Signal()
    next_requested = Signal()
    pause_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.icon = QSystemTrayIcon(get_icon())
        self.icon.setToolTip("Smriti — daily shloka reminders")

        self.menu = QMenu()

        self.action_show_now = self.menu.addAction("Show a shloka now")
        self.action_show_now.triggered.connect(self.show_now_requested.emit)

        self.action_next = self.menu.addAction("Next shloka")
        self.action_next.triggered.connect(self.next_requested.emit)

        self.menu.addSeparator()

        self.action_pause = self.menu.addAction("Pause")
        self.action_pause.setCheckable(True)
        self.action_pause.setChecked(not config.get("timing/enabled"))
        self.action_pause.toggled.connect(self._on_pause_toggled)

        self.menu.addSeparator()

        self.action_settings = self.menu.addAction("Settings…")
        self.action_settings.triggered.connect(self.settings_requested.emit)

        self.menu.addSeparator()

        self.action_quit = self.menu.addAction("Quit Smriti")
        self.action_quit.triggered.connect(self.quit_requested.emit)

        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)

    def _on_pause_toggled(self, checked: bool):
        self._config.set("timing/enabled", not checked)
        self.action_pause.setText("Resume" if checked else "Pause")
        self.pause_toggled.emit(checked)

    def _on_activated(self, reason):
        # Left click (Trigger) opens settings, matching the request:
        # "clicking on it from there would bring a settings panel".
        if reason == QSystemTrayIcon.Trigger:
            self.settings_requested.emit()

    def show(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self.icon.show()
        return True

    def notify(self, title: str, message: str):
        self.icon.showMessage(title, message, QSystemTrayIcon.Information, 3000)
