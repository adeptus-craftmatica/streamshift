from __future__ import annotations

import copy
import uuid as _uuid
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from stream_controller.plugins.scene_designer.designer_models import (
    DesignerScene, SourceConfig,
)
from stream_controller.plugins.scene_designer.designer_repository import DesignerRepository
from stream_controller.plugins.scene_designer.ui.canvas_widget import CanvasView
from stream_controller.plugins.scene_designer.ui.scene_editor_window import SceneEditorWindow


class SceneDesignerPage(QWidget):
    """Scene browser — select a scene to preview, click Edit to open the editor."""

    def __init__(
        self,
        repo: DesignerRepository,
        obs_settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._repo              = repo
        self._obs_settings_path = obs_settings_path
        self._active_scene: DesignerScene | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: scene list ──────────────────────────────────────────────────
        left = self._build_scene_list_panel()
        left.setFixedWidth(240)
        root.addWidget(left)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setObjectName("Separator")
        root.addWidget(sep)

        # ── Right: preview + edit button ──────────────────────────────────────
        root.addWidget(self._build_preview_panel(), 1)

        self._refresh_scene_list()

    # ══════════════════════════════════════════════════════════════════════════
    # SCENE LIST PANEL
    # ══════════════════════════════════════════════════════════════════════════

    def _build_scene_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("SidebarPanel")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        header = QWidget(); header.setObjectName("SidebarHeader")
        hl = QHBoxLayout(header); hl.setContentsMargins(14, 12, 14, 12)
        title = QLabel("Scenes"); title.setObjectName("CardTitle")
        hl.addWidget(title, 1)
        vl.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        self._scene_list = QListWidget()
        self._scene_list.setObjectName("SidebarList")
        self._scene_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._scene_list.customContextMenuRequested.connect(self._scene_context_menu)
        self._scene_list.currentItemChanged.connect(self._on_scene_selected)
        vl.addWidget(self._scene_list, 1)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        vl.addWidget(sep2)

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

        vl.addLayout(btn_row)
        return panel

    # ══════════════════════════════════════════════════════════════════════════
    # PREVIEW PANEL
    # ══════════════════════════════════════════════════════════════════════════

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header with scene name + edit button
        header = QWidget(); header.setObjectName("SidebarHeader")
        hl = QHBoxLayout(header); hl.setContentsMargins(16, 12, 16, 12)

        self._scene_name_lbl = QLabel("Select a scene")
        self._scene_name_lbl.setObjectName("PageTitle")
        hl.addWidget(self._scene_name_lbl, 1)

        self._edit_btn = QPushButton("Edit Scene")
        self._edit_btn.setObjectName("PrimaryButton")
        self._edit_btn.setToolTip("Open full editor for this scene")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._open_editor)
        hl.addWidget(self._edit_btn)

        vl.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        # Read-only canvas preview
        self._preview_canvas = CanvasView(interactive=False)
        vl.addWidget(self._preview_canvas, 1)

        # Source count hint at the bottom
        self._source_count_lbl = QLabel("")
        self._source_count_lbl.setObjectName("CardDescription")
        self._source_count_lbl.setContentsMargins(16, 8, 16, 8)
        vl.addWidget(self._source_count_lbl)

        return panel

    # ══════════════════════════════════════════════════════════════════════════
    # SCENE LIST LOGIC
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
        self._scene_name_lbl.setText(scene.name)
        self._edit_btn.setEnabled(True)

        self._preview_canvas.load_scene(scene.sources)
        bg = getattr(scene, "bg_color", "#0d0d1a")
        self._preview_canvas.set_bg_color(bg)

        n = len(scene.sources)
        self._source_count_lbl.setText(
            f"{n} source{'s' if n != 1 else ''}  ·  Double-click or press Edit Scene to modify"
        )

    def _add_scene(self) -> None:
        name, ok = QInputDialog.getText(self, "New Scene", "Scene name:", text="New Scene")
        if not ok or not name.strip():
            return
        scene = DesignerScene.new(name.strip())
        self._repo.save_scene(scene)
        self._refresh_scene_list()
        for i in range(self._scene_list.count()):
            if self._scene_list.item(i).data(Qt.UserRole) == scene.scene_id:
                self._scene_list.setCurrentRow(i)
                break

    def _duplicate_scene(self) -> None:
        if not self._active_scene:
            return
        dup          = copy.deepcopy(self._active_scene)
        dup.scene_id = str(_uuid.uuid4())
        dup.name     = f"{dup.name} (copy)"
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
        menu.addAction("Edit Scene",  self._open_editor)
        menu.addSeparator()
        menu.addAction("Rename",    lambda: self._rename_scene(scene_id, item))
        menu.addAction("Duplicate", self._duplicate_scene)
        menu.addSeparator()
        menu.addAction("Delete",    lambda: self._delete_scene(scene_id))
        menu.exec(self._scene_list.mapToGlobal(pos))

    def _rename_scene(self, scene_id: str, item: QListWidgetItem) -> None:
        name, ok = QInputDialog.getText(self, "Rename Scene", "New name:", text=item.text())
        if ok and name.strip():
            self._repo.rename_scene(scene_id, name.strip())
            item.setText(name.strip())
            if self._active_scene and self._active_scene.scene_id == scene_id:
                self._active_scene.name = name.strip()
                self._scene_name_lbl.setText(name.strip())

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
            self._preview_canvas.load_scene([])
            self._scene_name_lbl.setText("Select a scene")
            self._edit_btn.setEnabled(False)
            self._source_count_lbl.setText("")
        self._refresh_scene_list()

    # ══════════════════════════════════════════════════════════════════════════
    # EDITOR
    # ══════════════════════════════════════════════════════════════════════════

    def _open_editor(self) -> None:
        if self._active_scene is None:
            return
        win = SceneEditorWindow(
            scene=self._active_scene,
            repo=self._repo,
            obs_settings_path=self._obs_settings_path,
            parent=self,
        )
        win.scene_saved.connect(self._on_editor_saved)
        win.showMaximized()
        win.exec()

    def _on_editor_saved(self, scene_id: str) -> None:
        if self._active_scene and self._active_scene.scene_id == scene_id:
            self._load_scene(scene_id)
        self._refresh_scene_list()
