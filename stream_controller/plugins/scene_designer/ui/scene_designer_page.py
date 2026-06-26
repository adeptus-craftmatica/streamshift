from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider,
    QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from stream_controller.plugins.scene_designer.designer_models import (
    CANVAS_W, CANVAS_H, SOURCE_TYPES, TRANSITION_TYPES,
    DesignerScene, SourceConfig,
)
from stream_controller.plugins.scene_designer.designer_repository import DesignerRepository
from stream_controller.plugins.scene_designer.obs_sync import ObsSyncError, connect_obs, sync_scene
from stream_controller.plugins.scene_designer.ui.canvas_widget import CanvasView
from stream_controller.plugins.scene_designer.ui.source_properties import SourcePropertiesPanel


# ── sync result signal ────────────────────────────────────────────────────────

class _SyncSignals(QObject):
    done = Signal(str)   # empty = success, non-empty = error message
    progress = Signal(str)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

class SceneDesignerPage(QWidget):
    def __init__(
        self,
        repo: DesignerRepository,
        obs_settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._obs_settings_path = obs_settings_path
        self._active_scene: DesignerScene | None = None
        self._selected_source: SourceConfig | None = None
        self._sync_sigs = _SyncSignals()
        self._sync_sigs.done.connect(self._on_sync_done)
        self._sync_sigs.progress.connect(self._on_sync_progress)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: scene list (240px) ──────────────────────────────────────────
        left = self._build_scene_list_panel()
        left.setFixedWidth(240)
        root.addWidget(left)

        _vsep = QFrame(); _vsep.setFrameShape(QFrame.VLine); _vsep.setObjectName("Separator")
        root.addWidget(_vsep)

        # ── Center: canvas + layer list ───────────────────────────────────────
        center = self._build_center_panel()
        root.addWidget(center, 1)

        _vsep2 = QFrame(); _vsep2.setFrameShape(QFrame.VLine); _vsep2.setObjectName("Separator")
        root.addWidget(_vsep2)

        # ── Right: properties + transitions (300px) ───────────────────────────
        right = self._build_right_panel()
        right.setFixedWidth(300)
        root.addWidget(right)

        self._refresh_scene_list()

    # ══════════════════════════════════════════════════════════════════════════
    # PANELS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_scene_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("SidebarPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("SidebarHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)
        title = QLabel("Scenes")
        title.setObjectName("CardTitle")
        hl.addWidget(title, 1)
        layout.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        layout.addWidget(sep)

        self._scene_list = QListWidget()
        self._scene_list.setObjectName("SidebarList")
        self._scene_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._scene_list.customContextMenuRequested.connect(self._scene_context_menu)
        self._scene_list.currentItemChanged.connect(self._on_scene_selected)
        layout.addWidget(self._scene_list, 1)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        layout.addWidget(sep2)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 10, 10, 10)
        btn_row.setSpacing(6)

        add_btn = QPushButton("+ New Scene")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_scene)
        btn_row.addWidget(add_btn)

        dup_btn = QPushButton("Duplicate")
        dup_btn.setObjectName("SecondaryButton")
        dup_btn.clicked.connect(self._duplicate_scene)
        btn_row.addWidget(dup_btn)

        layout.addLayout(btn_row)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Toolbar
        toolbar = self._build_toolbar()
        vl.addWidget(toolbar)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        # Canvas
        self._canvas = CanvasView()
        self._canvas.source_selected.connect(self._on_canvas_selection)
        vl.addWidget(self._canvas, 3)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        vl.addWidget(sep2)

        # Layer list
        layer_header = self._build_layer_header()
        vl.addWidget(layer_header)

        self._layer_list = QListWidget()
        self._layer_list.setObjectName("LayerList")
        self._layer_list.setMaximumHeight(140)
        self._layer_list.setDragDropMode(QListWidget.InternalMove)
        self._layer_list.model().rowsMoved.connect(self._on_layers_reordered)
        self._layer_list.currentItemChanged.connect(self._on_layer_selected)
        vl.addWidget(self._layer_list)

        # OBS sync status bar
        self._sync_bar = QLabel("")
        self._sync_bar.setObjectName("CardDescription")
        self._sync_bar.setContentsMargins(14, 6, 14, 6)
        self._sync_bar.setVisible(False)
        vl.addWidget(self._sync_bar)

        return panel

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("DesignerToolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(8)

        # Add source button (dropdown menu)
        add_src = QPushButton("＋ Add Source ▾")
        add_src.setObjectName("PrimaryButton")
        add_src.clicked.connect(self._show_add_source_menu)
        bl.addWidget(add_src)

        del_src = QPushButton("Remove Source")
        del_src.setObjectName("SecondaryButton")
        del_src.clicked.connect(self._delete_selected_source)
        bl.addWidget(del_src)

        bl.addWidget(_vsep_widget())

        # Z-order buttons
        for label, tip, fn in [
            ("↑", "Move source up", self._source_up),
            ("↓", "Move source down", self._source_down),
            ("⤒", "Bring to front", self._source_to_front),
            ("⤓", "Send to back", self._source_to_back),
        ]:
            b = QPushButton(label)
            b.setObjectName("SecondaryButton")
            b.setToolTip(tip)
            b.setFixedWidth(36)
            b.clicked.connect(fn)
            bl.addWidget(b)

        bl.addWidget(_vsep_widget())

        # Snap / grid
        self._snap_btn = QPushButton("Snap: ON")
        self._snap_btn.setObjectName("SecondaryButton")
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._snap_btn.toggled.connect(lambda on: self._snap_btn.setText(f"Snap: {'ON' if on else 'OFF'}"))
        bl.addWidget(self._snap_btn)

        bl.addStretch(1)

        # Sync to OBS
        self._sync_btn = QPushButton("⬆ Sync to OBS")
        self._sync_btn.setObjectName("PrimaryButton")
        self._sync_btn.clicked.connect(self._sync_to_obs)
        bl.addWidget(self._sync_btn)

        return bar

    def _build_layer_header(self) -> QWidget:
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.setSpacing(8)
        lbl = QLabel("Sources / Layers")
        lbl.setObjectName("MusicFieldLabel")
        bl.addWidget(lbl, 1)
        hint = QLabel("Drag to reorder")
        hint.setObjectName("CardDescription")
        bl.addWidget(hint)
        return bar

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("SidebarPanel")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Tab bar: Properties | Transitions
        tab_bar = QWidget()
        tab_bar.setObjectName("MusicTabBar")
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(12, 10, 12, 0)
        tbl.setSpacing(4)

        self._right_stack = QStackedWidget()

        for i, label in enumerate(["Properties", "Transitions"]):
            btn = QPushButton(label)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._right_stack.setCurrentIndex(idx))
            tbl.addWidget(btn)
        tbl.addStretch(1)
        vl.addWidget(tab_bar)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        # Properties tab
        self._props_panel = SourcePropertiesPanel(on_changed=self._on_source_property_changed)
        self._right_stack.addWidget(self._props_panel)

        # Transitions tab
        self._right_stack.addWidget(self._build_transitions_panel())

        vl.addWidget(self._right_stack, 1)
        return panel

    def _build_transitions_panel(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(14, 14, 14, 14)
        vl.setSpacing(14)

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
        vl.addWidget(self._duration_slider)

        self._duration_spin.valueChanged.connect(
            lambda v: self._duration_slider.blockSignals(True) or
                      self._duration_slider.setValue(v) or
                      self._duration_slider.blockSignals(False)
        )

        hint = QLabel(
            "The transition plays when switching to this scene in StreamShift.\n"
            "When synced to OBS, the global OBS transition duration is also updated."
        )
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        vl.addWidget(hint)

        # OBS Connection settings
        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        vl.addWidget(_field_label("OBS WebSocket (for Sync)"))
        self._obs_host = QLineEdit("localhost")
        self._obs_host.setObjectName("OverlayTextField")
        self._obs_host.setPlaceholderText("localhost")
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
        self._obs_pass.setPlaceholderText("OBS WebSocket password")
        vl.addWidget(_field_label("Password"))
        vl.addWidget(self._obs_pass)

        self._load_obs_settings()

        vl.addStretch(1)
        return w

    # ══════════════════════════════════════════════════════════════════════════
    # SCENE LIST
    # ══════════════════════════════════════════════════════════════════════════

    def _refresh_scene_list(self) -> None:
        current_id = self._active_scene.scene_id if self._active_scene else None
        self._scene_list.blockSignals(True)
        self._scene_list.clear()
        for scene in self._repo.list_scenes():
            item = QListWidgetItem(scene.name)
            item.setData(Qt.UserRole, scene.scene_id)
            self._scene_list.addItem(item)
            if scene.scene_id == current_id:
                self._scene_list.setCurrentItem(item)
        self._scene_list.blockSignals(False)

        if not self._active_scene and self._scene_list.count():
            self._scene_list.setCurrentRow(0)
            self._load_scene(self._scene_list.item(0).data(Qt.UserRole))

    def _on_scene_selected(self, current, previous) -> None:
        if current:
            self._load_scene(current.data(Qt.UserRole))

    def _load_scene(self, scene_id: str) -> None:
        scene = self._repo.get(scene_id)
        if scene is None:
            return
        self._active_scene = scene
        self._canvas.load_scene(scene.sources)
        self._refresh_layer_list()
        self._props_panel.load(None)
        self._selected_source = None

        # Load transition settings
        idx = self._transition_combo.findData(scene.transition_type)
        if idx >= 0:
            self._transition_combo.blockSignals(True)
            self._transition_combo.setCurrentIndex(idx)
            self._transition_combo.blockSignals(False)
        self._duration_spin.blockSignals(True)
        self._duration_spin.setValue(scene.transition_duration_ms)
        self._duration_spin.blockSignals(False)
        self._duration_slider.blockSignals(True)
        self._duration_slider.setValue(scene.transition_duration_ms)
        self._duration_slider.blockSignals(False)

    def _add_scene(self) -> None:
        name, ok = QInputDialog.getText(self, "New Scene", "Scene name:", text="New Scene")
        if not ok or not name.strip():
            return
        scene = DesignerScene.new(name.strip())
        self._repo.save_scene(scene)
        self._refresh_scene_list()
        # Select the new scene
        for i in range(self._scene_list.count()):
            if self._scene_list.item(i).data(Qt.UserRole) == scene.scene_id:
                self._scene_list.setCurrentRow(i)
                break

    def _duplicate_scene(self) -> None:
        if not self._active_scene:
            return
        import copy, uuid as _uuid
        dup = copy.deepcopy(self._active_scene)
        dup.scene_id = str(_uuid.uuid4())
        dup.name = f"{dup.name} (copy)"
        for src in dup.sources:
            src.source_id = str(_uuid.uuid4())
        self._repo.save_scene(dup)
        self._refresh_scene_list()

    def _scene_context_menu(self, pos) -> None:
        item = self._scene_list.itemAt(pos)
        if item is None:
            return
        scene_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("Rename", lambda: self._rename_scene(scene_id, item))
        menu.addAction("Duplicate", self._duplicate_scene)
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete_scene(scene_id))
        menu.exec(self._scene_list.mapToGlobal(pos))

    def _rename_scene(self, scene_id: str, item: QListWidgetItem) -> None:
        name, ok = QInputDialog.getText(self, "Rename Scene", "New name:", text=item.text())
        if ok and name.strip():
            self._repo.rename_scene(scene_id, name.strip())
            item.setText(name.strip())
            if self._active_scene and self._active_scene.scene_id == scene_id:
                self._active_scene.name = name.strip()

    def _delete_scene(self, scene_id: str) -> None:
        scene = self._repo.get(scene_id)
        if scene is None:
            return
        btn = QMessageBox.question(
            self, "Delete Scene",
            f"Delete '{scene.name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if btn != QMessageBox.Yes:
            return
        self._repo.delete_scene(scene_id)
        if self._active_scene and self._active_scene.scene_id == scene_id:
            self._active_scene = None
            self._canvas.load_scene([])
            self._refresh_layer_list()
        self._refresh_scene_list()

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCES / LAYERS
    # ══════════════════════════════════════════════════════════════════════════

    def _show_add_source_menu(self) -> None:
        if self._active_scene is None:
            QMessageBox.information(self, "No Scene", "Create or select a scene first.")
            return
        menu = QMenu(self)
        for type_key, info in SOURCE_TYPES.items():
            action = menu.addAction(f"{info['icon']}  {info['label']}")
            action.setData(type_key)
        chosen = menu.exec(self.mapToGlobal(
            self.sender().pos() if self.sender() else self.rect().center()
        ))
        if chosen and chosen.data():
            self._add_source(chosen.data())

    def _add_source(self, source_type: str) -> None:
        if self._active_scene is None:
            return
        name, ok = QInputDialog.getText(
            self, "Add Source",
            f"Name for this {SOURCE_TYPES[source_type]['label']}:",
            text=SOURCE_TYPES[source_type]["label"],
        )
        if not ok or not name.strip():
            return
        source = SourceConfig.new(source_type, name.strip())
        self._active_scene.sources.append(source)
        self._repo.save_scene(self._active_scene)
        self._canvas.add_source(source)
        self._refresh_layer_list()
        self._select_source(source)

    def _delete_selected_source(self) -> None:
        if self._active_scene is None or self._selected_source is None:
            return
        sid = self._selected_source.source_id
        self._active_scene.sources = [s for s in self._active_scene.sources if s.source_id != sid]
        self._repo.save_scene(self._active_scene)
        self._canvas.remove_source(sid)
        self._refresh_layer_list()
        self._props_panel.load(None)
        self._selected_source = None

    def _refresh_layer_list(self) -> None:
        self._layer_list.blockSignals(True)
        self._layer_list.clear()
        if self._active_scene:
            # Show in reverse z-order (top of list = topmost layer)
            for source in reversed(self._active_scene.sources):
                info = SOURCE_TYPES.get(source.source_type, {})
                icon = info.get("icon", "?")
                vis = "👁" if source.visible else "🚫"
                item = QListWidgetItem(f"  {vis}  {icon}  {source.name}")
                item.setData(Qt.UserRole, source.source_id)
                self._layer_list.addItem(item)
                if self._selected_source and source.source_id == self._selected_source.source_id:
                    self._layer_list.setCurrentItem(item)
        self._layer_list.blockSignals(False)

    def _on_layer_selected(self, current, previous) -> None:
        if current is None or self._active_scene is None:
            return
        sid = current.data(Qt.UserRole)
        source = next((s for s in self._active_scene.sources if s.source_id == sid), None)
        if source:
            self._select_source(source)

    def _on_canvas_selection(self, source: SourceConfig | None) -> None:
        self._selected_source = source
        self._props_panel.load(source)
        if source:
            # Sync layer list selection
            for i in range(self._layer_list.count()):
                if self._layer_list.item(i).data(Qt.UserRole) == source.source_id:
                    self._layer_list.blockSignals(True)
                    self._layer_list.setCurrentRow(i)
                    self._layer_list.blockSignals(False)
                    break

    def _select_source(self, source: SourceConfig) -> None:
        self._selected_source = source
        self._props_panel.load(source)

    def _on_source_property_changed(self, source: SourceConfig) -> None:
        if self._active_scene is None:
            return
        # Update in the scene's source list
        for i, s in enumerate(self._active_scene.sources):
            if s.source_id == source.source_id:
                self._active_scene.sources[i] = source
                break
        self._repo.save_scene(self._active_scene)
        self._canvas.update_source(source)
        self._refresh_layer_list()

    def _on_layers_reordered(self, *args) -> None:
        if self._active_scene is None:
            return
        # Rebuild source order from list (list shows top→bottom, scene stores bottom→top)
        new_order_ids = [
            self._layer_list.item(i).data(Qt.UserRole)
            for i in range(self._layer_list.count())
        ]
        new_order_ids.reverse()  # list is top→bottom, model is bottom→top
        id_to_source = {s.source_id: s for s in self._active_scene.sources}
        self._active_scene.sources = [id_to_source[sid] for sid in new_order_ids if sid in id_to_source]
        self._repo.save_scene(self._active_scene)
        self._canvas.set_z_order(new_order_ids)

    # ── z-order controls ──────────────────────────────────────────────────────

    def _source_move(self, direction: int) -> None:
        if self._active_scene is None or self._selected_source is None:
            return
        sources = self._active_scene.sources
        idx = next((i for i, s in enumerate(sources) if s.source_id == self._selected_source.source_id), None)
        if idx is None:
            return
        new_idx = max(0, min(len(sources) - 1, idx + direction))
        sources.insert(new_idx, sources.pop(idx))
        self._repo.save_scene(self._active_scene)
        self._canvas.set_z_order([s.source_id for s in sources])
        self._refresh_layer_list()

    def _source_up(self):    self._source_move(1)
    def _source_down(self):  self._source_move(-1)
    def _source_to_front(self): self._source_move(999)
    def _source_to_back(self):  self._source_move(-999)

    # ══════════════════════════════════════════════════════════════════════════
    # TRANSITIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_transition_changed(self) -> None:
        if self._active_scene is None:
            return
        self._active_scene.transition_type = self._transition_combo.currentData() or "fade"
        self._active_scene.transition_duration_ms = self._duration_spin.value()
        self._repo.save_scene(self._active_scene)

    # ══════════════════════════════════════════════════════════════════════════
    # OBS SYNC
    # ══════════════════════════════════════════════════════════════════════════

    def _load_obs_settings(self) -> None:
        if self._obs_settings_path and self._obs_settings_path.exists():
            try:
                import json
                data = json.loads(self._obs_settings_path.read_text())
                self._obs_host.setText(str(data.get("host", "localhost")))
                self._obs_port.setValue(int(data.get("port", 4455)))
                # Password is in keychain for scene_manager — we don't load it here
                # to avoid coupling. User enters it in the Transitions tab.
            except Exception:
                pass

    def _sync_to_obs(self) -> None:
        if self._active_scene is None:
            QMessageBox.information(self, "No Scene", "Select a scene to sync.")
            return

        host = self._obs_host.text().strip() or "localhost"
        port = self._obs_port.value()
        password = self._obs_pass.text()

        self._sync_btn.setEnabled(False)
        self._sync_bar.setText("Connecting to OBS…")
        self._sync_bar.setVisible(True)

        scene = self._active_scene  # capture reference

        def _worker():
            try:
                req = connect_obs(host, port, password)
                sync_scene(
                    req, scene,
                    on_progress=lambda msg: self._sync_sigs.progress.emit(msg),
                )
                self._sync_sigs.done.emit("")
            except ObsSyncError as exc:
                self._sync_sigs.done.emit(str(exc))
            except Exception as exc:
                self._sync_sigs.done.emit(f"Unexpected error: {exc}")

        threading.Thread(target=_worker, daemon=True, name="obs-sync").start()

    def _on_sync_progress(self, msg: str) -> None:
        self._sync_bar.setText(msg)

    def _on_sync_done(self, error: str) -> None:
        self._sync_btn.setEnabled(True)
        if error:
            self._sync_bar.setText(f"⚠ {error}")
            self._sync_bar.setStyleSheet("color: #ef4444;")
        else:
            self._sync_bar.setText("✓ Scene synced to OBS successfully")
            self._sync_bar.setStyleSheet("color: #22c55e;")


# ── helpers ───────────────────────────────────────────────────────────────────

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("MusicFieldLabel")
    return lbl


def _vsep_widget() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setObjectName("Separator")
    return f
