from __future__ import annotations

import copy
import threading
import uuid as _uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QSize, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider,
    QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
    QColorDialog, QScrollArea, QApplication,
)

from stream_controller.plugins.scene_designer.designer_models import (
    CANVAS_W, CANVAS_H, SOURCE_TYPES, TRANSITION_TYPES,
    DesignerScene, SourceConfig,
)
from stream_controller.plugins.scene_designer.designer_repository import DesignerRepository
from stream_controller.plugins.scene_designer.obs_import import import_scene as obs_import_scene, fetch_obs_scenes
from stream_controller.plugins.scene_designer.obs_sync import ObsSyncError, connect_obs, sync_scene
from stream_controller.plugins.scene_designer.ui.canvas_widget import CanvasView
from stream_controller.plugins.scene_designer.ui.source_properties import SourcePropertiesPanel
from stream_controller.plugins.scene_designer.undo_stack import (
    UndoStack, _SceneCtx, AddSourceCmd, DeleteSourceCmd,
    PropertyChangeCmd, MoveSourceCmd, ReorderCmd,
)


class _SyncSignals(QObject):
    done     = Signal(str)
    progress = Signal(str)


class _ImportSignals(QObject):
    scenes_fetched = Signal(list)
    fetch_error    = Signal(str)
    scene_imported = Signal(object)
    import_error   = Signal(str)
    progress       = Signal(str)


# ══════════════════════════════════════════════════════════════════════════════

class SceneEditorWindow(QDialog):
    """Full-screen scene editor opened from the scene browser."""

    scene_saved = Signal(str)   # emits scene_id when saved

    def __init__(
        self,
        scene: DesignerScene,
        repo: DesignerRepository,
        obs_settings_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Editing: {scene.name}")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.resize(1400, 900)

        self._scene             = copy.deepcopy(scene)
        self._repo              = repo
        self._obs_settings_path = obs_settings_path
        self._selected_source: SourceConfig | None = None
        self._clipboard: SourceConfig | None = None

        self._undo      = UndoStack()
        self._undo_btn: QPushButton | None = None
        self._redo_btn: QPushButton | None = None

        self._sync_sigs   = _SyncSignals()
        self._import_sigs = _ImportSignals()
        self._sync_sigs.done.connect(self._on_sync_done)
        self._sync_sigs.progress.connect(self._on_sync_progress)
        self._import_sigs.scene_imported.connect(self._on_scene_imported)
        self._import_sigs.import_error.connect(self._on_import_error)
        self._import_pending = 0
        self._import_dialog: QDialog | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar: scene name + window actions ───────────────────────────
        root.addWidget(self._build_header())

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        root.addWidget(sep)

        # ── Body: tools sidebar | canvas | layers+properties ─────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_tools_sidebar())

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine); sep2.setObjectName("Separator")
        body.addWidget(sep2)

        body.addWidget(self._build_canvas_panel(), 1)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.VLine); sep3.setObjectName("Separator")
        body.addWidget(sep3)

        body.addWidget(self._build_right_sidebar())

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, 1)

        # Load scene onto canvas
        self._canvas.load_scene(self._scene.sources)
        bg = getattr(self._scene, "bg_color", "#0d0d1a")
        self._canvas.set_bg_color(bg)
        self._refresh_layer_list()
        self._load_transition_settings()

        self._setup_shortcuts()

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("DesignerToolbar")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(10)

        scene_lbl = QLabel(self._scene.name)
        scene_lbl.setObjectName("CardTitle")
        hl.addWidget(scene_lbl)

        hl.addStretch(1)

        import_btn = QPushButton("Import from OBS")
        import_btn.setObjectName("SecondaryButton")
        import_btn.setToolTip("Import scenes from OBS via WebSocket")
        import_btn.clicked.connect(self._import_from_obs)
        hl.addWidget(import_btn)

        self._sync_btn = QPushButton("Sync to OBS")
        self._sync_btn.setObjectName("SecondaryButton")
        self._sync_btn.setToolTip("Push this scene to OBS")
        self._sync_btn.clicked.connect(self._sync_to_obs)
        hl.addWidget(self._sync_btn)

        self._sync_bar = QLabel("")
        self._sync_bar.setObjectName("CardDescription")
        self._sync_bar.setVisible(False)
        hl.addWidget(self._sync_bar)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setObjectName("Separator")
        hl.addWidget(sep)

        done_btn = QPushButton("Done")
        done_btn.setObjectName("PrimaryButton")
        done_btn.setToolTip("Save and close  [Ctrl+W]")
        done_btn.clicked.connect(self._save_and_close)
        hl.addWidget(done_btn)

        return bar

    # ══════════════════════════════════════════════════════════════════════════
    # LEFT TOOLS SIDEBAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tools_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SidebarPanel")
        sidebar.setFixedWidth(240)

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        vl = QVBoxLayout(content)
        vl.setContentsMargins(10, 12, 10, 12)
        vl.setSpacing(4)

        def _section(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("MusicFieldLabel")
            lbl.setContentsMargins(0, 8, 0, 4)
            return lbl

        def _btn(label: str, tip: str, fn, obj: str = "SecondaryButton") -> QPushButton:
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setToolTip(tip)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(fn)
            return b

        def _hsep() -> QFrame:
            f = QFrame(); f.setFrameShape(QFrame.HLine); f.setObjectName("Separator")
            f.setContentsMargins(0, 6, 0, 6)
            return f

        def _row2(b1: QPushButton, b2: QPushButton) -> QWidget:
            w = QWidget(); hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(4)
            hl.addWidget(b1); hl.addWidget(b2)
            return w

        # ── Sources ────────────────────────────────────────────────────────────
        vl.addWidget(_section("Sources"))

        add_btn = QPushButton("+ Add Source")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setToolTip("Add a new source to this scene")
        add_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        add_btn.clicked.connect(self._show_add_source_menu)
        vl.addWidget(add_btn)

        vl.addWidget(_row2(
            _btn("Delete",    "Delete selected source  [Del]",       self._delete_selected_source),
            _btn("Duplicate", "Duplicate selected source  [Ctrl+D]", self._duplicate_source),
        ))
        vl.addWidget(_row2(
            _btn("Copy",  "Copy source  [Ctrl+C]",  self._copy_source),
            _btn("Paste", "Paste source  [Ctrl+V]", self._paste_source),
        ))

        vl.addWidget(_hsep())

        # ── History ────────────────────────────────────────────────────────────
        vl.addWidget(_section("History"))

        self._undo_btn = _btn("Undo", "Undo last action  [Ctrl+Z]", self._do_undo)
        self._undo_btn.setEnabled(False)
        self._redo_btn = _btn("Redo", "Redo  [Ctrl+Y]", self._do_redo)
        self._redo_btn.setEnabled(False)
        vl.addWidget(_row2(self._undo_btn, self._redo_btn))

        vl.addWidget(_hsep())

        # ── View ───────────────────────────────────────────────────────────────
        vl.addWidget(_section("View"))

        self._snap_btn = QPushButton("Snap: On")
        self._snap_btn.setObjectName("SecondaryButton")
        self._snap_btn.setToolTip("Toggle snap-to-grid when dragging sources")
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._snap_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._snap_btn.toggled.connect(self._on_snap_toggled)
        vl.addWidget(self._snap_btn)

        self._grid_btn = QPushButton("Grid: On")
        self._grid_btn.setObjectName("SecondaryButton")
        self._grid_btn.setToolTip("Show/hide grid lines on canvas")
        self._grid_btn.setCheckable(True)
        self._grid_btn.setChecked(True)
        self._grid_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._grid_btn.toggled.connect(self._on_grid_toggled)
        vl.addWidget(self._grid_btn)

        zoom_row = QWidget()
        zl = QHBoxLayout(zoom_row); zl.setContentsMargins(0, 0, 0, 0); zl.setSpacing(4)
        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setObjectName("CardDescription")
        self._zoom_lbl.setFixedWidth(42)
        zl.addWidget(self._zoom_lbl)
        fit_btn = QPushButton("Fit View")
        fit_btn.setObjectName("SecondaryButton")
        fit_btn.setToolTip("Fit canvas to window")
        fit_btn.clicked.connect(lambda: self._canvas.fit_to_window())
        zl.addWidget(fit_btn, 1)
        vl.addWidget(zoom_row)

        vl.addWidget(_btn("BG Color", "Change canvas background color", self._pick_bg_color))

        vl.addWidget(_hsep())

        # ── Align ──────────────────────────────────────────────────────────────
        vl.addWidget(_section("Align (2+ selected)"))

        vl.addWidget(_row2(
            _btn("Left",     "Align left edges",       lambda: self._align_sources("left")),
            _btn("Right",    "Align right edges",      lambda: self._align_sources("right")),
        ))
        vl.addWidget(_row2(
            _btn("Top",      "Align top edges",        lambda: self._align_sources("top")),
            _btn("Bottom",   "Align bottom edges",     lambda: self._align_sources("bottom")),
        ))
        vl.addWidget(_row2(
            _btn("Center H", "Align horizontal centers", lambda: self._align_sources("center_h")),
            _btn("Middle V", "Align vertical centers",   lambda: self._align_sources("center_v")),
        ))
        vl.addWidget(_row2(
            _btn("Dist H", "Distribute evenly left-to-right", lambda: self._distribute_sources("h")),
            _btn("Dist V", "Distribute evenly top-to-bottom", lambda: self._distribute_sources("v")),
        ))
        vl.addWidget(_row2(
            _btn("Ctr H", "Center on canvas horizontally", lambda: self._center_on_canvas("h")),
            _btn("Ctr V", "Center on canvas vertically",   lambda: self._center_on_canvas("v")),
        ))

        vl.addWidget(_hsep())

        # ── Layer Order ────────────────────────────────────────────────────────
        vl.addWidget(_section("Layer Order"))

        vl.addWidget(_row2(
            _btn("Move Up",   "Move layer up in stack",   self._source_up),
            _btn("Move Down", "Move layer down in stack", self._source_down),
        ))
        vl.addWidget(_row2(
            _btn("To Front", "Bring to front", self._source_to_front),
            _btn("To Back",  "Send to back",   self._source_to_back),
        ))

        vl.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return sidebar

    # ══════════════════════════════════════════════════════════════════════════
    # CANVAS PANEL
    # ══════════════════════════════════════════════════════════════════════════

    def _build_canvas_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self._canvas = CanvasView()
        self._canvas.source_selected.connect(self._on_canvas_selection)
        self._canvas.move_committed.connect(self._on_move_committed)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.source_context_menu.connect(self._on_source_context_menu)
        vl.addWidget(self._canvas, 1)

        return panel

    # ══════════════════════════════════════════════════════════════════════════
    # RIGHT SIDEBAR: layers + properties
    # ══════════════════════════════════════════════════════════════════════════

    def _build_right_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SidebarPanel")
        sidebar.setFixedWidth(360)
        vl = QVBoxLayout(sidebar)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Layers ─────────────────────────────────────────────────────────────
        layers_hdr = QWidget(); layers_hdr.setObjectName("SidebarHeader")
        lh = QHBoxLayout(layers_hdr); lh.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel("Layers"); lbl.setObjectName("CardTitle")
        lh.addWidget(lbl, 1)
        hint = QLabel("Drag to reorder"); hint.setObjectName("CardDescription")
        lh.addWidget(hint)
        vl.addWidget(layers_hdr)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setObjectName("Separator")
        vl.addWidget(sep1)

        self._layer_list = QListWidget()
        self._layer_list.setObjectName("LayerList")
        self._layer_list.setDragDropMode(QListWidget.InternalMove)
        self._layer_list.model().rowsMoved.connect(self._on_layers_reordered)
        self._layer_list.currentItemChanged.connect(self._on_layer_selected)
        self._layer_list.setIconSize(QSize(28, 28))
        self._layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._layer_list.customContextMenuRequested.connect(self._layer_context_menu)
        self._layer_list.setMaximumHeight(220)
        vl.addWidget(self._layer_list)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        vl.addWidget(sep2)

        # ── Properties / Transitions ───────────────────────────────────────────
        tab_bar = QWidget(); tab_bar.setObjectName("MusicTabBar")
        tbl = QHBoxLayout(tab_bar); tbl.setContentsMargins(12, 8, 12, 0); tbl.setSpacing(4)

        self._right_stack = QStackedWidget()
        self._tab_btns: list[QPushButton] = []

        for i, label in enumerate(["Properties", "Transitions"]):
            btn = QPushButton(label)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            tbl.addWidget(btn)
            self._tab_btns.append(btn)
        tbl.addStretch(1)
        vl.addWidget(tab_bar)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); sep3.setObjectName("Separator")
        vl.addWidget(sep3)

        self._props_panel = SourcePropertiesPanel(on_changed=self._on_source_property_changed)
        self._right_stack.addWidget(self._props_panel)
        self._right_stack.addWidget(self._build_transitions_panel())
        vl.addWidget(self._right_stack, 1)

        return sidebar

    def _switch_tab(self, idx: int) -> None:
        self._right_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == idx)

    def _build_transitions_panel(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(14, 14, 14, 14)
        vl.setSpacing(10)

        vl.addWidget(_field_label("Transition Type"))
        self._transition_combo = QComboBox()
        for key, info in TRANSITION_TYPES.items():
            self._transition_combo.addItem(info["label"], key)
        self._transition_combo.currentIndexChanged.connect(self._on_transition_changed)
        vl.addWidget(self._transition_combo)

        vl.addWidget(_field_label("Duration (ms)"))
        self._duration_spin = QSpinBox()
        self._duration_spin.setObjectName("TimerTransportBtn")
        self._duration_spin.setRange(0, 10000)
        self._duration_spin.setSingleStep(50)
        self._duration_spin.setValue(300)
        self._duration_spin.valueChanged.connect(self._on_transition_changed)
        vl.addWidget(self._duration_spin)

        self._duration_slider = QSlider(Qt.Horizontal)
        self._duration_slider.setObjectName("MusicVolumeSlider")
        self._duration_slider.setRange(0, 5000)
        self._duration_slider.setValue(300)
        self._duration_slider.valueChanged.connect(lambda v: self._duration_spin.setValue(v))
        self._duration_spin.valueChanged.connect(
            lambda v: self._duration_slider.blockSignals(True) or
                      self._duration_slider.setValue(v) or
                      self._duration_slider.blockSignals(False)
        )
        vl.addWidget(self._duration_slider)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        vl.addWidget(_field_label("OBS WebSocket"))

        self._obs_host = QLineEdit("localhost")
        self._obs_host.setObjectName("OverlayTextField")
        vl.addWidget(_field_label("Host"))
        vl.addWidget(self._obs_host)

        self._obs_port = QSpinBox()
        self._obs_port.setObjectName("TimerTransportBtn")
        self._obs_port.setRange(1, 65535)
        self._obs_port.setValue(4455)
        vl.addWidget(_field_label("Port"))
        vl.addWidget(self._obs_port)

        self._obs_pass = QLineEdit()
        self._obs_pass.setObjectName("OverlayTextField")
        self._obs_pass.setEchoMode(QLineEdit.Password)
        self._obs_pass.setPlaceholderText("Password")
        vl.addWidget(_field_label("Password"))
        vl.addWidget(self._obs_pass)

        self._load_obs_settings()
        vl.addStretch(1)
        return w

    # ══════════════════════════════════════════════════════════════════════════
    # SHORTCUTS
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_shortcuts(self) -> None:
        for keys, fn in [
            ("Ctrl+Z",       self._do_undo),
            ("Ctrl+Y",       self._do_redo),
            ("Ctrl+Shift+Z", self._do_redo),
            ("Ctrl+D",       self._duplicate_source),
            ("Ctrl+C",       self._copy_source),
            ("Ctrl+V",       self._paste_source),
            ("Delete",       self._delete_selected_source),
            ("Backspace",    self._delete_selected_source),
        ]:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(fn)

    # ══════════════════════════════════════════════════════════════════════════
    # UNDO
    # ══════════════════════════════════════════════════════════════════════════

    def _make_undo_ctx(self) -> _SceneCtx:
        return _SceneCtx(
            get_scene     = lambda: self._scene,
            save          = lambda s: None,          # save on close, not every action
            canvas_add    = self._canvas.add_source,
            canvas_remove = self._canvas.remove_source,
            canvas_update = self._canvas.update_source,
            refresh_layers= self._refresh_layer_list,
            select_source = lambda s: (
                setattr(self, "_selected_source", s),
                self._props_panel.load(s),
            ),
            props_load    = self._props_panel.load,
        )

    def _do_undo(self) -> None:
        self._undo.undo(); self._update_undo_buttons()

    def _do_redo(self) -> None:
        self._undo.redo(); self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        if self._undo_btn:
            self._undo_btn.setEnabled(self._undo.can_undo())
            tip = f"Undo: {self._undo.undo_text()}  [Ctrl+Z]" if self._undo.can_undo() else "Undo  [Ctrl+Z]"
            self._undo_btn.setToolTip(tip)
        if self._redo_btn:
            self._redo_btn.setEnabled(self._undo.can_redo())
            tip = f"Redo: {self._undo.redo_text()}  [Ctrl+Y]" if self._undo.can_redo() else "Redo  [Ctrl+Y]"
            self._redo_btn.setToolTip(tip)

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCES
    # ══════════════════════════════════════════════════════════════════════════

    def _show_add_source_menu(self) -> None:
        menu = QMenu(self)
        for type_key, info in SOURCE_TYPES.items():
            action = menu.addAction(f"{info['icon']}  {info['label']}")
            action.setData(type_key)
        btn = self.sender()
        pos = btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.rect().center()
        chosen = menu.exec(pos)
        if chosen and chosen.data():
            self._add_source(chosen.data())

    def _add_source(self, source_type: str) -> None:
        name, ok = QInputDialog.getText(
            self, "Add Source",
            f"Name for this {SOURCE_TYPES[source_type]['label']}:",
            text=SOURCE_TYPES[source_type]["label"],
        )
        if not ok or not name.strip():
            return
        source = SourceConfig.new(source_type, name.strip())
        self._undo.push(AddSourceCmd(source, self._make_undo_ctx()))
        self._update_undo_buttons()

    def _delete_selected_source(self) -> None:
        if self._selected_source is None:
            return
        self._undo.push(DeleteSourceCmd(self._selected_source, self._make_undo_ctx()))
        self._selected_source = None
        self._update_undo_buttons()

    def _duplicate_source(self) -> None:
        if self._selected_source is None:
            return
        dup = copy.deepcopy(self._selected_source)
        dup.source_id = str(_uuid.uuid4())
        dup.name      = f"{dup.name} (copy)"
        dup.x += 20; dup.y += 20
        self._undo.push(AddSourceCmd(dup, self._make_undo_ctx()))
        self._update_undo_buttons()

    def _copy_source(self) -> None:
        if self._selected_source:
            self._clipboard = copy.deepcopy(self._selected_source)

    def _paste_source(self) -> None:
        if self._clipboard is None:
            return
        pasted = copy.deepcopy(self._clipboard)
        pasted.source_id = str(_uuid.uuid4())
        pasted.name      = f"{pasted.name} (copy)"
        pasted.x += 20; pasted.y += 20
        self._undo.push(AddSourceCmd(pasted, self._make_undo_ctx()))
        self._update_undo_buttons()

    def _on_source_property_changed(self, source: SourceConfig) -> None:
        before = next((copy.deepcopy(s) for s in self._scene.sources
                       if s.source_id == source.source_id), None)
        for i, s in enumerate(self._scene.sources):
            if s.source_id == source.source_id:
                self._scene.sources[i] = source
                break
        self._canvas.update_source(source)
        self._refresh_layer_list()
        if before:
            cmd = PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Edit properties")
            self._undo._stack = self._undo._stack[:self._undo._pos + 1]
            self._undo._stack.append(cmd)
            if len(self._undo._stack) > self._undo._max:
                self._undo._stack.pop(0)
            self._undo._pos = len(self._undo._stack) - 1
            self._update_undo_buttons()

    def _on_move_committed(self, sid: str, ox: float, oy: float, nx: float, ny: float) -> None:
        if ox == nx and oy == ny:
            return
        cmd = MoveSourceCmd(sid, ox, oy, nx, ny, self._make_undo_ctx())
        self._undo._stack = self._undo._stack[:self._undo._pos + 1]
        self._undo._stack.append(cmd)
        if len(self._undo._stack) > self._undo._max:
            self._undo._stack.pop(0)
        self._undo._pos = len(self._undo._stack) - 1
        self._update_undo_buttons()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYERS
    # ══════════════════════════════════════════════════════════════════════════

    def _refresh_layer_list(self) -> None:
        from PySide6.QtGui import QIcon
        self._layer_list.blockSignals(True)
        self._layer_list.clear()
        for source in reversed(self._scene.sources):
            info  = SOURCE_TYPES.get(source.source_type, {})
            vis   = "👁" if source.visible else "🔴"
            lock  = " 🔒" if source.locked else ""
            label = f"{vis}{lock}   {info.get('icon', '?')}  {source.name}"
            item  = QListWidgetItem(label)
            item.setData(Qt.UserRole, source.source_id)
            canvas_item = self._canvas._items.get(source.source_id)
            if canvas_item:
                item.setIcon(QIcon(canvas_item.thumbnail(28)))
            self._layer_list.addItem(item)
            if self._selected_source and source.source_id == self._selected_source.source_id:
                self._layer_list.setCurrentItem(item)
        self._layer_list.blockSignals(False)

    def _on_layer_selected(self, current, previous) -> None:
        if current is None:
            return
        sid = current.data(Qt.UserRole)
        source = next((s for s in self._scene.sources if s.source_id == sid), None)
        if source:
            self._selected_source = source
            self._props_panel.load(source)

    def _on_canvas_selection(self, source: SourceConfig | None) -> None:
        self._selected_source = source
        self._props_panel.load(source)
        if source:
            for i in range(self._layer_list.count()):
                if self._layer_list.item(i).data(Qt.UserRole) == source.source_id:
                    self._layer_list.blockSignals(True)
                    self._layer_list.setCurrentRow(i)
                    self._layer_list.blockSignals(False)
                    break

    def _on_source_context_menu(self, source: SourceConfig, global_pos) -> None:
        self._selected_source = source
        self._props_panel.load(source)

        menu = QMenu(self)

        # ── Add Source ────────────────────────────────────────────────────────
        add_menu = menu.addMenu("Add Source")
        for type_key, info in SOURCE_TYPES.items():
            act = add_menu.addAction(f"{info['icon']}  {info['label']}")
            act.setData(("add", type_key))

        menu.addSeparator()

        # ── Visibility / Lock ─────────────────────────────────────────────────
        vis_act = menu.addAction("Visible")
        vis_act.setCheckable(True)
        vis_act.setChecked(source.visible)
        vis_act.setData(("toggle_vis",))

        lock_act = menu.addAction("Locked")
        lock_act.setCheckable(True)
        lock_act.setChecked(source.locked)
        lock_act.setData(("toggle_lock",))

        menu.addSeparator()

        # ── Order ─────────────────────────────────────────────────────────────
        order_menu = menu.addMenu("Order")
        order_menu.addAction("Bring to Front").setData(("to_front",))
        order_menu.addAction("Send to Back").setData(("to_back",))
        order_menu.addSeparator()
        order_menu.addAction("Move Up").setData(("move_up",))
        order_menu.addAction("Move Down").setData(("move_down",))

        # ── Transform ─────────────────────────────────────────────────────────
        transform_menu = menu.addMenu("Transform")
        transform_menu.addAction("Center Horizontally").setData(("ctr_h",))
        transform_menu.addAction("Center Vertically").setData(("ctr_v",))
        transform_menu.addSeparator()
        transform_menu.addAction("Fit to Canvas").setData(("fit_canvas",))
        transform_menu.addAction("Reset Transform").setData(("reset_transform",))

        menu.addSeparator()

        # ── Edit ──────────────────────────────────────────────────────────────
        menu.addAction("Copy").setData(("copy",))
        menu.addAction("Paste").setData(("paste",))
        menu.addAction("Duplicate").setData(("duplicate",))

        menu.addSeparator()

        # ── Source ────────────────────────────────────────────────────────────
        menu.addAction("Rename…").setData(("rename",))
        menu.addAction("Properties").setData(("properties",))

        menu.addSeparator()

        rem = menu.addAction("Remove")
        rem.setData(("remove",))

        chosen = menu.exec(global_pos.toPoint() if hasattr(global_pos, "toPoint") else global_pos)
        if chosen is None or chosen.data() is None:
            return

        action = chosen.data()
        tag = action[0]

        if tag == "add":
            self._add_source(action[1])
        elif tag == "toggle_vis":
            self._toggle_visibility(source)
        elif tag == "toggle_lock":
            self._toggle_lock(source)
        elif tag == "to_front":
            self._source_to_front()
        elif tag == "to_back":
            self._source_to_back()
        elif tag == "move_up":
            self._source_up()
        elif tag == "move_down":
            self._source_down()
        elif tag == "ctr_h":
            self._center_on_canvas("h")
        elif tag == "ctr_v":
            self._center_on_canvas("v")
        elif tag == "fit_canvas":
            before = copy.deepcopy(source)
            source.x, source.y, source.width, source.height = 0, 0, CANVAS_W, CANVAS_H
            self._undo.push(PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Fit to canvas"))
            self._canvas.update_source(source)
            self._update_undo_buttons()
        elif tag == "reset_transform":
            before = copy.deepcopy(source)
            source.rotation = 0.0
            self._undo.push(PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Reset transform"))
            self._canvas.update_source(source)
            self._update_undo_buttons()
        elif tag == "copy":
            self._copy_source()
        elif tag == "paste":
            self._paste_source()
        elif tag == "duplicate":
            self._duplicate_source()
        elif tag == "rename":
            name, ok = QInputDialog.getText(self, "Rename Source", "Name:", text=source.name)
            if ok and name.strip():
                before = copy.deepcopy(source)
                source.name = name.strip()
                self._undo.push(PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Rename"))
                self._refresh_layer_list()
                self._update_undo_buttons()
        elif tag == "properties":
            self._switch_tab(0)
            self._props_panel.load(source)
        elif tag == "remove":
            self._delete_selected_source()

    def _on_layers_reordered(self, *args) -> None:
        old_ids = [s.source_id for s in self._scene.sources]
        new_ids = [self._layer_list.item(i).data(Qt.UserRole)
                   for i in range(self._layer_list.count())]
        new_ids.reverse()
        id_map = {s.source_id: s for s in self._scene.sources}
        self._scene.sources = [id_map[sid] for sid in new_ids if sid in id_map]
        self._canvas.set_z_order(new_ids)
        cmd = ReorderCmd(old_ids, [s.source_id for s in self._scene.sources], self._make_undo_ctx())
        self._undo._stack = self._undo._stack[:self._undo._pos + 1]
        self._undo._stack.append(cmd)
        self._undo._pos = len(self._undo._stack) - 1
        self._update_undo_buttons()

    def _layer_context_menu(self, pos) -> None:
        item = self._layer_list.itemAt(pos)
        if item is None:
            return
        sid = item.data(Qt.UserRole)
        source = next((s for s in self._scene.sources if s.source_id == sid), None)
        if source is None:
            return
        menu = QMenu(self)
        vis_label = "Hide" if source.visible else "Show"
        menu.addAction(vis_label, lambda: self._toggle_visibility(source))
        lock_label = "Unlock" if source.locked else "Lock"
        menu.addAction(lock_label, lambda: self._toggle_lock(source))
        menu.addSeparator()
        menu.addAction("Duplicate", self._duplicate_source)
        menu.addAction("Delete", self._delete_selected_source)
        menu.exec(self._layer_list.mapToGlobal(pos))

    def _toggle_visibility(self, source: SourceConfig) -> None:
        before = copy.deepcopy(source)
        source.visible = not source.visible
        cmd = PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Toggle visibility")
        self._undo.push(cmd)
        self._canvas.update_source(source)
        self._refresh_layer_list()
        self._update_undo_buttons()

    def _toggle_lock(self, source: SourceConfig) -> None:
        before = copy.deepcopy(source)
        source.locked = not source.locked
        cmd = PropertyChangeCmd(before, copy.deepcopy(source), self._make_undo_ctx(), "Toggle lock")
        self._undo.push(cmd)
        self._refresh_layer_list()
        self._update_undo_buttons()

    # ── z-order ───────────────────────────────────────────────────────────────

    def _source_move(self, direction: int) -> None:
        if self._selected_source is None:
            return
        sources = self._scene.sources
        idx = next((i for i, s in enumerate(sources) if s.source_id == self._selected_source.source_id), None)
        if idx is None:
            return
        new_idx = max(0, min(len(sources) - 1, idx + direction))
        sources.insert(new_idx, sources.pop(idx))
        self._canvas.set_z_order([s.source_id for s in sources])
        self._refresh_layer_list()

    def _source_up(self):       self._source_move(1)
    def _source_down(self):     self._source_move(-1)
    def _source_to_front(self): self._source_move(999)
    def _source_to_back(self):  self._source_move(-999)

    # ══════════════════════════════════════════════════════════════════════════
    # ALIGNMENT
    # ══════════════════════════════════════════════════════════════════════════

    def _align_sources(self, mode: str) -> None:
        ids  = self._canvas.selected_source_ids()
        if len(ids) < 2 and self._selected_source:
            ids = [self._selected_source.source_id]
        srcs = [s for s in self._scene.sources if s.source_id in ids]
        if len(srcs) < 2:
            return
        for s in srcs:
            before = copy.deepcopy(s)
            if mode == "left":    s.x = min(x.x for x in srcs)
            elif mode == "right": s.x = max(x.x + x.width for x in srcs) - s.width
            elif mode == "center_h":
                cx = sum(x.x + x.width / 2 for x in srcs) / len(srcs)
                s.x = cx - s.width / 2
            elif mode == "top":    s.y = min(x.y for x in srcs)
            elif mode == "bottom": s.y = max(x.y + x.height for x in srcs) - s.height
            elif mode == "center_v":
                cy = sum(x.y + x.height / 2 for x in srcs) / len(srcs)
                s.y = cy - s.height / 2
            cmd = PropertyChangeCmd(before, copy.deepcopy(s), self._make_undo_ctx(), f"Align {mode}")
            self._undo._stack = self._undo._stack[:self._undo._pos + 1]
            self._undo._stack.append(cmd)
            self._undo._pos = len(self._undo._stack) - 1
            self._canvas.update_source(s)
        self._update_undo_buttons()

    # ══════════════════════════════════════════════════════════════════════════
    # CANVAS TOGGLES
    # ══════════════════════════════════════════════════════════════════════════

    def _distribute_sources(self, axis: str) -> None:
        ids  = self._canvas.selected_source_ids()
        srcs = [s for s in self._scene.sources if s.source_id in ids]
        if len(srcs) < 3:
            return
        if axis == "h":
            srcs.sort(key=lambda s: s.x)
            gap = (srcs[-1].x - srcs[0].x - srcs[0].width) / (len(srcs) - 1)
            x = srcs[0].x + srcs[0].width
            for s in srcs[1:-1]:
                s.x = x; x = s.x + s.width + gap
        else:
            srcs.sort(key=lambda s: s.y)
            gap = (srcs[-1].y - srcs[0].y - srcs[0].height) / (len(srcs) - 1)
            y = srcs[0].y + srcs[0].height
            for s in srcs[1:-1]:
                s.y = y; y = s.y + s.height + gap
        for s in srcs:
            self._canvas.update_source(s)

    def _center_on_canvas(self, axis: str) -> None:
        if self._selected_source is None:
            return
        s = self._selected_source
        before = copy.deepcopy(s)
        if axis == "h":
            s.x = (CANVAS_W - s.width) / 2
        else:
            s.y = (CANVAS_H - s.height) / 2
        self._undo.push(PropertyChangeCmd(before, copy.deepcopy(s), self._make_undo_ctx(), "Center on canvas"))
        self._canvas.update_source(s)
        self._update_undo_buttons()

    def _on_snap_toggled(self, on: bool) -> None:
        self._snap_btn.setText("Snap: On" if on else "Snap: Off")
        self._canvas.set_snap(on)

    def _on_grid_toggled(self, on: bool) -> None:
        self._grid_btn.setText("Grid: On" if on else "Grid: Off")
        self._canvas.set_show_grid(on)

    def _on_zoom_changed(self, pct: int) -> None:
        self._zoom_lbl.setText(f"{pct}%")

    def _pick_bg_color(self) -> None:
        current = QColor(getattr(self._scene, "bg_color", "#0d0d1a"))
        col = QColorDialog.getColor(current, self, "Scene Background Color")
        if col.isValid():
            self._scene.bg_color = col.name()
            self._canvas.set_bg_color(col.name())

    # ══════════════════════════════════════════════════════════════════════════
    # TRANSITIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _load_transition_settings(self) -> None:
        idx = self._transition_combo.findData(self._scene.transition_type)
        if idx >= 0:
            self._transition_combo.blockSignals(True)
            self._transition_combo.setCurrentIndex(idx)
            self._transition_combo.blockSignals(False)
        self._duration_spin.blockSignals(True)
        self._duration_spin.setValue(self._scene.transition_duration_ms)
        self._duration_spin.blockSignals(False)

    def _on_transition_changed(self) -> None:
        self._scene.transition_type         = self._transition_combo.currentData() or "fade"
        self._scene.transition_duration_ms  = self._duration_spin.value()

    # ══════════════════════════════════════════════════════════════════════════
    # OBS
    # ══════════════════════════════════════════════════════════════════════════

    def _load_obs_settings(self) -> None:
        if self._obs_settings_path and self._obs_settings_path.exists():
            try:
                import json
                data = json.loads(self._obs_settings_path.read_text())
                self._obs_host.setText(str(data.get("host", "localhost")))
                self._obs_port.setValue(int(data.get("port", 4455)))
            except Exception:
                pass
        try:
            from stream_controller.core.keyring_helper import load
            pw = load("scene_manager", "password")
            if pw:
                self._obs_pass.setText(pw)
        except Exception:
            pass

    def _sync_to_obs(self) -> None:
        host     = self._obs_host.text().strip() or "localhost"
        port     = self._obs_port.value()
        password = self._obs_pass.text()
        self._sync_btn.setEnabled(False)
        self._sync_bar.setText("Connecting to OBS…")
        self._sync_bar.setVisible(True)
        scene = self._scene

        def _worker():
            try:
                req = connect_obs(host, port, password)
                sync_scene(req, scene, on_progress=lambda m: self._sync_sigs.progress.emit(m))
                self._sync_sigs.done.emit("")
            except ObsSyncError as exc:
                self._sync_sigs.done.emit(str(exc))
            except Exception as exc:
                self._sync_sigs.done.emit(f"Unexpected error: {exc}")

        threading.Thread(target=_worker, daemon=True, name="obs-sync").start()

    def _on_sync_progress(self, msg: str) -> None:
        self._sync_bar.setText(msg)
        self._sync_bar.setVisible(True)

    def _on_sync_done(self, error: str) -> None:
        self._sync_btn.setEnabled(True)
        if error:
            self._sync_bar.setText(f"⚠ {error}")
            self._sync_bar.setStyleSheet("color: #ef4444;")
        else:
            self._sync_bar.setText("✓ Synced to OBS")
            self._sync_bar.setStyleSheet("color: #22c55e;")
        self._sync_bar.setVisible(True)

    def _import_from_obs(self) -> None:
        host     = self._obs_host.text().strip() or "localhost"
        port     = self._obs_port.value()
        password = self._obs_pass.text()

        dlg = QDialog(self)
        dlg.setWindowTitle("Import Scenes from OBS")
        dlg.setMinimumSize(460, 360)
        dlg.setModal(True)
        self._import_dialog = dlg

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(10)

        title_lbl = QLabel("Import Scenes from OBS"); title_lbl.setObjectName("PageTitle")
        vl.addWidget(title_lbl)
        sub_lbl = QLabel("Connecting to OBS…"); sub_lbl.setObjectName("CardDescription")
        sub_lbl.setWordWrap(True)
        vl.addWidget(sub_lbl)

        scene_list = QListWidget(); scene_list.setEnabled(False)
        vl.addWidget(scene_list, 1)

        sel_row = QWidget(); sl = QHBoxLayout(sel_row); sl.setContentsMargins(0, 0, 0, 0)
        all_btn  = QPushButton("Select All");  all_btn.setObjectName("SecondaryButton")
        none_btn = QPushButton("Select None"); none_btn.setObjectName("SecondaryButton")
        sl.addWidget(all_btn); sl.addWidget(none_btn); sl.addStretch()
        vl.addWidget(sel_row)

        prog_lbl = QLabel(""); prog_lbl.setObjectName("MetaText"); prog_lbl.setWordWrap(True)
        vl.addWidget(prog_lbl)

        btn_box = QDialogButtonBox()
        import_btn = btn_box.addButton("Import Selected", QDialogButtonBox.AcceptRole)
        cancel_btn = btn_box.addButton("Cancel",          QDialogButtonBox.RejectRole)
        import_btn.setObjectName("PrimaryButton"); import_btn.setEnabled(False)
        vl.addWidget(btn_box)

        all_btn.clicked.connect(lambda: [scene_list.item(i).setCheckState(Qt.Checked)   for i in range(scene_list.count())])
        none_btn.clicked.connect(lambda: [scene_list.item(i).setCheckState(Qt.Unchecked) for i in range(scene_list.count())])

        def _do_import():
            selected = [scene_list.item(i).text() for i in range(scene_list.count())
                        if scene_list.item(i).checkState() == Qt.Checked]
            if not selected:
                prog_lbl.setText("Select at least one scene."); return
            import_btn.setEnabled(False); cancel_btn.setEnabled(False); scene_list.setEnabled(False)
            self._import_pending = len(selected)
            prog_lbl.setText(f"Importing 0 / {self._import_pending}…")
            for name in selected:
                threading.Thread(
                    target=self._import_worker, args=(host, port, password, name), daemon=True
                ).start()

        def _on_fetched(names):
            scene_list.clear()
            if not names:
                sub_lbl.setText("No scenes found in OBS."); return
            for name in names:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                scene_list.addItem(item)
            scene_list.setEnabled(True); import_btn.setEnabled(True)
            sub_lbl.setText(f"Found {len(names)} scene(s). Select which to import.")

        def _on_fetch_err(msg):
            sub_lbl.setText(f"⚠ Could not connect to OBS: {msg}")

        self._import_sigs.scenes_fetched.connect(_on_fetched)
        self._import_sigs.fetch_error.connect(_on_fetch_err)
        self._import_sigs.progress.connect(prog_lbl.setText)
        btn_box.accepted.connect(_do_import)
        btn_box.rejected.connect(dlg.reject)

        threading.Thread(target=self._fetch_scenes_worker, args=(host, port, password), daemon=True).start()
        dlg.exec()

        self._import_sigs.scenes_fetched.disconnect(_on_fetched)
        self._import_sigs.fetch_error.disconnect(_on_fetch_err)
        self._import_sigs.progress.disconnect(prog_lbl.setText)
        self._import_dialog = None

    def _fetch_scenes_worker(self, host, port, password):
        try:
            self._import_sigs.scenes_fetched.emit(fetch_obs_scenes(host, port, password))
        except ObsSyncError as exc:
            self._import_sigs.fetch_error.emit(str(exc))
        except Exception as exc:
            self._import_sigs.fetch_error.emit(f"Unexpected error: {exc}")

    def _import_worker(self, host, port, password, name):
        try:
            scene = obs_import_scene(host, port, password, name,
                                     on_progress=self._import_sigs.progress.emit)
            self._import_sigs.scene_imported.emit(scene)
        except Exception as exc:
            self._import_sigs.import_error.emit(f"'{name}': {exc}")

    def _on_scene_imported(self, scene) -> None:
        self._repo.save_scene(scene)
        self._import_pending -= 1
        if self._import_pending == 0 and self._import_dialog:
            self._import_dialog.accept()

    def _on_import_error(self, msg: str) -> None:
        self._import_pending -= 1
        if self._import_pending == 0 and self._import_dialog and self._import_dialog.isVisible():
            QMessageBox.warning(self._import_dialog, "Import Error", msg)
            self._import_dialog.accept()

    # ══════════════════════════════════════════════════════════════════════════
    # SAVE / CLOSE
    # ══════════════════════════════════════════════════════════════════════════

    def _save_and_close(self) -> None:
        self._repo.save_scene(self._scene)
        self.scene_saved.emit(self._scene.scene_id)
        self.accept()

    def closeEvent(self, event) -> None:
        self._repo.save_scene(self._scene)
        self.scene_saved.emit(self._scene.scene_id)
        super().closeEvent(event)


# ── helpers ───────────────────────────────────────────────────────────────────

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text); lbl.setObjectName("MusicFieldLabel")
    return lbl
