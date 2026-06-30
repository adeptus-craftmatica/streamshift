from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    QPointF, QRectF, QSizeF, QTimer, QUrl, Qt, Signal,
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
        self._web_view = None   # off-screen QWebEngineView, if any
        self._web_timer: QTimer | None = None
        self._drag_origin: QPointF | None = None

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
        self._teardown_web_view()

        if self._source.source_type == "image":
            path = self._source.settings.get("file", "")
            if path:
                pm = QPixmap(path)
                if not pm.isNull():
                    self._pixmap = pm

        elif self._source.source_type == "browser":
            url = self._source.settings.get("url", "").strip()
            if url:
                self._start_web_preview(url)

    def _teardown_web_view(self) -> None:
        """Stop refresh timer and destroy the off-screen web view."""
        if self._web_timer is not None:
            self._web_timer.stop()
            self._web_timer = None
        if self._web_view is not None:
            self._web_view.deleteLater()
            self._web_view = None

    def _start_web_preview(self, url: str) -> None:
        """
        Render browser source off-screen and snapshot it to a pixmap.

        QWebEngineView cannot be embedded in QGraphicsScene (Chromium GPU
        compositor conflict). Instead we keep a hidden view, grab a QPixmap
        after the page loads, and refresh every 2 s so live overlays update.
        """
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            return

        w = max(int(self._source.width),  1)
        h = max(int(self._source.height), 1)

        view = QWebEngineView()
        # WA_DontShowOnScreen: Chromium renders off-screen without showing a window.
        # WA_QuitOnClose=False: prevents this hidden view from blocking app exit.
        view.setAttribute(Qt.WA_DontShowOnScreen, True)
        view.setAttribute(Qt.WA_QuitOnClose, False)
        view.resize(w, h)
        view.show()             # must call show() for the renderer to activate
        view.load(QUrl(url))
        self._web_view = view

        def _grab() -> None:
            if self._web_view is None:
                return
            pm = self._web_view.grab()
            if not pm.isNull():
                self._pixmap = pm
                self.update()

        view.loadFinished.connect(lambda ok: _grab())

        # Refresh every 2 s so live overlays (chat, now-playing…) stay current
        timer = QTimer()
        timer.setInterval(2000)
        timer.timeout.connect(_grab)
        timer.start()
        self._web_timer = timer

    # ── paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None) -> None:
        w, h = self._source.width, self._source.height
        rect = QRectF(0, 0, w, h)
        t = self._source.source_type
        info = SOURCE_TYPES.get(t, {})

        painter.setRenderHint(QPainter.Antialiasing, False)

        # Apply opacity (hidden sources show at 30% so they're still locatable)
        effective_opacity = self._source.opacity if self._source.visible else 0.3
        painter.setOpacity(effective_opacity)

        if t == "color":
            hex_col = self._source.settings.get("color_hex", "1a1a2e")
            try:
                color = QColor(f"#{hex_col}")
            except Exception:
                color = QColor("#1a1a2e")
            painter.fillRect(rect, QBrush(color))

        elif self._pixmap:
            # image sources and browser sources (grabbed from off-screen view)
            painter.drawPixmap(
                rect.toRect(),
                self._pixmap.scaled(int(w), int(h), Qt.KeepAspectRatio, Qt.SmoothTransformation),
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

        # Selection border — always fully opaque
        painter.setOpacity(1.0)
        if self.isSelected():
            pen = QPen(QColor("#7c3aed"), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        elif not self._source.visible:
            # "hidden" badge
            painter.setPen(QPen(QColor("#f59e0b"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    # ── interaction ───────────────────────────────────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            show = bool(value)
            for h in self._handles:
                h.setVisible(show)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            pos = self.pos()
            if view and isinstance(view, CanvasView) and view.snap_enabled:
                g = view.snap_grid
                snapped = QPointF(round(pos.x() / g) * g, round(pos.y() / g) * g)
                if snapped != pos:
                    # Block re-entrancy: setPos will fire itemChange again
                    self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
                    self.setPos(snapped)
                    self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
                    pos = snapped
            self._source.x = pos.x()
            self._source.y = pos.y()
            self._emit_transform()
        elif change == QGraphicsItem.ItemSceneChange and value is None:
            # Being removed from the scene — clean up the off-screen web view
            self._teardown_web_view()
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
        # Reposition existing handles in-place — rebuilding them would destroy
        # the handle currently being dragged and break the resize interaction.
        self._reposition_handles()
        self.update()
        self._emit_transform()

    def _reposition_handles(self) -> None:
        for handle, pt in zip(self._handles, self._handle_positions()):
            handle.setPos(pt.x() - _HANDLE_HALF, pt.y() - _HANDLE_HALF)

    def mousePressEvent(self, event) -> None:
        self._drag_origin = QPointF(self._source.x, self._source.y)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._drag_origin is not None:
            new_x, new_y = self._source.x, self._source.y
            old_x, old_y = self._drag_origin.x(), self._drag_origin.y()
            if (old_x, old_y) != (new_x, new_y):
                scene = self.scene()
                if scene and scene.views():
                    view = scene.views()[0]
                    if hasattr(view, "move_committed"):
                        view.move_committed.emit(self._source.source_id, old_x, old_y, new_x, new_y)
            self._drag_origin = None

    def contextMenuEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.views():
            view = scene.views()[0]
            if hasattr(view, "source_context_menu"):
                view.source_context_menu.emit(self._source, event.screenPos())
        event.accept()

    def thumbnail(self, size: int = 32) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        from PySide6.QtGui import QPainter
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        if self._pixmap and not self._pixmap.isNull():
            p.drawPixmap(0, 0, size, size, self._pixmap)
        else:
            from stream_controller.plugins.scene_designer.ui.canvas_widget import _type_color
            col = QColor(_type_color(self._source.source_type))
            p.fillRect(0, 0, size, size, QBrush(col))
            p.setPen(QPen(QColor("white"), 1))
            info = SOURCE_TYPES.get(self._source.source_type, {})
            f = QFont("Arial", size // 3)
            p.setFont(f)
            p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, info.get("icon", "?"))
        p.end()
        return pm


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
    source_selected    = Signal(object)                    # SourceConfig | None
    sources_reordered  = Signal()
    zoom_changed       = Signal(int)
    move_committed     = Signal(str, float, float, float, float)
    source_context_menu = Signal(object, object)           # SourceConfig, QPoint (global)

    def __init__(self, parent=None, interactive: bool = True) -> None:
        super().__init__(parent)
        self._interactive = interactive
        self._gscene = QGraphicsScene(0, 0, CANVAS_W, CANVAS_H, self)
        self.setScene(self._gscene)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.RubberBandDrag if interactive else QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setBackgroundBrush(QBrush(QColor("#0a0a0f")))
        self.setObjectName("CanvasView")
        if not interactive:
            self.setInteractive(False)

        # Background grid / canvas area
        self._canvas_bg = QGraphicsRectItem(0, 0, CANVAS_W, CANVAS_H)
        self._canvas_bg.setBrush(QBrush(QColor("#0d0d1a")))
        self._canvas_bg.setPen(QPen(QColor("#1e293b"), 2))
        self._canvas_bg.setZValue(-1)
        self._gscene.addItem(self._canvas_bg)

        self._items: dict[str, SourceItem] = {}  # source_id → SourceItem
        self.snap_enabled = True
        self.snap_grid    = 10          # pixels in scene (canvas) coordinates
        self._show_grid   = True
        self._zoom_pct    = 100

        self._gscene.selectionChanged.connect(self._on_selection_changed)

    # ── public API ────────────────────────────────────────────────────────────

    def load_scene(self, sources: list[SourceConfig]) -> None:
        """Replace all items with the given source list (bottom→top order)."""
        for item in list(self._items.values()):
            item._teardown_web_view()
            self._gscene.removeItem(item)
        self._items.clear()

        for z, source in enumerate(sources):
            self._add_item(source, z)

    def add_source(self, source: SourceConfig) -> None:
        z = len(self._items)
        self._add_item(source, z)

    def set_snap(self, enabled: bool, grid: int = 10) -> None:
        self.snap_enabled = enabled
        self.snap_grid    = max(1, grid)

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = show
        self._gscene.update()

    def set_bg_color(self, hex_color: str) -> None:
        try:
            color = QColor(hex_color)
        except Exception:
            return
        self._canvas_bg.setBrush(QBrush(color))
        self.setBackgroundBrush(QBrush(color.darker(150)))

    def selected_source_ids(self) -> list[str]:
        return [
            item.src.source_id
            for item in self._gscene.selectedItems()
            if isinstance(item, SourceItem)
        ]

    def fit_to_window(self) -> None:
        self._fit_canvas()

    def remove_source(self, source_id: str) -> None:
        item = self._items.pop(source_id, None)
        if item:
            item._teardown_web_view()   # stop timer + destroy hidden browser
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

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self._show_grid or not self.snap_enabled:
            return
        g = self.snap_grid
        painter.setPen(QPen(QColor("#1e2235"), 1, Qt.DotLine))
        left   = int(rect.left()   / g) * g
        top    = int(rect.top()    / g) * g
        right  = rect.right()
        bottom = rect.bottom()
        x = left
        while x <= right:
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, bottom))
            x += g
        y = top
        while y <= bottom:
            painter.drawLine(QPointF(rect.left(), y), QPointF(right, y))
            y += g

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            t = self.transform()
            pct = int(round(t.m11() * 100 / self._base_scale)) if hasattr(self, "_base_scale") else 100
            self.zoom_changed.emit(pct)
            event.accept()
        else:
            super().wheelEvent(event)

    def _fit_canvas(self) -> None:
        self.fitInView(QRectF(0, 0, CANVAS_W, CANVAS_H), Qt.KeepAspectRatio)
        self._base_scale = self.transform().m11()
        self.zoom_changed.emit(100)
