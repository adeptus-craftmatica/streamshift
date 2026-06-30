from __future__ import annotations

"""
A live mini-preview widget that renders a scaled-down version of the app
using the current theme colors. Updates instantly as colors change.
No real widgets — just QPainter drawing the mockup.
"""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from stream_controller.plugins.theme_manager.theme_models import AppTheme


class ThemePreview(QWidget):
    """Paints a miniature mockup of the app UI using theme colors."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme: AppTheme | None = None
        self.setMinimumSize(340, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(220)

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        if self._theme is None:
            return

        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # ── outer frame ──────────────────────────────────────────────────────
        _rounded_rect(p, QRectF(0, 0, w, h), t.bg_primary, t.border, radius=12)

        # ── sidebar ───────────────────────────────────────────────────────────
        sidebar_w = int(w * 0.2)
        _rounded_rect(p, QRectF(2, 2, sidebar_w, h - 4), t.bg_sidebar, "", radius=10)

        # Sidebar nav items
        item_h = 18
        for i, (label, active) in enumerate([("Dashboard", False), ("Scene Mgr", True),
                                              ("Music", False), ("Chat", False)]):
            y = 20 + i * (item_h + 4)
            if active:
                _rounded_rect(p, QRectF(6, y, sidebar_w - 10, item_h),
                              t.accent + "30", "", radius=5)
                p.fillRect(QRectF(6, y, 3, item_h), QColor(t.accent))
            color = QColor(t.accent_light if active else t.text_secondary)
            p.setPen(QPen(color))
            p.setFont(QFont("Arial", 7, QFont.Bold if active else QFont.Normal))
            p.drawText(QRect(12, int(y), sidebar_w, item_h), Qt.AlignVCenter, label)

        # ── content area ──────────────────────────────────────────────────────
        cx = sidebar_w + 4
        cw = w - cx - 2

        # Page title
        p.setPen(QPen(QColor(t.text_primary)))
        p.setFont(QFont("Arial", 9, QFont.Bold))
        p.drawText(QRect(cx + 8, 10, cw, 18), Qt.AlignVCenter, "Scene Manager")

        p.setFont(QFont("Arial", 6))
        p.setPen(QPen(QColor(t.text_secondary)))
        p.drawText(QRect(cx + 8, 24, cw, 12), Qt.AlignVCenter, "Connect OBS and manage your scenes")

        # Cards row
        card_y = 42
        card_h = int((h - card_y - 10) * 0.55)
        card_w = int(cw * 0.48)
        _rounded_rect(p, QRectF(cx + 6, card_y, card_w, card_h), t.bg_card, t.border, radius=8)
        _rounded_rect(p, QRectF(cx + cw - card_w - 6, card_y, card_w, card_h), t.bg_card, t.border, radius=8)

        # Card content (scene tiles)
        for ci, (name, live) in enumerate([("Gaming", True), ("BRB", False)]):
            bx = cx + 6 + ci * (cw - card_w)
            p.setPen(QPen(QColor(t.text_primary if live else t.text_secondary)))
            p.setFont(QFont("Arial", 7, QFont.Bold))
            p.drawText(QRect(int(bx) + 8, int(card_y) + 8, card_w, 14), Qt.AlignVCenter, name)
            if live:
                _rounded_rect(p, QRectF(bx + card_w - 32, card_y + 6, 26, 10),
                              t.accent, "", radius=3)
                p.setPen(QPen(QColor("#ffffff")))
                p.setFont(QFont("Arial", 5, QFont.Bold))
                p.drawText(QRect(int(bx + card_w - 32), int(card_y + 6), 26, 10), Qt.AlignCenter, "LIVE")

        # Primary button
        btn_y = int(card_y + card_h + 6)
        btn_h = 18
        btn_w = 80
        _rounded_rect(p, QRectF(cx + 6, btn_y, btn_w, btn_h), t.accent, "", radius=6)
        p.setPen(QPen(QColor(t.text_primary)))
        p.setFont(QFont("Arial", 6, QFont.Bold))
        p.drawText(QRect(int(cx + 6), btn_y, btn_w, btn_h), Qt.AlignCenter, "Connect to OBS")

        # Secondary button
        _rounded_rect(p, QRectF(cx + btn_w + 14, btn_y, 60, btn_h), t.bg_elevated, t.border, radius=6)
        p.setPen(QPen(QColor(t.text_secondary)))
        p.drawText(QRect(int(cx + btn_w + 14), btn_y, 60, btn_h), Qt.AlignCenter, "Disconnect")

        # Stage panel (bottom right)
        sp_y = btn_y
        sp_x = int(cx + cw * 0.55)
        sp_w = int(cw * 0.42)
        sp_h = int(h - sp_y - 4)
        _rounded_rect(p, QRectF(sp_x, sp_y, sp_w, sp_h), t.bg_card, t.border_strong, radius=8)
        # Panel title bar
        _rounded_rect(p, QRectF(sp_x, sp_y, sp_w, 16), t.accent_dark, "", radius=8)
        p.setClipRect(QRectF(sp_x, sp_y, sp_w, 16))
        _rounded_rect(p, QRectF(sp_x, sp_y + 8, sp_w, 8), t.accent_dark, "", radius=0)
        p.setClipping(False)
        p.setPen(QPen(QColor("#ffffff")))
        p.setFont(QFont("Arial", 5, QFont.Bold))
        p.drawText(QRect(sp_x + 6, sp_y, sp_w, 16), Qt.AlignVCenter, "Stage View")

        p.end()


def _rounded_rect(p: QPainter, rect: QRectF, fill: str, border: str, radius: float = 8) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    if fill:
        try:
            p.fillPath(path, QBrush(QColor(fill)))
        except Exception:
            pass
    if border:
        try:
            p.setPen(QPen(QColor(border), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        except Exception:
            pass
