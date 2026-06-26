from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stream_controller.ui.stage_view.layout_repository import LayoutRepository
from stream_controller.ui.stage_view.stage_layout import StageLayout
from stream_controller.ui.stage_view.stage_panel import StagePanel

if TYPE_CHECKING:
    from stream_controller.ui.stage_view.stage_registry import StageRegistry

logger = logging.getLogger(__name__)

_DEFAULT_PANEL_W = 380
_DEFAULT_PANEL_H = 300
_CANVAS_W = 1920
_CANVAS_H = 1080

_ICONS_DIR = Path.home() / ".streamshift" / "stage_icons"

# ── Preset panel themes ────────────────────────────────────────────────────────
# Each entry: (display_name, accent_hex, bg_hex, border_hex)
# Names are descriptive for colorblind accessibility — color is redundant, not essential.

_PRESET_THEMES = [
    ("Default Purple",    "#7c3aed", "",        ""),
    ("Deep Indigo",       "#4f46e5", "#0c0b1a", "#1e1a3a"),
    ("Ocean Blue",        "#2563eb", "#060c1a", "#0d2040"),
    ("Sky Blue",          "#0284c7", "#060e18", "#0a2030"),
    ("Teal / Aqua",       "#0d9488", "#061210", "#0a2420"),
    ("Forest Green",      "#16a34a", "#060e07", "#0a2010"),
    ("Lime / Neon",       "#65a30d", "#080d04", "#142009"),
    ("Gold / Amber",      "#d97706", "#120a00", "#2a1a00"),
    ("Burnt Orange",      "#ea580c", "#120600", "#280d00"),
    ("Crimson Red",       "#dc2626", "#120606", "#2a0a0a"),
    ("Rose / Hot Pink",   "#e11d48", "#120408", "#280810"),
    ("Pink / Magenta",    "#db2777", "#120308", "#280810"),
    ("Slate / Grey",      "#475569", "#0a0c10", "#181e28"),
    ("Warm White",        "#d1d5db", "#101010", "#2a2a2a"),
    ("Cyberpunk Cyan",    "#06b6d4", "#020610", "#041830"),
    ("Aurora / Emerald",  "#10b981", "#040c08", "#0a2018"),
]


class StageViewPage(QWidget):
    """
    Freeform drag-and-drop layout designer.
    Panels can be dragged, resized by edges/corners, and the layout auto-saves.
    A fullscreen button pops the canvas onto any connected display.
    """

    # Emitted after a panel is added — lets the theme manager plugin re-apply overrides.
    panel_added = Signal(str)

    def __init__(self, registry: "StageRegistry") -> None:
        super().__init__()
        self._registry      = registry
        self._layout_db     = StageLayout()
        self._layout_repo   = LayoutRepository()
        self._panels:  dict[str, StagePanel] = {}
        self._edit_mode = True
        self._fullscreen_window: QWidget | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self._scroll, 1)

        self._canvas = QWidget()
        self._canvas.setObjectName("StageCanvas")
        self._canvas.setFixedSize(_CANVAS_W, _CANVAS_H)
        self._scroll.setWidget(self._canvas)

        self._layout_restored = False
        QTimer.singleShot(0, self._restore_layout)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self._exit_fullscreen)

    # ── toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StageToolbar")
        bar.setFixedHeight(48)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        title = QLabel("Stage View")
        title.setObjectName("StageToolbarTitle")
        layout.addWidget(title)
        layout.addStretch(1)

        self._edit_btn = QPushButton("✏  Edit Layout")
        self._edit_btn.setObjectName("StageToolbarBtn")
        self._edit_btn.setCheckable(True)
        self._edit_btn.setChecked(True)
        self._edit_btn.toggled.connect(self._on_edit_toggled)
        layout.addWidget(self._edit_btn)

        add_btn = QPushButton("＋  Add Panel")
        add_btn.setObjectName("StagePrimaryBtn")
        add_btn.clicked.connect(self._show_add_dialog)
        layout.addWidget(add_btn)

        layout.addSpacing(8)

        save_layout_btn = QPushButton("💾  Save Layout")
        save_layout_btn.setObjectName("StageToolbarBtn")
        save_layout_btn.clicked.connect(self._save_named_layout)
        layout.addWidget(save_layout_btn)

        load_layout_btn = QPushButton("📂  Load Layout")
        load_layout_btn.setObjectName("StageToolbarBtn")
        load_layout_btn.clicked.connect(self._show_load_layout_dialog)
        layout.addWidget(load_layout_btn)

        layout.addSpacing(8)

        fs_btn = QPushButton("⛶  Fullscreen")
        fs_btn.setObjectName("StageToolbarBtn")
        fs_btn.clicked.connect(self._show_fullscreen_menu)
        layout.addWidget(fs_btn)

        return bar

    # ── edit mode ─────────────────────────────────────────────────────────────

    def _on_edit_toggled(self, checked: bool) -> None:
        self._edit_mode = checked
        self._edit_btn.setText("✏  Edit Layout" if checked else "👁  View Mode")
        for panel in self._panels.values():
            panel.set_edit_mode(checked)

    # ── add panel dialog ──────────────────────────────────────────────────────

    def _show_add_dialog(self) -> None:
        defs = self._registry.list_widgets()
        if not defs:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Add Panel")
        dlg.setMinimumWidth(340)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(12)

        lbl = QLabel("Choose a panel to add to the stage:")
        lbl.setObjectName("CardDescription")
        dlg_layout.addWidget(lbl)

        list_widget = QListWidget()
        list_widget.setObjectName("StagePickerList")
        for defn in defs:
            item = QListWidgetItem(f"{defn.icon}  {defn.title}")
            item.setData(Qt.UserRole, defn.panel_id)
            if defn.panel_id in self._panels:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setText(item.text() + "  (already on stage)")
            list_widget.addItem(item)
        dlg_layout.addWidget(list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        selected = list_widget.currentItem()
        if not selected or not (selected.flags() & Qt.ItemIsEnabled):
            return

        panel_id = selected.data(Qt.UserRole)
        self._add_panel(panel_id)

    # ── panel management ──────────────────────────────────────────────────────

    def _add_panel(self, panel_id: str, x: int | None = None, y: int | None = None,
                   w: int | None = None, h: int | None = None,
                   icon_text: str = "", icon_path: str = "") -> StagePanel | None:
        defn = self._registry.get(panel_id)
        if defn is None:
            logger.warning("Stage panel '%s' not found in registry", panel_id)
            return None

        try:
            content_widget = defn.factory()
        except Exception as exc:
            logger.error("Failed to create stage panel '%s': %s", panel_id, exc)
            return None

        _size_defaults = {
            "chat.live":   (460, 520),
            "chat.alerts": (420, 500),
            "bots.live":   (440, 500),
            "music.main":  (520, 300),
            "scene.main":  (360, 480),
            "timer.main":  (360, 320),
            "info.main":   (420, 580),
            "stats.main":  (380, 420),
        }
        dw, dh = _size_defaults.get(panel_id, (_DEFAULT_PANEL_W, 420))
        offset = len(self._panels) * 32
        px = x if x is not None else min(offset + 20, _CANVAS_W - dw - 20)
        py = y if y is not None else min(offset + 20, _CANVAS_H - dh - 20)
        pw = w if w is not None else dw
        ph = h if h is not None else dh

        panel = StagePanel(
            panel_id=panel_id,
            title=defn.title,
            content=content_widget,
            icon_text=icon_text,
            icon_path=icon_path,
            parent=self._canvas,
        )
        panel.set_edit_mode(self._edit_mode)
        panel.setGeometry(px, py, pw, ph)
        panel.close_requested.connect(self._remove_panel)
        panel.geometry_changed.connect(self._save_layout)
        panel.customize_requested.connect(self._on_customize_panel)
        panel.show()
        panel.raise_to_top()   # raise panel, then re-raise grips above it

        self._panels[panel_id] = panel
        self._save_layout()
        self.panel_added.emit(panel_id)
        return panel

    def _remove_panel(self, panel_id: str) -> None:
        panel = self._panels.pop(panel_id, None)
        if panel:
            panel.destroy_grips()
            panel.hide()
            panel.setParent(None)
            panel.deleteLater()
        self._save_layout()

    # ── layout persistence ────────────────────────────────────────────────────

    def _save_layout(self) -> None:
        self._layout_db.save([p.serialise() for p in self._panels.values()])

    def _restore_layout(self) -> None:
        for entry in self._layout_db.panels:
            pid = entry.get("id", "")
            self._add_panel(
                pid,
                x=entry.get("x"), y=entry.get("y"),
                w=entry.get("w"), h=entry.get("h"),
                icon_text=entry.get("icon_text", ""),
                icon_path=entry.get("icon_path", ""),
            )

    # ── named layout save / load / export / import ────────────────────────────

    def _current_panels_data(self) -> list[dict]:
        return [p.serialise() for p in self._panels.values()]

    def _save_named_layout(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save Layout", "Layout name:", text="My Layout"
        )
        if not ok or not name.strip():
            return
        self._layout_repo.save_layout(name.strip(), self._current_panels_data())
        QMessageBox.information(self, "Layout Saved", f"Layout '{name.strip()}' saved.")

    def _show_load_layout_dialog(self) -> None:
        layouts = self._layout_repo.list_layouts()

        dlg = QDialog(self)
        dlg.setWindowTitle("Layouts")
        dlg.setMinimumWidth(460)
        dlg.setMinimumHeight(340)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(12)

        lbl = QLabel("Saved layouts:")
        lbl.setObjectName("CardDescription")
        dlg_layout.addWidget(lbl)

        list_widget = QListWidget()
        list_widget.setObjectName("StagePickerList")
        for entry in layouts:
            item = QListWidgetItem(entry.name)
            item.setData(Qt.UserRole, entry.slug)
            list_widget.addItem(item)
        dlg_layout.addWidget(list_widget, 1)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.setObjectName("PrimaryButton")
        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("TimerDangerBtn")
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("StageToolbarBtn")
        import_btn = QPushButton("Import…")
        import_btn.setObjectName("StageToolbarBtn")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryButton")
        btn_row.addWidget(load_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addSpacing(12)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(import_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        dlg_layout.addLayout(btn_row)

        def _selected_entry():
            item = list_widget.currentItem()
            if not item:
                return None
            slug = item.data(Qt.UserRole)
            return next((e for e in layouts if e.slug == slug), None)

        def _on_load():
            entry = _selected_entry()
            if not entry:
                return
            panels = self._layout_repo.load_layout(entry.slug)
            if panels is None:
                QMessageBox.warning(dlg, "Error", "Could not load layout.")
                return
            self._apply_layout(panels)
            dlg.accept()

        def _on_delete():
            entry = _selected_entry()
            if not entry:
                return
            ans = QMessageBox.question(
                dlg, "Delete Layout",
                f"Delete '{entry.name}'?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
            self._layout_repo.delete_layout(entry.slug)
            row = list_widget.currentRow()
            list_widget.takeItem(row)
            layouts[:] = self._layout_repo.list_layouts()

        def _on_export():
            entry = _selected_entry()
            if not entry:
                QMessageBox.information(dlg, "Export", "Select a layout to export.")
                return
            dest, _ = QFileDialog.getSaveFileName(
                dlg, "Export Layout",
                str(Path.home() / f"{entry.name}.streamshift-layout.json"),
                "StreamShift Layout (*.json);;All Files (*)",
            )
            if not dest:
                return
            panels = self._layout_repo.load_layout(entry.slug) or []
            self._layout_repo.export_layout(entry.name, panels, Path(dest))
            QMessageBox.information(dlg, "Exported", f"Layout exported to:\n{dest}")

        def _on_import():
            src, _ = QFileDialog.getOpenFileName(
                dlg, "Import Layout", str(Path.home()),
                "StreamShift Layout (*.json);;All Files (*)",
            )
            if not src:
                return
            result = LayoutRepository.import_layout(Path(src))
            if result is None:
                QMessageBox.warning(dlg, "Import Failed", "Could not read the layout file.")
                return
            name, panels = result
            name, ok = QInputDialog.getText(
                dlg, "Import Layout", "Save imported layout as:", text=name
            )
            if not ok or not name.strip():
                return
            entry = self._layout_repo.save_layout(name.strip(), panels)
            item = QListWidgetItem(entry.name)
            item.setData(Qt.UserRole, entry.slug)
            list_widget.addItem(item)
            layouts.append(entry)
            ans = QMessageBox.question(
                dlg, "Apply Layout",
                f"Apply '{name.strip()}' to the stage now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self._apply_layout(panels)
                dlg.accept()

        load_btn.clicked.connect(_on_load)
        delete_btn.clicked.connect(_on_delete)
        export_btn.clicked.connect(_on_export)
        import_btn.clicked.connect(_on_import)
        cancel_btn.clicked.connect(dlg.reject)
        list_widget.itemDoubleClicked.connect(lambda _: _on_load())

        dlg.exec()

    def _apply_layout(self, panels: list[dict]) -> None:
        for panel_id in list(self._panels.keys()):
            self._remove_panel(panel_id)
        for entry in panels:
            pid = entry.get("id", "")
            self._add_panel(
                pid,
                x=entry.get("x"), y=entry.get("y"),
                w=entry.get("w"), h=entry.get("h"),
                icon_text=entry.get("icon_text", ""),
                icon_path=entry.get("icon_path", ""),
            )

    # ── customize dialog ──────────────────────────────────────────────────────

    def _on_customize_panel(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if not panel:
            return

        # Load current theme engine state for this panel
        try:
            from stream_controller.plugins.theme_manager import theme_engine
            from stream_controller.plugins.theme_manager.theme_models import PanelTheme
            _has_engine = True
        except ImportError:
            _has_engine = False

        current_pt = None
        if _has_engine:
            t = theme_engine.current_theme()
            if t:
                current_pt = t.panel_overrides.get(panel_id)

        current_accent = current_pt.accent if current_pt else "#7c3aed"
        current_icon_text = panel._icon_text
        current_icon_path = panel._icon_path

        # ── dialog ──
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Customize Panel")
        dlg.setMinimumWidth(500)
        dlg.setMinimumHeight(560)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(14)
        lay.setContentsMargins(20, 20, 20, 20)

        # ── Theme presets ──
        preset_hdr = QLabel("Panel Theme Preset")
        preset_hdr.setObjectName("CardTitle")
        lay.addWidget(preset_hdr)

        desc = QLabel(
            "Each preset changes the full panel look — background, border, accent stripe, and title bar color."
        )
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        selected_preset: list[tuple] = [None]   # mutable cell

        preset_scroll = QScrollArea()
        preset_scroll.setWidgetResizable(True)
        preset_scroll.setFixedHeight(220)
        preset_scroll.setFrameShape(QFrame.NoFrame)
        preset_inner = QWidget()
        preset_grid = QGridLayout(preset_inner)
        preset_grid.setSpacing(10)
        preset_grid.setContentsMargins(4, 4, 4, 4)
        preset_scroll.setWidget(preset_inner)
        lay.addWidget(preset_scroll)

        swatch_frames: list[QFrame] = []
        COLS = 4

        def _select_preset(idx: int) -> None:
            selected_preset[0] = _PRESET_THEMES[idx]
            for i, f in enumerate(swatch_frames):
                f.setProperty("selected", i == idx)
                f.style().unpolish(f)
                f.style().polish(f)
                # highlight selected with a bright border inline
                accent = _PRESET_THEMES[i][1]
                border = "3px solid #ffffff" if i == idx else f"2px solid {accent}44"
                f.setStyleSheet(f"QFrame {{ border-radius:10px; border:{border}; background:{_PRESET_THEMES[i][2] or '#0f0f18'}; }}")

        for idx, (name, accent, bg, border) in enumerate(_PRESET_THEMES):
            frame = QFrame()
            frame.setFixedSize(104, 80)
            frame.setStyleSheet(
                f"QFrame {{ border-radius:10px; border:2px solid {accent}44; background:{bg or '#0f0f18'}; }}"
            )
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(0, 6, 0, 4)
            fl.setSpacing(3)

            # Mini accent stripe
            stripe = QFrame()
            stripe.setFixedHeight(5)
            stripe.setStyleSheet(f"background:{accent}; border-radius:3px;")
            fl.addWidget(stripe)
            fl.addStretch(1)

            # Name label — visible text for colorblind accessibility
            name_lbl = QLabel(name)
            name_lbl.setAlignment(Qt.AlignCenter)
            name_lbl.setStyleSheet("color:#d0d8f0; font-size:10px; font-weight:600;")
            name_lbl.setWordWrap(True)
            fl.addWidget(name_lbl)

            # Mark current selection
            if accent == current_accent:
                selected_preset[0] = (name, accent, bg, border)

            frame.mousePressEvent = lambda e, i=idx: _select_preset(i)
            swatch_frames.append(frame)
            preset_grid.addWidget(frame, idx // COLS, idx % COLS)

        # Apply initial highlight
        for i, f in enumerate(swatch_frames):
            if selected_preset[0] and _PRESET_THEMES[i][1] == current_accent:
                accent = _PRESET_THEMES[i][1]
                f.setStyleSheet(f"QFrame {{ border-radius:10px; border:3px solid #ffffff; background:{_PRESET_THEMES[i][2] or '#0f0f18'}; }}")

        # ── Icon section ──
        icon_hdr = QLabel("Panel Icon")
        icon_hdr.setObjectName("CardTitle")
        lay.addWidget(icon_hdr)

        # Row 1: emoji
        emoji_row = QHBoxLayout()
        emoji_row.setSpacing(10)
        emoji_row.addWidget(QLabel("Emoji:"))
        emoji_input = QLineEdit(current_icon_text)
        emoji_input.setObjectName("ChatSendInput")
        emoji_input.setPlaceholderText("e.g. 🤖  📡  🎮  🎵  ⏱")
        emoji_input.setMaxLength(8)
        emoji_row.addWidget(emoji_input, 1)
        lay.addLayout(emoji_row)

        # Row 2: image upload
        chosen_image_path: list[str] = [current_icon_path]

        img_path_lbl = QLabel()
        img_path_lbl.setObjectName("MetaText")

        def _update_img_label() -> None:
            p = chosen_image_path[0]
            img_path_lbl.setText(Path(p).name if (p and Path(p).exists()) else "No image selected")

        _update_img_label()

        def _browse_image() -> None:
            path, _ = QFileDialog.getOpenFileName(
                dlg, "Choose Icon Image", str(Path.home()),
                "Images (*.png *.svg *.jpg *.jpeg *.bmp *.gif)"
            )
            if path:
                chosen_image_path[0] = path
                _update_img_label()
                emoji_input.clear()

        def _clear_image() -> None:
            chosen_image_path[0] = ""
            _update_img_label()

        img_row = QHBoxLayout()
        img_row.setSpacing(10)
        img_row.addWidget(QLabel("Image:"))
        browse_btn = QPushButton("Browse…")
        browse_btn.setMinimumWidth(80)
        browse_btn.clicked.connect(_browse_image)
        img_row.addWidget(browse_btn)
        img_row.addWidget(img_path_lbl, 1)
        clear_img_btn = QPushButton("Clear")
        clear_img_btn.setMinimumWidth(60)
        clear_img_btn.clicked.connect(_clear_image)
        img_row.addWidget(clear_img_btn)
        lay.addLayout(img_row)

        # ── Buttons ──
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        # ── Apply ──
        preset = selected_preset[0]
        accent = preset[1] if preset else "#7c3aed"
        bg     = preset[2] if preset else ""
        border = preset[3] if preset else ""

        # Copy uploaded image into managed folder so it survives moves
        final_icon_path = ""
        raw_path = chosen_image_path[0]
        if raw_path and Path(raw_path).exists():
            _ICONS_DIR.mkdir(parents=True, exist_ok=True)
            dest = _ICONS_DIR / Path(raw_path).name
            if Path(raw_path).resolve() != dest.resolve():
                shutil.copy2(raw_path, dest)
            final_icon_path = str(dest)

        final_icon_text = "" if final_icon_path else emoji_input.text().strip()

        panel.update_icon(final_icon_text, final_icon_path)

        if _has_engine:
            pt = PanelTheme(
                panel_id=panel_id,
                accent=accent,
                bg=bg,
                border=border,
            )
            pt.icon_text = final_icon_text
            pt.icon_path = final_icon_path
            theme_engine.save_panel_theme(panel_id, pt)
            theme_engine.apply_panel_theme(panel, pt)

        self._save_layout()

    # ── fullscreen ────────────────────────────────────────────────────────────

    def _show_fullscreen_menu(self) -> None:
        screens = QApplication.screens()
        if len(screens) == 1:
            self._launch_fullscreen(0)
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Choose Screen")
        dlg.setMinimumWidth(320)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Select a screen for the fullscreen stage:"))

        list_widget = QListWidget()
        list_widget.setObjectName("StagePickerList")
        for i, screen in enumerate(screens):
            g = screen.geometry()
            label = f"Screen {i + 1} — {g.width()}×{g.height()}"
            if screen == QApplication.primaryScreen():
                label += "  (primary)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            list_widget.addItem(item)
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        selected = list_widget.currentItem()
        if selected:
            self._launch_fullscreen(selected.data(Qt.UserRole))

    def _launch_fullscreen(self, screen_index: int) -> None:
        if self._fullscreen_window:
            self._exit_fullscreen()

        screens = QApplication.screens()
        if screen_index >= len(screens):
            screen_index = 0

        win = QWidget()
        win.setObjectName("StageFullscreenWindow")
        win.setWindowTitle("Stage View — StreamShift")
        win.setAttribute(Qt.WA_DeleteOnClose, False)
        win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        win_layout = QVBoxLayout(win)
        win_layout.setContentsMargins(0, 0, 0, 0)

        fs_bar = QWidget()
        fs_bar.setObjectName("StageToolbar")
        fs_bar.setFixedHeight(40)
        fs_bar_layout = QHBoxLayout(fs_bar)
        fs_bar_layout.setContentsMargins(12, 0, 12, 0)
        exit_btn = QPushButton("✕  Exit Fullscreen")
        exit_btn.setObjectName("StagePrimaryBtn")
        exit_btn.clicked.connect(self._exit_fullscreen)

        edit_btn_fs = QPushButton("✏  Edit")
        edit_btn_fs.setObjectName("StageToolbarBtn")
        edit_btn_fs.setCheckable(True)
        edit_btn_fs.setChecked(self._edit_mode)
        edit_btn_fs.toggled.connect(self._on_edit_toggled)

        fs_bar_layout.addWidget(QLabel("⚡  Stage View"))
        fs_bar_layout.addStretch(1)
        fs_bar_layout.addWidget(edit_btn_fs)
        fs_bar_layout.addWidget(exit_btn)
        win_layout.addWidget(fs_bar)

        self._scroll.setParent(None)
        win_layout.addWidget(self._scroll, 1)

        self._fullscreen_window = win
        target_screen = screens[screen_index]
        win.windowHandle()
        win.show()
        win.windowHandle().setScreen(target_screen)
        win.setGeometry(target_screen.geometry())
        win.showFullScreen()

        QShortcut(QKeySequence("Escape"), win).activated.connect(self._exit_fullscreen)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Ensure the scroll area is always visible when this page is shown.
        # It can be hidden by Qt when reparented during fullscreen mode.
        if not self._scroll.isVisible():
            self._scroll.show()
            self.layout().activate()
        # Re-position all grips — they can end up misplaced when the app
        # loses and regains focus (e.g. a browser tab opened momentarily).
        for panel in self._panels.values():
            panel.raise_to_top()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            for panel in self._panels.values():
                panel.raise_to_top()

    def _exit_fullscreen(self) -> None:
        if not self._fullscreen_window:
            return

        fw = self._fullscreen_window
        self._fullscreen_window = None  # clear first to prevent re-entry

        # Re-parent the scroll area back into this page's layout.
        # setParent() hides the widget in Qt when moving to a different hierarchy,
        # so we must explicitly show it after and force the layout to reactivate.
        self._scroll.setParent(self)
        # Remove any duplicate references then insert at position 1 (after toolbar)
        self.layout().insertWidget(1, self._scroll, 1)
        self._scroll.show()
        self.layout().activate()

        fw.hide()
        fw.deleteLater()
