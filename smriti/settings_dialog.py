"""
settings_dialog.py — The elegant settings panel, opened from the tray.

Organised into tabs: Timing, Appearance, Behaviour, Content, Hotkeys.
Every control is wired directly to Config so changes apply live
(the currently-visible popup, if any, updates its own values on next
paint since it reads straight from Config too).
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QPushButton,
    QLabel, QColorDialog, QFileDialog, QSlider, QFontComboBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from .config import config


class ColorButton(QPushButton):
    """A small button that shows a color swatch and opens a picker."""

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        # Scoped with an objectName selector rather than an unqualified
        # rule, so this swatch's color can never bleed into any other
        # widget in the dialog under the Qt stylesheet cascade — only
        # this exact button matches "QPushButton#colorSwatch".
        self.setObjectName("colorSwatch")
        self.setFixedSize(60, 24)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        color = config.get(self._key)
        self.setStyleSheet(
            f"QPushButton#colorSwatch {{"
            f"background-color: {color}; border: 1px solid #555; border-radius: 4px;"
            f"}}"
        )

    def _pick(self):
        current = QColor(config.get(self._key))
        color = QColorDialog.getColor(current, self, "Choose color")
        if color.isValid():
            config.set(self._key, color.name())
            self._refresh()


class SettingsDialog(QDialog):
    preview_requested = Signal()
    restart_cycle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Smriti — Settings")
        self.setMinimumSize(460, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_timing_tab(), "Timing")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        tabs.addTab(self._build_behaviour_tab(), "Behaviour")
        tabs.addTab(self._build_content_tab(), "Content")
        tabs.addTab(self._build_hotkeys_tab(), "Hotkeys")

        button_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_row.addWidget(reset_btn)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.setStyleSheet(STYLE_SHEET)

    # ------------------------------------------------------------------
    def _build_timing_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        display = QSpinBox()
        display.setRange(3, 3600)
        display.setSuffix(" s")
        display.blockSignals(True)
        display.setValue(config.get("timing/display_seconds"))
        display.blockSignals(False)
        display.valueChanged.connect(lambda v: config.set("timing/display_seconds", v))
        form.addRow("Display duration", display)

        interval = QSpinBox()
        interval.setRange(5, 86400)
        interval.setSuffix(" s")
        interval.blockSignals(True)
        interval.setValue(config.get("timing/interval_seconds"))
        interval.blockSignals(False)
        interval.valueChanged.connect(lambda v: config.set("timing/interval_seconds", v))
        form.addRow("Time between popups", interval)

        enabled = QCheckBox("Active (uncheck to pause popups)")
        enabled.blockSignals(True)
        enabled.setChecked(config.get("timing/enabled"))
        enabled.blockSignals(False)
        enabled.toggled.connect(lambda v: config.set("timing/enabled", v))
        form.addRow(enabled)

        preview_row = QHBoxLayout()
        preview_btn = QPushButton("Preview a shloka now")
        preview_btn.clicked.connect(self.preview_requested.emit)
        restart_btn = QPushButton("Restart random cycle")
        restart_btn.setToolTip(
            "Reshuffles the shloka order and shows one immediately — "
            "handy for previewing appearance changes."
        )
        restart_btn.clicked.connect(self.restart_cycle_requested.emit)
        preview_row.addWidget(preview_btn)
        preview_row.addWidget(restart_btn)
        form.addRow(preview_row)

        return w

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        width = QSpinBox()
        width.setRange(200, 1200)
        width.blockSignals(True)
        width.setValue(config.get("appearance/width"))
        width.blockSignals(False)
        width.valueChanged.connect(lambda v: config.set("appearance/width", v))
        form.addRow("Width (px)", width)

        height = QSpinBox()
        height.setRange(100, 900)
        height.blockSignals(True)
        height.setValue(config.get("appearance/height"))
        height.blockSignals(False)
        height.valueChanged.connect(lambda v: config.set("appearance/height", v))
        form.addRow("Height (px)", height)

        radius = QSpinBox()
        radius.setRange(0, 60)
        radius.blockSignals(True)
        radius.setValue(config.get("appearance/corner_radius"))
        radius.blockSignals(False)
        radius.valueChanged.connect(lambda v: config.set("appearance/corner_radius", v))
        form.addRow("Corner radius", radius)

        bg_color = ColorButton("appearance/bg_color")
        form.addRow("Background color", bg_color)

        opacity = QSlider(Qt.Horizontal)
        opacity.setRange(20, 100)
        opacity.blockSignals(True)
        opacity.setValue(int(config.get("appearance/bg_opacity") * 100))
        opacity.blockSignals(False)
        opacity.valueChanged.connect(lambda v: config.set("appearance/bg_opacity", v / 100))
        form.addRow("Background opacity", opacity)

        accent_color = ColorButton("appearance/accent_color")
        form.addRow("Accent color", accent_color)

        text_color = ColorButton("appearance/text_color")
        form.addRow("Text color", text_color)

        font_combo = QFontComboBox()
        font_combo.blockSignals(True)
        font_combo.setCurrentFont(QFont(config.get("appearance/font_family")))
        font_combo.blockSignals(False)
        font_combo.currentFontChanged.connect(
            lambda f: config.set("appearance/font_family", f.family())
        )
        form.addRow("Font", font_combo)

        font_size = QSpinBox()
        font_size.setRange(7, 60)
        font_size.blockSignals(True)
        font_size.setValue(config.get("appearance/font_size"))
        font_size.blockSignals(False)
        font_size.valueChanged.connect(lambda v: config.set("appearance/font_size", v))
        form.addRow("Font size", font_size)

        border = QCheckBox("Show border")
        border.blockSignals(True)
        border.setChecked(config.get("appearance/show_border"))
        border.blockSignals(False)
        border.toggled.connect(lambda v: config.set("appearance/show_border", v))
        form.addRow(border)

        return w

    def _build_behaviour_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        remember = QCheckBox("Remember last dragged position")
        remember.blockSignals(True)
        remember.setChecked(config.get("behaviour/remember_position"))
        remember.blockSignals(False)
        remember.toggled.connect(lambda v: config.set("behaviour/remember_position", v))
        form.addRow(remember)

        click_through = QCheckBox("Click-through (popup never grabs focus/clicks)")
        click_through.blockSignals(True)
        click_through.setChecked(config.get("behaviour/click_through"))
        click_through.blockSignals(False)
        click_through.toggled.connect(lambda v: config.set("behaviour/click_through", v))
        form.addRow(click_through)

        order = QComboBox()
        order.addItems(["sequential", "shuffle"])
        order.blockSignals(True)
        order.setCurrentText(config.get("behaviour/order"))
        order.blockSignals(False)
        order.currentTextChanged.connect(lambda v: config.set("behaviour/order", v))
        form.addRow("Playback order", order)

        fade = QSpinBox()
        fade.setRange(0, 2000)
        fade.setSuffix(" ms")
        fade.blockSignals(True)
        fade.setValue(config.get("behaviour/fade_ms"))
        fade.blockSignals(False)
        fade.valueChanged.connect(lambda v: config.set("behaviour/fade_ms", v))
        form.addRow("Fade duration", fade)

        max_meaning = QSpinBox()
        max_meaning.setRange(200, 900)
        max_meaning.setSuffix(" px")
        max_meaning.blockSignals(True)
        max_meaning.setValue(config.get("behaviour/max_meaning_height"))
        max_meaning.blockSignals(False)
        max_meaning.valueChanged.connect(lambda v: config.set("behaviour/max_meaning_height", v))
        form.addRow("Max height when meaning is open", max_meaning)

        return w

    def _build_content_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        path_row = QHBoxLayout()
        path_edit = QLineEdit(config.get("content/csv_path"))
        path_edit.setReadOnly(True)
        browse = QPushButton("Browse…")

        def do_browse():
            path, _ = QFileDialog.getOpenFileName(self, "Choose shlokas CSV", "", "CSV Files (*.csv)")
            if path:
                path_edit.setText(path)
                config.set("content/csv_path", path)

        browse.clicked.connect(do_browse)
        path_row.addWidget(path_edit)
        path_row.addWidget(browse)
        form.addRow("Shlokas CSV", path_row)

        hint = QLabel(
            "CSV columns (must match exactly): Reference_Number, Shloka, Translation\n"
            "Changing this reloads the shloka list immediately."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999; font-size: 11px;")
        form.addRow(hint)

        return w

    def _build_hotkeys_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        enabled = QCheckBox("Enable global dismiss hotkey")
        enabled.blockSignals(True)
        enabled.setChecked(config.get("hotkeys/enabled"))
        enabled.blockSignals(False)
        enabled.toggled.connect(lambda v: config.set("hotkeys/enabled", v))
        form.addRow(enabled)

        hotkey_edit = QLineEdit(config.get("hotkeys/dismiss"))
        hotkey_edit.setPlaceholderText("e.g. ctrl+alt+x")
        hotkey_edit.editingFinished.connect(
            lambda: config.set("hotkeys/dismiss", hotkey_edit.text().strip())
        )
        form.addRow("Dismiss popup", hotkey_edit)

        hint = QLabel(
            "Uses the 'keyboard' library's hotkey syntax.\n"
            "Restart the app after changing this for it to re-register."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999; font-size: 11px;")
        form.addRow(hint)
        
        # New quick hide features
        form.addRow(QLabel("")) # Spacer
        
        ctrl_click = QCheckBox("Ctrl+Click on popup to quick hide")
        ctrl_click.blockSignals(True)
        ctrl_click.setChecked(config.get("hotkeys/ctrl_click_hide"))
        ctrl_click.blockSignals(False)
        ctrl_click.toggled.connect(lambda v: config.set("hotkeys/ctrl_click_hide", v))
        form.addRow(ctrl_click)
        
        ctrl_pause = QCheckBox("Also pause the app when quick hiding")
        ctrl_pause.blockSignals(True)
        ctrl_pause.setChecked(config.get("hotkeys/ctrl_click_pause"))
        ctrl_pause.blockSignals(False)
        ctrl_pause.setEnabled(config.get("hotkeys/ctrl_click_hide"))
        ctrl_pause.toggled.connect(lambda v: config.set("hotkeys/ctrl_click_pause", v))
        form.addRow(ctrl_pause)
        
        # Link the two checkboxes
        ctrl_click.toggled.connect(ctrl_pause.setEnabled)

        return w

    # ------------------------------------------------------------------
    def _reset_all(self):
        config.reset_all()
        self.close()


STYLE_SHEET = """
QDialog {
    background-color: #20212b;
    color: #f2ede3;
}
QTabWidget::pane {
    border: 1px solid #383a4a;
    border-radius: 8px;
    background: #24252f;
}
QTabBar::tab {
    background: #20212b;
    color: #b8b3a8;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #2c2d3a;
    color: #f2ede3;
    border-bottom: 2px solid #c9a15a;
}
QLabel { color: #f2ede3; }
QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox, QFontComboBox {
    background: #2c2d3a;
    color: #f2ede3;
    border: 1px solid #444659;
    border-radius: 4px;
    padding: 3px 6px;
}
QPushButton {
    background: #2c2d3a;
    color: #f2ede3;
    border: 1px solid #444659;
    border-radius: 4px;
    padding: 5px 14px;
}
QPushButton:hover {
    background: #383a4a;
    border-color: #c9a15a;
}
QCheckBox { color: #f2ede3; }
QSlider::groove:horizontal {
    height: 4px;
    background: #444659;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #c9a15a;
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
}
"""
