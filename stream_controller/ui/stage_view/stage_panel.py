from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

_TITLE_H     = 32
_ACCENT_H    = 4    # always-visible colored stripe above title bar
_EDGE_GRIP   = 10
_CORNER_GRIP = 18
_MIN_W       = 240
_MIN_H       = 200
_SNAP        = 8

_N  = 1; _S  = 2; _W  = 4; _E  = 8
_NW = _N | _W; _NE = _N | _E
_SW = _S | _W; _SE = _S | _E


def _snap(v: int) -> int:
    return round(v / _SNAP) * _SNAP


# ── Resize grip ───────────────────────────────────────────────────────────────

class _Grip(QWidget):
    def __init__(self, canvas: QWidget, panel: "StagePanel", direction: int) -> None:
        super().__init__(canvas)
        self._panel     = panel
        self._direction = direction
        self._drag_start: QPoint | None = None
        self._orig_geo:   QRect  | None = None
        self._zoom: float = 1.0

        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

        cursors = {
            _N: Qt.SizeVerCursor,  _S: Qt.SizeVerCursor,
            _W: Qt.SizeHorCursor,  _E: Qt.SizeHorCursor,
            _NW: Qt.SizeFDiagCursor, _SE: Qt.SizeFDiagCursor,
            _NE: Qt.SizeBDiagCursor, _SW: Qt.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(direction, Qt.ArrowCursor))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            g = self._panel.geometry()
            # Snap all 4 edges to the grid at press time so there is no
            # initial jump when the panel isn't already grid-aligned.
            # Use exclusive right/bottom (left+width, top+height) to avoid
            # Qt's QRect right = left+width-1 off-by-one.
            left   = _snap(g.left())
            top    = _snap(g.top())
            right  = _snap(g.left() + g.width())
            bottom = _snap(g.top()  + g.height())
            self._orig_geo = QRect(left, top, right - left, bottom - top)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None:
            event.ignore()
            return
        raw = event.globalPosition().toPoint() - self._drag_start
        zoom = self._zoom if self._zoom > 0 else 1.0
        dx = raw.x() / zoom
        dy = raw.y() / zoom
        d = self._direction

        # Work in exclusive edge coordinates to keep snap math clean.
        left   = self._orig_geo.left()
        top    = self._orig_geo.top()
        right  = self._orig_geo.left() + self._orig_geo.width()
        bottom = self._orig_geo.top()  + self._orig_geo.height()

        if d & _E:  right  = _snap(right  + dx)
        if d & _W:  left   = _snap(left   + dx)
        if d & _S:  bottom = _snap(bottom + dy)
        if d & _N:  top    = _snap(top    + dy)

        if right  - left   < _MIN_W:
            if d & _W: left   = right  - _MIN_W
            else:      right  = left   + _MIN_W
        if bottom - top    < _MIN_H:
            if d & _N: top    = bottom - _MIN_H
            else:      bottom = top    + _MIN_H

        self._panel.setGeometry(left, top, right - left, bottom - top)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_start is not None:
            self._drag_start = None
            self._orig_geo   = None
            self._panel.geometry_changed.emit()
        event.accept()


# ── Title-bar drag handle ─────────────────────────────────────────────────────

class _TitleBar(QFrame):
    def __init__(self, panel: "StagePanel", title: str) -> None:
        super().__init__(panel)
        self._panel      = panel
        self._drag_start: QPoint | None = None
        self._orig_pos:   QPoint | None = None
        self._zoom: float = 1.0

        self.setObjectName("StagePanelTitleBar")
        self.setFixedHeight(_TITLE_H)
        self.setCursor(Qt.SizeAllCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        drag_icon = QLabel("⠿")
        drag_icon.setObjectName("StagePanelDragIcon")

        # Icon: shows either an emoji label or a scaled image pixmap
        self._icon_emoji = QLabel("")
        self._icon_emoji.setStyleSheet("font-size:14px;")
        self._icon_emoji.setVisible(False)

        self._icon_img = QLabel()
        self._icon_img.setFixedSize(20, 20)
        self._icon_img.setScaledContents(True)
        self._icon_img.setVisible(False)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("StagePanelTitle")

        self._customize_btn = QPushButton("🎨")
        self._customize_btn.setObjectName("StagePanelCloseBtn")
        self._customize_btn.setFixedSize(22, 22)
        self._customize_btn.setToolTip("Customize theme, color, and icon")
        self._customize_btn.clicked.connect(
            lambda: panel.customize_requested.emit(panel.panel_id)
        )

        close_btn = QPushButton("✕")
        close_btn.setObjectName("StagePanelCloseBtn")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(lambda: panel.close_requested.emit(panel.panel_id))

        layout.addWidget(drag_icon)
        layout.addWidget(self._icon_img)
        layout.addWidget(self._icon_emoji)
        layout.addWidget(self._title_lbl, 1)
        layout.addWidget(self._customize_btn)
        layout.addWidget(close_btn)

    def update_icon(self, icon_text: str, icon_path: str) -> None:
        if icon_path and Path(icon_path).exists():
            px = QPixmap(icon_path)
            if not px.isNull():
                self._icon_img.setPixmap(px)
                self._icon_img.setVisible(True)
                self._icon_emoji.setVisible(False)
                return
        self._icon_img.setVisible(False)
        self._icon_emoji.setText(icon_text)
        self._icon_emoji.setVisible(bool(icon_text))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            p = self._panel.pos()
            # Snap origin at press so dragging never has an initial jump.
            self._orig_pos = QPoint(_snap(p.x()), _snap(p.y()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None:
            return
        raw = event.globalPosition().toPoint() - self._drag_start
        zoom = self._zoom if self._zoom > 0 else 1.0
        new_x = _snap(self._orig_pos.x() + raw.x() / zoom)
        new_y = _snap(max(0, self._orig_pos.y() + raw.y() / zoom))
        self._panel.move(new_x, new_y)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_start is not None:
            self._drag_start = None
            self._orig_pos   = None
            self._panel.geometry_changed.emit()
        event.accept()


# ── StagePanel ────────────────────────────────────────────────────────────────

class StagePanel(QFrame):
    """
    Freely positionable, resizable panel for the Stage View canvas.
    Edit mode: title bar for dragging + 8 edge/corner resize grips.
    View mode: thin accent stripe at top only. All colors driven by the
    theme engine via setStyleSheet() on the panel widget.
    """

    close_requested     = Signal(str)
    geometry_changed    = Signal()
    customize_requested = Signal(str)

    def __init__(self, panel_id: str, title: str, content: QWidget,
                 icon_text: str = "", icon_path: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel_id   = panel_id
        self._icon_text = icon_text
        self._icon_path = icon_path
        self._edit_mode = True
        self._grips: list[_Grip] = []

        self.setObjectName("StagePanel")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMinimumSize(_MIN_W, _MIN_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Thin accent stripe — always visible; color set by theme engine QSS
        self._accent = QFrame()
        self._accent.setObjectName("StagePanelAccent")
        self._accent.setFixedHeight(_ACCENT_H)
        root.addWidget(self._accent)

        self._title_bar = _TitleBar(self, title)
        self._title_bar.update_icon(icon_text, icon_path)
        root.addWidget(self._title_bar)

        # Scroll area so content is always reachable regardless of panel size
        self._scroll = QScrollArea()
        self._scroll.setObjectName("StagePanelScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setWidget(content)
        root.addWidget(self._scroll, 1)

    # ── public ────────────────────────────────────────────────────────────────

    def set_zoom(self, zoom: float) -> None:
        self._title_bar._zoom = zoom
        for g in self._grips:
            g._zoom = zoom

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self._title_bar.setVisible(enabled)
        for g in self._grips:
            g.setVisible(enabled)
        self.setObjectName("StagePanel" if enabled else "StagePanelView")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_icon(self, icon_text: str, icon_path: str) -> None:
        self._icon_text = icon_text
        self._icon_path = icon_path
        self._title_bar.update_icon(icon_text, icon_path)

    def serialise(self) -> dict:
        r = self.geometry()
        return {
            "id":        self.panel_id,
            "x": r.x(), "y": r.y(), "w": r.width(), "h": r.height(),
            "icon_text": self._icon_text,
            "icon_path": self._icon_path,
        }

    def raise_to_top(self) -> None:
        """Raise the panel, then re-raise all grips so they stay above it."""
        self.raise_()
        for g in self._grips:
            g.raise_()

    def destroy_grips(self) -> None:
        for g in self._grips:
            g.setParent(None)
            g.deleteLater()
        self._grips.clear()

    # ── Qt overrides ──────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._grips and self.parentWidget():
            self._create_grips()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_grips()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._position_grips()

    # ── grip management ───────────────────────────────────────────────────────

    def _create_grips(self) -> None:
        canvas = self.parentWidget()
        for d in [_N, _S, _W, _E, _NW, _NE, _SW, _SE]:
            g = _Grip(canvas, self, d)
            g.setVisible(self._edit_mode)
            self._grips.append(g)
        self._position_grips()

    def _position_grips(self) -> None:
        if not self._grips:
            return
        x, y = self.x(), self.y()
        w, h = self.width(), self.height()
        e, c = _EDGE_GRIP, _CORNER_GRIP

        geo = {
            _N:  QRect(x + c,     y,           w - 2*c, e),
            _S:  QRect(x + c,     y + h - e,   w - 2*c, e),
            _W:  QRect(x,         y + c,        e,       h - 2*c),
            _E:  QRect(x + w - e, y + c,        e,       h - 2*c),
            _NW: QRect(x,         y,            c,       c),
            _NE: QRect(x + w - c, y,            c,       c),
            _SW: QRect(x,         y + h - c,    c,       c),
            _SE: QRect(x + w - c, y + h - c,    c,       c),
        }
        for grip in self._grips:
            grip.setGeometry(geo[grip._direction])
            grip.raise_()
