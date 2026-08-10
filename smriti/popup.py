"""
popup.py — The floating shloka card.

Default view shows only the Sanskrit verse and its reference tag.
Two small icon-only buttons sit in the top-right corner:
  - an "i" (meaning) button that reveals the translation in place,
    expanding the card's height to fit it. While the meaning is open,
    the auto-hide timer is paused (via meaning_toggled signal) so a
    long translation is never cut off mid-read.
  - a "×" (close) button that dismisses the popup immediately.

Both are QToolButtons with NoFocus policy and autoRaise styling, so
neither can trigger a platform "beep" (which normally comes from a
button reacting to Enter/Return as an implicit default action — these
buttons are never focusable, so that can't happen) and neither steals
keyboard focus from whatever the user was doing.

Layout note: how tall the card must grow to fit the translation
(_expand_for_meaning) and where the translation actually gets painted
(paintEvent) both go through the single `_compute_layout` helper below.
They used to use two independently-hand-tuned formulas that quietly
disagreed by ~10-20px, which clipped the last line of the translation.
Routing both through one function makes that class of bug impossible —
whatever height is reserved is exactly the height that's painted into,
at any font size.
"""

from __future__ import annotations
from PySide6.QtWidgets import QWidget, QToolButton
from PySide6.QtCore import Qt, QPoint, QRectF, QPropertyAnimation, QEasingCurve, Signal, QSize
from PySide6.QtGui import QPainter, QColor, QPainterPath, QFont, QFontMetrics

from .config import config
from .shloka_source import Shloka

BUTTON_SIZE = 28
BUTTON_MARGIN = 10

CARD_PAD = 22                                    # inner padding on all sides
TOP_CLEAR = BUTTON_SIZE + BUTTON_MARGIN + 6       # room reserved for the icon buttons
SECTION_GAP = 12                                  # gap: sanskrit -> separator
SEP_GAP = 10                                      # gap: separator -> translation
BOTTOM_PAD = 16                                   # breathing room below everything
TEXT_SAFETY_BUFFER = 4                            # small cushion against font metric rounding


class _IconButton(QToolButton):
    """Small circular, icon-only, flat button that never takes focus
    or plays a system sound when clicked."""

    def __init__(self, glyph: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setText(glyph)
        self.setToolTip(tooltip)
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setStyleSheet(self._style())

    def set_active(self, active: bool):
        self.setStyleSheet(self._style(active))

    @staticmethod
    def _style(active: bool = False) -> str:
        bg = "rgba(201,161,90,0.28)" if active else "rgba(255,255,255,0.08)"
        return f"""
            QToolButton {{
                background: {bg};
                color: #f2ede3;
                border: none;
                border-radius: {BUTTON_SIZE // 2}px;
                font-size: 13px;
            }}
            QToolButton:hover {{
                background: rgba(201,161,90,0.35);
            }}
            QToolButton:pressed {{
                background: rgba(201,161,90,0.5);
            }}
        """


class PopupWindow(QWidget):
    dismissed = Signal()
    next_requested = Signal()
    prev_requested = Signal()
    meaning_toggled = Signal(bool)   # True while meaning is expanded/open

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._drag_offset: QPoint | None = None
        self._shloka: Shloka | None = None
        self._meaning_open = False
        self._base_height = config.get("appearance/height")

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_finished_callback = None
        # Connected once, permanently — avoids the connect/disconnect
        # churn (and the "Failed to disconnect" warning) that came from
        # rewiring this signal on every fade-out.
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._resize_anim = QPropertyAnimation(self, b"size")
        self._resize_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._resize_anim.setDuration(220)

        self.close_btn = _IconButton("\u2715", "Close", self)   # ✕
        self.close_btn.clicked.connect(lambda: self.dismiss())

        self.meaning_btn = _IconButton("\u24d8", "Show meaning", self)  # ⓘ
        self.meaning_btn.clicked.connect(self.toggle_meaning)

        self._apply_geometry_from_config()
        self._restore_position()
        self._position_buttons()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_shloka(self, shloka: Shloka) -> None:
        self._shloka = shloka
        self._meaning_open = False
        self.meaning_btn.set_active(False)
        self._base_height = config.get("appearance/height")
        self.resize(config.get("appearance/width"), self._base_height)
        self._restore_position()
        self._position_buttons()
        self.update()
        self.show()
        self.raise_()
        self._fade_in()

    def dismiss(self, emit_signal: bool = True) -> None:
        if self._meaning_open:
            self._meaning_open = False
            self.meaning_toggled.emit(False)
        self._fade_out(on_finished=self.hide)
        if emit_signal:
            self.dismissed.emit()

    def refresh_appearance(self) -> None:
        """Called when a color/font/border/radius setting changes while
        this popup may already be on screen — just needs a repaint,
        no resize."""
        self.update()

    def refresh_geometry(self) -> None:
        """Called when width/height changes while the popup may already
        be on screen. Leaves an in-progress meaning view's height alone
        (only the width is live-applied then) so we don't yank the card
        out from under someone mid-read."""
        new_width = config.get("appearance/width")
        self._base_height = config.get("appearance/height")
        if self._meaning_open:
            self.resize(new_width, self.height())
        else:
            self.resize(new_width, self._base_height)
        self._position_buttons()
        self.update()

    def toggle_meaning(self) -> None:
        self._meaning_open = not self._meaning_open
        self.meaning_btn.set_active(self._meaning_open)
        self.meaning_toggled.emit(self._meaning_open)
        if self._meaning_open:
            self._expand_for_meaning()
        else:
            self._collapse_from_meaning()
        self.update()

    # ------------------------------------------------------------------
    # Layout — the single source of truth for both sizing and painting
    # ------------------------------------------------------------------
    def _compute_layout(self, card_width: float, meaning_open: bool) -> dict:
        """Every measurement needed to lay out the card's text, derived
        fresh from the current font settings and the actual shloka text.
        Used identically by _expand_for_meaning (to decide how tall the
        card needs to be) and by paintEvent (to decide where things go)
        so the two can never drift apart."""
        font_family = config.get("appearance/font_family")
        base_size = config.get("appearance/font_size")
        text_width = max(card_width - 2 * CARD_PAD, 1)

        sans_h = 0
        if self._shloka:
            sans_font = QFont(font_family, base_size)
            sans_font.setBold(True)
            sans_h = QFontMetrics(sans_font).boundingRect(
                0, 0, int(text_width), 5000, Qt.TextWordWrap, self._shloka.sanskrit
            ).height()

        trans_h = 0
        if meaning_open and self._shloka and self._shloka.translation:
            trans_font = QFont(font_family, max(base_size - 5, 8))
            trans_h = QFontMetrics(trans_font).boundingRect(
                0, 0, int(text_width), 5000, Qt.TextWordWrap, self._shloka.translation
            ).height()

        ref_h = 0
        if self._shloka and self._shloka.reference:
            ref_font = QFont(font_family, max(base_size - 7, 7))
            ref_h = QFontMetrics(ref_font).height()

        return {
            "text_width": text_width,
            "sans_h": sans_h,
            "trans_h": trans_h,
            "ref_h": ref_h,
        }

    # ------------------------------------------------------------------
    # Expand / collapse to fit the translation
    # ------------------------------------------------------------------
    def _expand_for_meaning(self) -> None:
        layout = self._compute_layout(self.width(), meaning_open=True)
        needed = (
            TOP_CLEAR + layout["sans_h"] + SECTION_GAP + SEP_GAP
            + layout["trans_h"] + TEXT_SAFETY_BUFFER + BOTTOM_PAD + layout["ref_h"]
        )
        max_h = config.get("behaviour/max_meaning_height")
        new_height = min(max(needed, self._base_height), max_h)
        self._animate_resize(new_height)

    def _collapse_from_meaning(self) -> None:
        self._animate_resize(self._base_height)

    def _animate_resize(self, new_height: float) -> None:
        self._resize_anim.stop()
        self._resize_anim.setStartValue(self.size())
        self._resize_anim.setEndValue(QSize(self.width(), int(new_height)))
        self._resize_anim.start()
        # Keep the card fully on-screen as it grows downward.
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            bottom = self.y() + new_height
            if bottom > screen.bottom():
                self.move(self.x(), max(screen.top(), screen.bottom() - int(new_height)))

    # ------------------------------------------------------------------
    # Geometry / persistence
    # ------------------------------------------------------------------
    def _apply_geometry_from_config(self) -> None:
        w = config.get("appearance/width")
        h = config.get("appearance/height")
        self._base_height = h
        self.resize(w, h)

    def _restore_position(self) -> None:
        if config.get("behaviour/remember_position"):
            x = config.get("behaviour/last_x")
            y = config.get("behaviour/last_y")
            if x >= 0 and y >= 0:
                self.move(x, y)
                return
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            self.move(screen.right() - self.width() - 24,
                      screen.bottom() - self.height() - 24)

    def _save_position(self) -> None:
        if config.get("behaviour/remember_position"):
            config.set("behaviour/last_x", self.x())
            config.set("behaviour/last_y", self.y())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_buttons()

    def _position_buttons(self) -> None:
        x = self.width() - BUTTON_MARGIN - BUTTON_SIZE
        self.close_btn.move(x, BUTTON_MARGIN)
        self.meaning_btn.move(x - BUTTON_SIZE - 6, BUTTON_MARGIN)

    # ------------------------------------------------------------------
    # Fade animation helpers
    # ------------------------------------------------------------------
    def _fade_in(self):
        dur = config.get("behaviour/fade_ms")
        self._fade_anim.stop()
        self.setWindowOpacity(0.0)
        self._fade_anim.setDuration(dur)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_finished_callback = None
        self._fade_anim.start()

    def _fade_out(self, on_finished=None):
        dur = config.get("behaviour/fade_ms")
        self._fade_anim.stop()
        self._fade_anim.setDuration(dur)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_finished_callback = on_finished
        self._fade_anim.start()

    def _on_fade_finished(self):
        cb = self._fade_finished_callback
        self._fade_finished_callback = None
        if cb is not None:
            cb()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        radius = config.get("appearance/corner_radius")
        bg = QColor(config.get("appearance/bg_color"))
        bg.setAlphaF(config.get("appearance/bg_opacity"))
        accent = QColor(config.get("appearance/accent_color"))
        text_color = QColor(config.get("appearance/text_color"))

        card_rect = QRectF(0, 0, self.width(), self.height())

        path = QPainterPath()
        path.addRoundedRect(card_rect, radius, radius)
        painter.fillPath(path, bg)

        if config.get("appearance/show_border"):
            pen_w = config.get("appearance/border_width")
            painter.setPen(accent)
            painter.setBrush(Qt.NoBrush)
            inset = pen_w / 2
            painter.drawRoundedRect(
                card_rect.adjusted(inset, inset, -inset, -inset), radius, radius
            )

        bar_rect = QRectF(card_rect.left(), card_rect.top() + radius * 0.4, 4,
                           card_rect.height() - radius * 0.8)
        bar_path = QPainterPath()
        bar_path.addRoundedRect(bar_rect, 2, 2)
        painter.fillPath(bar_path, accent)

        if self._shloka is None:
            return

        layout = self._compute_layout(self.width(), meaning_open=self._meaning_open)
        font_family = config.get("appearance/font_family")
        base_size = config.get("appearance/font_size")

        content_left = card_rect.left() + CARD_PAD
        content_width = layout["text_width"]
        y = card_rect.top() + TOP_CLEAR

        sans_font = QFont(font_family, base_size)
        sans_font.setBold(True)
        painter.setFont(sans_font)
        painter.setPen(text_color)
        # Height here is generous on purpose (down to the card bottom) —
        # the text is top-aligned and naturally stops after sans_h, so
        # extra room below is harmless; what matters is text_width for
        # wrapping, which is exact.
        sans_rect = QRectF(content_left, y, content_width, card_rect.bottom() - y)
        painter.drawText(sans_rect, Qt.AlignLeft | Qt.TextWordWrap, self._shloka.sanskrit)
        y += layout["sans_h"] + SECTION_GAP

        if self._meaning_open and self._shloka.translation:
            painter.setPen(QColor(accent).darker(105))
            painter.drawLine(int(content_left), int(y),
                              int(content_left + content_width), int(y))
            y += SEP_GAP

            trans_font = QFont(font_family, max(base_size - 5, 8))
            painter.setFont(trans_font)
            painter.setPen(QColor(text_color).lighter(120))
            # Exactly the height the sizing pass reserved (+ a tiny
            # safety buffer) — this is what used to be shorter than the
            # actual text and clip the last line.
            trans_rect = QRectF(content_left, y, content_width,
                                 layout["trans_h"] + TEXT_SAFETY_BUFFER)
            painter.drawText(trans_rect, Qt.AlignLeft | Qt.TextWordWrap,
                              self._shloka.translation)

        if self._shloka.reference:
            ref_font = QFont(font_family, max(base_size - 7, 7))
            painter.setFont(ref_font)
            painter.setPen(accent)
            fm = QFontMetrics(ref_font)
            painter.drawText(
                QRectF(content_left, card_rect.bottom() - fm.height() - 8,
                       content_width, fm.height()),
                Qt.AlignRight, self._shloka.reference,
            )

    # ------------------------------------------------------------------
    # Dragging (background only — clicks on the icon buttons are
    # consumed by those child widgets before reaching here)
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self._save_position()

    def wheelEvent(self, event):
        if self._meaning_open:
            return  # don't switch shlokas mid-read
        if event.angleDelta().y() > 0:
            self.prev_requested.emit()
        else:
            self.next_requested.emit()

    def mouseDoubleClickEvent(self, event):
        if not self._meaning_open:
            self.next_requested.emit()