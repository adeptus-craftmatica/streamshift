from __future__ import annotations
import copy
from typing import Callable, Any


class Command:
    description: str = "Action"
    def execute(self) -> None: ...
    def undo(self) -> None: ...


class UndoStack:
    """Bounded undo/redo stack. Push a Command to execute + record it."""

    def __init__(self, max_size: int = 100) -> None:
        self._stack: list[Command] = []
        self._pos = -1
        self._max = max_size
        self._on_change: Callable[[], None] | None = None

    def set_change_callback(self, cb: Callable[[], None]) -> None:
        self._on_change = cb

    def push(self, cmd: Command) -> None:
        # Discard any redo history above current position
        self._stack = self._stack[:self._pos + 1]
        self._stack.append(cmd)
        if len(self._stack) > self._max:
            self._stack.pop(0)
        self._pos = len(self._stack) - 1
        cmd.execute()
        if self._on_change:
            self._on_change()

    def undo(self) -> bool:
        if self._pos < 0:
            return False
        self._stack[self._pos].undo()
        self._pos -= 1
        if self._on_change:
            self._on_change()
        return True

    def redo(self) -> bool:
        if self._pos >= len(self._stack) - 1:
            return False
        self._pos += 1
        self._stack[self._pos].execute()
        if self._on_change:
            self._on_change()
        return True

    def can_undo(self) -> bool:
        return self._pos >= 0

    def can_redo(self) -> bool:
        return self._pos < len(self._stack) - 1

    def undo_text(self) -> str:
        return self._stack[self._pos].description if self._pos >= 0 else ""

    def redo_text(self) -> str:
        nxt = self._pos + 1
        return self._stack[nxt].description if nxt < len(self._stack) else ""

    def clear(self) -> None:
        self._stack.clear()
        self._pos = -1
        if self._on_change:
            self._on_change()


# ── Concrete commands ─────────────────────────────────────────────────────────

class _SceneCtx:
    """Minimal context passed to every command so they can mutate state."""
    def __init__(self, get_scene, save, canvas_add, canvas_remove,
                 canvas_update, refresh_layers, select_source, props_load):
        self.get_scene     = get_scene        # () -> DesignerScene | None
        self.save          = save             # (scene) -> None
        self.canvas_add    = canvas_add       # (source) -> None
        self.canvas_remove = canvas_remove    # (source_id) -> None
        self.canvas_update = canvas_update    # (source) -> None
        self.refresh_layers= refresh_layers   # () -> None
        self.select_source = select_source    # (source | None) -> None
        self.props_load    = props_load       # (source | None) -> None


class AddSourceCmd(Command):
    def __init__(self, source, ctx: _SceneCtx) -> None:
        self._source = source
        self._ctx    = ctx
        self.description = f"Add {source.name}"

    def execute(self) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        if not any(s.source_id == self._source.source_id for s in scene.sources):
            scene.sources.append(self._source)
        self._ctx.save(scene)
        self._ctx.canvas_add(self._source)
        self._ctx.refresh_layers()
        self._ctx.select_source(self._source)

    def undo(self) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        scene.sources = [s for s in scene.sources if s.source_id != self._source.source_id]
        self._ctx.save(scene)
        self._ctx.canvas_remove(self._source.source_id)
        self._ctx.refresh_layers()
        self._ctx.select_source(None)
        self._ctx.props_load(None)


class DeleteSourceCmd(Command):
    def __init__(self, source, ctx: _SceneCtx) -> None:
        self._source = copy.deepcopy(source)
        self._ctx    = ctx
        self.description = f"Delete {source.name}"

    def execute(self) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        scene.sources = [s for s in scene.sources if s.source_id != self._source.source_id]
        self._ctx.save(scene)
        self._ctx.canvas_remove(self._source.source_id)
        self._ctx.refresh_layers()
        self._ctx.select_source(None)
        self._ctx.props_load(None)

    def undo(self) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        scene.sources.append(self._source)
        self._ctx.save(scene)
        self._ctx.canvas_add(self._source)
        self._ctx.refresh_layers()
        self._ctx.select_source(self._source)


class PropertyChangeCmd(Command):
    """Generic before/after snapshot for any source property edit."""
    def __init__(self, before, after, ctx: _SceneCtx, desc: str = "Edit source") -> None:
        self._before = copy.deepcopy(before)
        self._after  = copy.deepcopy(after)
        self._ctx    = ctx
        self.description = desc

    def _apply(self, source) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        for i, s in enumerate(scene.sources):
            if s.source_id == source.source_id:
                scene.sources[i] = copy.deepcopy(source)
                break
        self._ctx.save(scene)
        self._ctx.canvas_update(source)
        self._ctx.refresh_layers()
        self._ctx.select_source(source)

    def execute(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)


class MoveSourceCmd(Command):
    def __init__(self, source_id: str, old_x: float, old_y: float,
                 new_x: float, new_y: float, ctx: _SceneCtx) -> None:
        self._sid = source_id
        self._old = (old_x, old_y)
        self._new = (new_x, new_y)
        self._ctx = ctx
        self.description = "Move source"

    def _apply(self, x: float, y: float) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        for s in scene.sources:
            if s.source_id == self._sid:
                s.x, s.y = x, y
                self._ctx.save(scene)
                self._ctx.canvas_update(s)
                return

    def execute(self) -> None:
        self._apply(*self._new)

    def undo(self) -> None:
        self._apply(*self._old)


class ReorderCmd(Command):
    def __init__(self, old_ids: list, new_ids: list, ctx: _SceneCtx) -> None:
        self._old = list(old_ids)
        self._new = list(new_ids)
        self._ctx = ctx
        self.description = "Reorder layers"

    def _apply(self, id_order: list) -> None:
        scene = self._ctx.get_scene()
        if scene is None:
            return
        id_map = {s.source_id: s for s in scene.sources}
        scene.sources = [id_map[i] for i in id_order if i in id_map]
        self._ctx.save(scene)
        self._ctx.refresh_layers()

    def execute(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)
