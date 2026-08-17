"""
popup.py — The floating shloka card.

Default view shows only the Sanskrit verse and its reference tag.
The button row is two docked groups:
  - Left: "▼" / "▲" (show more / show less) — nudge the card's height
    up or down a little, purely for this run of the app, so a verse
    whose Sanskrit is getting clipped can be read in full. Never
    written to config — it quietly resets to nothing the next time the
    process starts.
  - Right: "i" (meaning) and "×" (close). "×" is deliberately wider
    than the others so it's easy to hit without carefully aiming.
    Meaning reveals the translation in place, expanding the card's
    height to fit it — while it's open, the auto-hide timer is paused
    (via meaning_toggled signal) so a long translation is never cut
    off mid-read.

All are QToolButtons with NoFocus policy and autoRaise styling, so
none can trigger a platform "beep" (which normally comes from a
button reacting to Enter/Return as an implicit default action — these
buttons are never focusable, so that can't happen) and none steals
keyboard focus from whatever the user was doing.

Layout note: how tall the card must grow to fit the translation
(_expand_for_meaning) and where the translation actually gets painted
(paintEvent) both go through the single `_compute_layout` helper below.
They used to use two independently-hand-tuned formulas that quietly
disagreed by ~10-20px, which clipped the last line of the translation.
Routing both through one function makes that class of bug impossible —
whatever height is reserved is exactly the height that's painted into,
at any font size.

The icon buttons sit at a fixed y derived from the *effective* base
height (configured appearance/height plus any session-only show-more
bump), not from the card's current (possibly meaning-expanded) height
— so they stay put when the meaning view opens; the translation is
painted into the newly-added space *below* them instead.

Click-through note: with behaviour/click_through enabled, a plain
click (press+release with no real movement) on the card's background
is replayed onto whatever's underneath instead of being swallowed —
for every mouse button (left/right/middle) and for wheel scroll alike
— done by very briefly hiding the popup and synthesizing the input via
the Windows API (Windows-only for now). An actual left-button drag
(press+move past a small threshold) is always handled directly by
this widget and never passed through, regardless of the setting, so
the card stays movable either way — right/middle clicks can't drag it,
so those pass through unconditionally on release. Clicks on the icon
buttons are unaffected either way, since they're separate child
widgets that consume their own events before this logic ever runs.
"""

from __future__ import annotations
import ctypes
import sys
from PySide6.QtWidgets import QWidget, QToolButton, QApplication
from PySide6.QtCore import Qt, QPoint, QRectF, QPropertyAnimation, QEasingCurve, Signal, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QPainterPath, QFont, QFontMetrics

from .config import config
from .shloka_source import Shloka

BUTTON_SIZE = 28
BUTTON_MARGIN = 10

CARD_PAD = 22                                    # inner padding on all sides
GAP_REF_TO_BUTTONS = 6                            # gap: reference tag -> button row
GAP_BUTTONS_TO_TRANS = 12                         # gap: button row -> translation (expanded only)
SEP_GAP = 10                                      # gap: separator -> translation
BOTTOM_PAD = 16                                   # breathing room below everything
TEXT_SAFETY_BUFFER = 4                            # small cushion against font metric rounding
DRAG_THRESHOLD_PX = 8                             # movement beyond this counts as a drag, not a click
                                                   # (was 4 — too tight; ordinary hand tremor during
                                                   # a click regularly exceeds a few px, which was
                                                   # silently misfiring as a drag and swallowing the
                                                   # click instead of passing it through)

EXPAND_STEP_PX = 40                               # how much the "show more" button grows the card by, per click
MAX_SESSION_EXTRA_HEIGHT = 320                    # cap on the in-memory-only growth from that button


class _IconButton(QToolButton):
    """Small icon-only, flat button that never takes focus or plays a
    system sound when clicked. Square/circular by default, but width,
    corner radius and glyph size can all be overridden — used for the
    up/down arrows (bigger glyph) and the close button (elongated, for
    a more forgiving hit target)."""

    def __init__(
        self,
        glyph: str,
        tooltip: str,
        parent=None,
        width: int = BUTTON_SIZE,
        height: int = BUTTON_SIZE,
        font_size: int = 13,
        border_radius: int | None = None,
    ):
        super().__init__(parent)
        self.setText(glyph)
        self.setToolTip(tooltip)
        self.setFixedSize(width, height)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self._border_radius = border_radius if border_radius is not None else height // 2
        self._font_size = font_size
        self.setStyleSheet(self._style())

    def set_active(self, active: bool):
        self.setStyleSheet(self._style(active))

    def _style(self, active: bool = False) -> str:
        bg = "rgba(201,161,90,0.28)" if active else "rgba(255,255,255,0.08)"
        return f"""
            QToolButton {{
                background: {bg};
                color: #f2ede3;
                border: none;
                border-radius: {self._border_radius}px;
                font-size: {self._font_size}px;
                font-weight: bold;
            }}
            QToolButton:hover {{
                background: rgba(201,161,90,0.35);
            }}
            QToolButton:pressed {{
                background: rgba(201,161,90,0.5);
            }}
        """


CLOSE_BUTTON_WIDTH = 46                           # elongated so it's easy to hit without careful aiming
ARROW_FONT_SIZE = 16                              # bigger glyph than the default 13px — small triangles
                                                   # at 13px read as an unrecognisable smudge ("d"-ish blob)


class PopupWindow(QWidget):
    dismissed = Signal()
    next_requested = Signal()
    prev_requested = Signal()
    pause_requested = Signal()
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
        self._press_global_pos: QPoint | None = None
        self._is_dragging = False
        self._click_through_pending = False
        self._shloka: Shloka | None = None
        self._meaning_open = False
        self._base_height = config.get("appearance/height")
        # In-memory-only bump from the "show more" button. Never touches
        # config, so it quietly resets to 0 the moment the process
        # restarts — it only exists to survive across popups within a
        # single run, for exactly as long as the app keeps running.
        self._session_extra_height = 0

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

        # Right-docked group: close (elongated hit target) + meaning.
        self.close_btn = _IconButton(
            "\u2715", "Close", self,
            width=CLOSE_BUTTON_WIDTH, border_radius=BUTTON_SIZE // 2,
        )   # ✕
        self.close_btn.clicked.connect(lambda: self.dismiss())

        self.meaning_btn = _IconButton("\u24d8", "Show meaning", self)  # ⓘ
        self.meaning_btn.clicked.connect(self.toggle_meaning)

        # Left-docked group: grow/shrink the text area, session-only.
        self.expand_btn = _IconButton(
            "\u25bc", "Show more (this session only)", self, font_size=ARROW_FONT_SIZE
        )  # ▼
        self.expand_btn.clicked.connect(self._expand_text_area)

        self.shrink_btn = _IconButton(
            "\u25b2", "Show less (this session only)", self, font_size=ARROW_FONT_SIZE
        )  # ▲
        self.shrink_btn.clicked.connect(self._shrink_text_area)

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
        self.resize(config.get("appearance/width"), self._effective_base_height())
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
            self.resize(new_width, self._effective_base_height())
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
    def _effective_base_height(self) -> int:
        """The configured base height, plus whatever the 'show more'
        button has added this session. This — not the raw config
        value — is what the card collapses back to and what the
        button row is anchored against, so an expand sticks around
        across popups until the app restarts, without ever being
        written to config."""
        return self._base_height + self._session_extra_height

    def _button_row_top(self) -> float:
        """Fixed y-position (from the card's top) of the icon buttons —
        anchored to the *effective* base height (configured height plus
        any session-only expand), never to the card's current (possibly
        meaning-expanded) height. That's what keeps the buttons from
        sliding down when the meaning view opens, while still moving
        down — giving the Sanskrit text more room above them — when the
        user presses the expand button."""
        return self._effective_base_height() - BUTTON_MARGIN - BUTTON_SIZE

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
            self._button_row_top() + BUTTON_SIZE + GAP_BUTTONS_TO_TRANS
            + layout["trans_h"] + TEXT_SAFETY_BUFFER + BOTTOM_PAD
        )
        max_h = config.get("behaviour/max_meaning_height")
        new_height = min(max(needed, self._base_height), max_h)
        self._animate_resize(new_height)

    def _collapse_from_meaning(self) -> None:
        self._animate_resize(self._effective_base_height())

    def _expand_text_area(self) -> None:
        """Grow the card by EXPAND_STEP_PX so clipped Sanskrit text has
        room to breathe — session-only, never written to config, and
        capped so repeated clicks can't run the card off-screen. If the
        meaning view happens to be open, re-run that sizing pass instead
        so the two never fight over the card's height."""
        if self._session_extra_height >= MAX_SESSION_EXTRA_HEIGHT:
            return
        self._session_extra_height = min(
            self._session_extra_height + EXPAND_STEP_PX, MAX_SESSION_EXTRA_HEIGHT
        )
        if self._meaning_open:
            self._expand_for_meaning()
        else:
            self._animate_resize(self._effective_base_height())

    def _shrink_text_area(self) -> None:
        """Mirror of _expand_text_area — undoes a previous session-only
        grow, one EXPAND_STEP_PX at a time, down to (but never below)
        the configured appearance/height."""
        if self._session_extra_height <= 0:
            return
        self._session_extra_height = max(self._session_extra_height - EXPAND_STEP_PX, 0)
        if self._meaning_open:
            self._expand_for_meaning()
        else:
            self._animate_resize(self._effective_base_height())

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
        y = int(self._button_row_top())

        # Right-docked group: close, then meaning to its left.
        right_x = self.width() - BUTTON_MARGIN - CLOSE_BUTTON_WIDTH
        self.close_btn.move(right_x, y)
        self.meaning_btn.move(right_x - BUTTON_SIZE - 6, y)

        # Left-docked group: down-arrow, then up-arrow to its right.
        left_x = BUTTON_MARGIN
        self.expand_btn.move(left_x, y)
        self.shrink_btn.move(left_x + BUTTON_SIZE + 6, y)

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
        button_row_top = self._button_row_top()

        content_left = card_rect.left() + CARD_PAD
        content_width = layout["text_width"]

        # --- Sanskrit verse, top-aligned ---
        sans_font = QFont(font_family, base_size)
        sans_font.setBold(True)
        painter.setFont(sans_font)
        painter.setPen(text_color)
        sans_top = card_rect.top() + CARD_PAD
        sans_rect = QRectF(content_left, sans_top, content_width,
                            max(button_row_top - sans_top, 0))
        painter.drawText(sans_rect, Qt.AlignLeft | Qt.TextWordWrap, self._shloka.sanskrit)

        # --- Reference tag, right above the (fixed) button row ---
        if self._shloka.reference:
            ref_font = QFont(font_family, max(base_size - 7, 7))
            painter.setFont(ref_font)
            painter.setPen(accent)
            ref_h = layout["ref_h"]
            painter.drawText(
                QRectF(content_left, button_row_top - ref_h - GAP_REF_TO_BUTTONS,
                       content_width, ref_h),
                Qt.AlignRight, self._shloka.reference,
            )

        # --- Translation, painted below the button row ---
        if self._meaning_open and self._shloka.translation:
            y = button_row_top + BUTTON_SIZE + GAP_BUTTONS_TO_TRANS
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

    # ------------------------------------------------------------------
    # Dragging + click-through (background only — clicks on the icon
    # buttons are consumed by those child widgets before reaching here)
    #
    # With behaviour/click_through enabled, EVERY mouse interaction with
    # the card's background — left/right/middle clicks and wheel scroll
    # alike — is meant to pass through to whatever's underneath, the one
    # exception being an actual left-button drag (which always moves the
    # card, click-through or not, so it stays movable). Right-click and
    # middle-click can't drag the window, so they're replayed unconditionally
    # on release; only the left button needs the press/move/release dance
    # to tell a click apart from a drag.
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if config.get("hotkeys/ctrl_click_hide") and (event.modifiers() & Qt.ControlModifier):
                self.dismiss()
                if config.get("hotkeys/ctrl_click_pause"):
                    self.pause_requested.emit()
                return

            self._press_global_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_global_pos - self.pos()
            self._is_dragging = False

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            current = event.globalPosition().toPoint()
            if not self._is_dragging:
                if (current - self._press_global_pos).manhattanLength() < DRAG_THRESHOLD_PX:
                    return  # still within click tolerance — not a drag yet
                self._is_dragging = True
            self.move(current - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self._is_dragging
            press_pos = self._press_global_pos
            self._drag_offset = None
            self._is_dragging = False
            self._press_global_pos = None

            if was_dragging:
                # A real drag always wins, click-through setting or not.
                self._save_position()
            elif config.get("behaviour/click_through") and press_pos is not None:
                self._replay_click_below(press_pos, event.button())
        elif event.button() in (Qt.RightButton, Qt.MiddleButton):
            # Neither button can drag the card, so there's no click-vs-drag
            # decision to make — just pass it straight through if enabled.
            if config.get("behaviour/click_through"):
                self._replay_click_below(event.globalPosition().toPoint(), event.button())

    def wheelEvent(self, event):
        # No more scroll-to-switch-shloka here (that used to fight with
        # click-through — see module docstring). With click-through on,
        # forward the scroll to whatever's underneath; with it off, the
        # scroll is simply swallowed, same as a click would be.
        if config.get("behaviour/click_through"):
            self._replay_wheel_below(event.globalPosition().toPoint(), event.angleDelta().y())

    _MOUSE_EVENT_FLAGS = {
        Qt.LeftButton: (0x0002, 0x0004),      # MOUSEEVENTF_LEFTDOWN / LEFTUP
        Qt.RightButton: (0x0008, 0x0010),     # MOUSEEVENTF_RIGHTDOWN / RIGHTUP
        Qt.MiddleButton: (0x0020, 0x0040),    # MOUSEEVENTF_MIDDLEDOWN / MIDDLEUP
    }
    MOUSEEVENTF_WHEEL = 0x0800

    def _replay_click_below(self, global_pos: QPoint, button=Qt.LeftButton) -> None:
        """A genuine click (no drag) with click-through enabled: pass
        it through to whatever's actually underneath the popup.

        We cannot rely on the OS to pass the click through automatically
        because the OS cannot predict the future — it doesn't know if a
        mouse-down is going to be a click or a drag until the mouse is
        released or moved. Thus we MUST intercept the event.
        
        Instead of the old `hide()` -> synthesize -> `show()` method
        (which caused a visual flicker), we briefly make the window
        transparent to input via the Windows API, synthesize the click
        so the OS passes it to the window beneath us, and then restore
        our window style."""
        if sys.platform != "win32":
            return
        if self._click_through_pending:
            return  # a previous replay hasn't finished yet — don't overlap
        self._click_through_pending = True
        QTimer.singleShot(0, lambda: self._do_replay_click(global_pos, button))

    def _do_replay_click(self, global_pos: QPoint, button) -> None:
        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        
        # 1. Temporarily make our window transparent to mouse events
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | WS_EX_TRANSPARENT)

        # 2. Synthesize the click (will fall through to the window below)
        user32.SetCursorPos(global_pos.x(), global_pos.y())
        down_flag, up_flag = self._MOUSE_EVENT_FLAGS.get(
            button, self._MOUSE_EVENT_FLAGS[Qt.LeftButton]
        )
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        
        # 3. Restore the window style shortly after. The delay ensures the OS 
        # processes the synthesized click while we are still transparent.
        QTimer.singleShot(50, lambda: self._restore_exstyle(hwnd, exstyle))

    def _replay_wheel_below(self, global_pos: QPoint, delta: int) -> None:
        """Same idea as _replay_click_below, but for a wheel notch."""
        if sys.platform != "win32" or delta == 0:
            return
        if self._click_through_pending:
            return
        self._click_through_pending = True
        QTimer.singleShot(0, lambda: self._do_replay_wheel(global_pos, delta))

    def _do_replay_wheel(self, global_pos: QPoint, delta: int) -> None:
        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | WS_EX_TRANSPARENT)

        user32.SetCursorPos(global_pos.x(), global_pos.y())
        user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        
        QTimer.singleShot(50, lambda: self._restore_exstyle(hwnd, exstyle))
        
    def _restore_exstyle(self, hwnd: int, original_exstyle: int) -> None:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, original_exstyle)
        self._click_through_pending = False
