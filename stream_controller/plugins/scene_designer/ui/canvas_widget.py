from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    QPointF, QRectF, QSizeF, Qt, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen, QPixmap, QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView, QSizePolicy,
)

from stream_controller.plugins.scene_designer.designer_models import (
    CANVAS_H, CANVAS_W, SOURCE_TYPES, SourceConfig,
)

_HANDLE_SIZE = 10
_HANDLE_HALF = _HANDLE_SIZE / 2

# Handle positions (indices)
_TL, _TC, _TR = 0, 1, 2
_ML, _MR      = 3, 4
_BL, _BC, _BR = 5, 6, 7


class SourceItem(QGraphicsObject):
    """
    One source displayed on the canvas.
    Supports move (drag body), resize (8 corner/edge handles), and rotation.
    """
    transform_changed = Signal(str, float, float, float, float, float)  # id,x,y,w,h,rot

    def __init__(self, source: SourceConfig) -> None:
        super().__init__()
        self._source = source
        self._handles: list[_Handle] = []
        self._pixmap: QPixmap | None = None

        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(source.x, source.y)
        if source.rotation:
            self.setRotation(source.rotation)

        self._build_handles()
        self._load_preview()

    # ── geometry ──────────────────────────────────────────────────────────────

    @property
    def src(self) -> SourceConfig:
        return self._source

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._source.width, self._source.height)

    def _handle_positions(self) -> list[QPointF]:
        w, h = self._source.width, self._source.height
        return [
            QPointF(0, 0),       QPointF(w / 2, 0),       QPointF(w, 0),
            QPointF(0, h / 2),                              QPointF(w, h / 2),
            QPointF(0, h),       QPointF(w / 2, h),        QPointF(w, h),
        ]

    def _build_handles(self) -> None:
        for h in self._handles:
            h.setParentItem(None)
        self._handles.clear()
        for i, pt in enumerate(self._handle_positions()):
            h = _Handle(i, self)
            h.setPos(pt.x() - _HANDLE_HALF, pt.y() - _HANDLE_HALF)
            h.setVisible(False)
            self._handles.append(h)

    def update_from_source(self, source: SourceConfig) -> None:
        self._source = source
        self.setPos(source.x, source.y)
        self.setRotation(source.rotation)
        self.setVisible(source.visible)
        self.prepareGeometryChange()
        self._load_preview()
        self._build_handles()
        self.update()

    # ── preview rendering ─────────────────────────────────────────────────────

    def _load_preview(self) -> None:
        self._pixmap = None
        if self._source.source_type == "image":
            path = self._source.settings.get("file", "")
            if path:
                pm = QPixmap(path)
                if not pm.isNull():
                    self._pixmap = pm

    # ── paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None) -> None:
        w, h = self._source.width, self._source.height
        rect = QRectF(0, 0, w, h)
        t = self._source.source_type
        info = SOURCE_TYPES.get(t, {})

        painter.setRenderHint(QPainter.Antialiasing, False)

        if t == "color":
            hex_col = self._source.settings.get("color_hex", "1a1a2e")
            try:
                color = QColor(f"#{hex_col}")
            except Exception:
                color = QColor("#1a1a2e")
            painter.fillRect(rect, QBrush(color))

        elif t == "image" and self._pixmap:
            painter.drawPixmap(
                rect.toRect(),
                self._pixmap.scaled(int(w), int(h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation),
            )

        elif t == "text":
            # Faint background + text preview
            painter.fillRect(rect, QBrush(QColor(30, 30, 46, 80)))
            hex_col = self._source.settings.get("color_hex", "ffffff")
            try:
                text_color = QColor(f"#{hex_col}")
            except Exception:
                text_color = QColor("#ffffff")
            font_size = self._source.settings.get("font", {}).get("size", 48)
            f = QFont("Arial", max(8, min(int(font_size * 0.05), 72)))
            painter.setFont(f)
            painter.setPen(QPen(text_color))
            text = self._source.settings.get("text", "Text")
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, text)

        else:
            # Generic placeholder
            painter.fillRect(rect, QBrush(QColor(20, 20, 35, 200)))
            icon_color = _type_color(t)
            painter.setPen(QPen(QColor(icon_color), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

            # Icon
            icon = info.get("icon", "?")
            label = info.get("label", t)
            f = QFont("Arial", max(8, int(min(w, h) * 0.08)))
            painter.setFont(f)
            painter.setPen(QPen(QColor(icon_color)))
            painter.drawText(
                rect.adjusted(0, 0, 0, -rect.height() * 0.2),
                Qt.AlignCenter,
                icon,
            )
            f2 = QFont("Arial", max(7, int(min(w, h) * 0.05)))
            painter.setFont(f2)
            painter.setPen(QPen(QColor(180, 180, 200)))
            painter.drawText(
                rect.adjusted(0, rect.height() * 0.55, 0, 0),
                Qt.AlignCenter,
                f"{label}\n{self._source.name}",
            )

        # Selection border
        if self.isSelected():
            pen = QPen(QColor("#7c3aed"), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    # ── interaction ───────────────────────────────────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            show = bool(value)
            for h in self._handles:
                h.setVisible(show)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self._source.x = self.pos().x()
            self._source.y = self.pos().y()
            self._emit_transform()
        return super().itemChange(change, value)

    def _emit_transform(self) -> None:
        self.transform_changed.emit(
            self._source.source_id,
            self._source.x, self._source.y,
            self._source.width, self._source.height,
            self._source.rotation,
        )

    def apply_resize(self, handle_idx: int, delta: QPointF) -> None:
        """Called by _Handle when the user drags a resize handle."""
        if self._source.locked:
            return
        x, y = self._source.x, self._source.y
        w, h = self._source.width, self._source.height
        dx, dy = delta.x(), delta.y()

        if handle_idx in (_TL, _ML, _BL):  # left edge
            x += dx; w -= dx
        if handle_idx in (_TR, _MR, _BR):  # right edge
            w += dx
        if handle_idx in (_TL, _TC, _TR):  # top edge
            y += dy; h -= dy
        if handle_idx in (_BL, _BC, _BR):  # bottom edge
            h += dy

        w = max(10, w)
        h = max(10, h)
        self._source.x, self._source.y = x, y
        self._source.width, self._source.height = w, h
        self.setPos(x, y)
        self.prepareGeometryChange()
        self._build_handles()
        self.update()
        self._emit_transform()


# ── resize handle ──────────────────────────────────────────────────────────────

class _Handle(QGraphicsRectItem):
    def __init__(self, idx: int, parent: SourceItem) -> None:
        super().__init__(0, 0, _HANDLE_SIZE, _HANDLE_SIZE, parent)
        self._idx = idx
        self._parent_item = parent
        self._drag_start: QPointF | None = None
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIgnoresParentOpacity, True)
        self.setAcceptHoverEvents(True)
        self.setBrush(QBrush(QColor("#7c3aed")))
        self.setPen(QPen(QColor("#ffffff"), 1))
        self.setCursor(_cursor_for(idx))

    def mousePressEvent(self, event) -> None:
        self._drag_start = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None:
            return
        delta = event.scenePos() - self._drag_start
        self._drag_start = event.scenePos()
        self._parent_item.apply_resize(self._idx, delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start = None
        event.accept()


def _cursor_for(idx: int) -> Qt.CursorShape:
    return {
        _TL: Qt.SizeFDiagCursor, _TC: Qt.SizeVerCursor,  _TR: Qt.SizeBDiagCursor,
        _ML: Qt.SizeHorCursor,                             _MR: Qt.SizeHorCursor,
        _BL: Qt.SizeBDiagCursor, _BC: Qt.SizeVerCursor,  _BR: Qt.SizeFDiagCursor,
    }.get(idx, Qt.SizeAllCursor)


def _type_color(source_type: str) -> str:
    return {
        "image":          "#22c55e",
        "browser":        "#3b82f6",
        "text":           "#f59e0b",
        "color":          "#8b5cf6",
        "media":          "#ec4899",
        "audio_input":    "#06b6d4",
        "window_capture": "#f97316",
        "display_capture":"#84cc16",
        "chat_overlay":   "#a78bfa",
    }.get(source_type, "#6b7280")


# ── canvas view ────────────────────────────────────────────────────────────────

class CanvasView(QGraphicsView):
    """
    1920×1080 virtual canvas scaled to fill the widget.
    Emits `source_selected` when the selection changes.
    """
    source_selected = Signal(object)   # SourceConfig | None
    sources_reordered = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gscene = QGraphicsScene(0, 0, CANVAS_W, CANVAS_H, self)
        self.setScene(self._gscene)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setBackgroundBrush(QBrush(QColor("#0a0a0f")))
        self.setObjectName("CanvasView")

        # Background grid / canvas area
        self._canvas_bg = QGraphicsRectItem(0, 0, CANVAS_W, CANVAS_H)
        self._canvas_bg.setBrush(QBrush(QColor("#0d0d1a")))
        self._canvas_bg.setPen(QPen(QColor("#1e293b"), 2))
        self._canvas_bg.setZValue(-1)
        self._gscene.addItem(self._canvas_bg)

        self._items: dict[str, SourceItem] = {}  # source_id → SourceItem

        self._gscene.selectionChanged.connect(self._on_selection_changed)

    # ── public API ────────────────────────────────────────────────────────────

    def load_scene(self, sources: list[SourceConfig]) -> None:
        """Replace all items with the given source list (bottom→top order)."""
        # Remove existing source items (keep background)
        for item in list(self._items.values()):
            self._gscene.removeItem(item)
        self._items.clear()

        for z, source in enumerate(sources):
            self._add_item(source, z)

    def add_source(self, source: SourceConfig) -> None:
        z = len(self._items)
        self._add_item(source, z)

    def remove_source(self, source_id: str) -> None:
        item = self._items.pop(source_id, None)
        if item:
            self._gscene.removeItem(item)

    def update_source(self, source: SourceConfig) -> None:
        item = self._items.get(source.source_id)
        if item:
            item.update_from_source(source)

    def set_z_order(self, ordered_ids: list[str]) -> None:
        for z, sid in enumerate(ordered_ids):
            item = self._items.get(sid)
            if item:
                item.setZValue(z)

    def selected_source_id(self) -> str | None:
        sel = self._gscene.selectedItems()
        for item in sel:
            if isinstance(item, SourceItem):
                return item.src.source_id
        return None

    def clear_selection(self) -> None:
        self._gscene.clearSelection()

    # ── internal ──────────────────────────────────────────────────────────────

    def _add_item(self, source: SourceConfig, z: int) -> None:
        item = SourceItem(source)
        item.setZValue(z)
        item.setVisible(source.visible)
        item.transform_changed.connect(self._on_item_transform_changed)
        self._gscene.addItem(item)
        self._items[source.source_id] = item

    def _on_selection_changed(self) -> None:
        sel = self._gscene.selectedItems()
        src = None
        for item in sel:
            if isinstance(item, SourceItem):
                src = item.src
                break
        self.source_selected.emit(src)

    def _on_item_transform_changed(self, source_id: str, x: float, y: float, w: float, h: float, rot: float) -> None:
        pass  # Model already updated inside SourceItem; page picks up on next emit

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_canvas()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_canvas()

    def _fit_canvas(self) -> None:
        self.fitInView(QRectF(0, 0, CANVAS_W, CANVAS_H), Qt.KeepAspectRatio)
