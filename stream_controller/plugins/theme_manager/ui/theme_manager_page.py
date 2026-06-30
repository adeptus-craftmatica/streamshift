from __future__ import annotations

import copy
import uuid
from typing import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from stream_controller.plugins.theme_manager.theme_models import (
    BUILTIN_THEMES, AppTheme, PanelTheme,
)
from stream_controller.plugins.theme_manager.theme_repository import ThemeRepository
from stream_controller.plugins.theme_manager import theme_engine
from stream_controller.plugins.theme_manager.ui.color_row import ColorRow
from stream_controller.plugins.theme_manager.ui.theme_preview import ThemePreview
from stream_controller.plugins.theme_manager.ui.theme_generator import ThemeGeneratorPanel


# ── colour group definitions ─────────────────────────────────────────────────

_COLOR_GROUPS = [
    {
        "title": "Backgrounds",
        "desc": "The layered dark backgrounds that form the app's depth.",
        "fields": [
            ("bg_base",     "Deepest Background"),
            ("bg_primary",  "Main Window"),
            ("bg_sidebar",  "Sidebar"),
            ("bg_card",     "Cards & Panels"),
            ("bg_elevated", "Elevated Surfaces"),
            ("bg_input",    "Input Fields"),
        ],
    },
    {
        "title": "Accent / Brand",
        "desc": "The primary color used for buttons, active states, and highlights.",
        "fields": [
            ("accent", "Accent Color"),
        ],
    },
    {
        "title": "Text",
        "desc": "Text colors across the UI.",
        "fields": [
            ("text_primary",   "Primary Text"),
            ("text_secondary", "Secondary / Muted Text"),
            ("text_muted",     "Very Muted Text"),
        ],
    },
    {
        "title": "Borders",
        "desc": "Borders between panels, cards, and UI sections.",
        "fields": [
            ("border", "Border Color"),
        ],
    },
    {
        "title": "Status Colors",
        "desc": "Colors used for success, warning, error, and info states.",
        "fields": [
            ("success", "Success (Green)"),
            ("warning", "Warning (Yellow)"),
            ("error",   "Error (Red)"),
            ("info",    "Info (Blue)"),
        ],
    },
]

_PANEL_LABELS = {
    "scene.main":              ("🎬", "Scene Manager"),
    "music.main":              ("🎵", "Music Player"),
    "chat.live":               ("💬", "Live Chat"),
    "chat.alerts":             ("🔔", "Alerts"),
    "bots.live":               ("🤖", "Bot Activity"),
    "timer.main":              ("⏱", "Timer"),
    "info.main":               ("📋", "Stream Info"),
    "stats.main":              ("📊", "Stream Stats"),
    "stream_health.main":      ("❤️", "Stream Health"),
    "pngtuber.main":           ("🖼️", "PNGtuber"),
    "redemption_tracker.queue":("🎁", "Redemptions"),
    "quick_connect.tile":      ("⚡", "Quick Connect"),
}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

class ThemeManagerPage(QWidget):
    def __init__(self, repo: ThemeRepository) -> None:
        super().__init__()
        self._repo = repo
        self._editing: AppTheme | None = None   # theme being edited (copy)
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(120)       # debounce live preview
        self._apply_timer.timeout.connect(self._apply_current)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left: theme list
        left = self._build_left_panel()
        left.setFixedWidth(230)
        root.addWidget(left)

        _vsep = QFrame(); _vsep.setFrameShape(QFrame.VLine); _vsep.setObjectName("Separator")
        root.addWidget(_vsep)

        # Center: color editor + preview
        center = self._build_center_panel()
        root.addWidget(center, 1)

        _vsep2 = QFrame(); _vsep2.setFrameShape(QFrame.VLine); _vsep2.setObjectName("Separator")
        root.addWidget(_vsep2)

        # Right: stage panel overrides
        right = self._build_right_panel()
        right.setFixedWidth(280)
        root.addWidget(right)

        self._refresh_theme_list()

    # ══════════════════════════════════════════════════════════════════════════
    # LEFT PANEL — theme list
    # ══════════════════════════════════════════════════════════════════════════

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("SidebarPanel")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        header = QWidget(); header.setObjectName("SidebarHeader")
        hl = QHBoxLayout(header); hl.setContentsMargins(14, 12, 14, 12)
        lbl = QLabel("Themes"); lbl.setObjectName("CardTitle")
        hl.addWidget(lbl, 1)
        vl.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        # Tab widget — Built-In / Custom
        self._theme_tabs = QTabWidget()
        self._theme_tabs.setObjectName("SidebarTabs")
        self._theme_tabs.setDocumentMode(True)

        self._builtin_list = QListWidget()
        self._builtin_list.setObjectName("SidebarList")
        self._builtin_list.setFrameShape(QFrame.NoFrame)
        self._builtin_list.currentItemChanged.connect(
            lambda c, p: self._on_tab_selection(c, self._builtin_list, self._custom_list))

        self._custom_list = QListWidget()
        self._custom_list.setObjectName("SidebarList")
        self._custom_list.setFrameShape(QFrame.NoFrame)
        self._custom_list.currentItemChanged.connect(
            lambda c, p: self._on_tab_selection(c, self._custom_list, self._builtin_list))

        self._theme_tabs.addTab(self._builtin_list, "Built-In")
        self._theme_tabs.addTab(self._custom_list, "Custom")
        vl.addWidget(self._theme_tabs, 1)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        vl.addWidget(sep2)

        btn_row = QVBoxLayout(); btn_row.setContentsMargins(10, 10, 10, 10); btn_row.setSpacing(6)
        new_btn = QPushButton("＋ New Theme"); new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._new_theme)
        dup_btn = QPushButton("Duplicate Selected"); dup_btn.setObjectName("SecondaryButton")
        dup_btn.clicked.connect(self._duplicate_theme)
        del_btn = QPushButton("Delete"); del_btn.setObjectName("SecondaryButton")
        del_btn.clicked.connect(self._delete_theme)
        btn_row.addWidget(new_btn); btn_row.addWidget(dup_btn); btn_row.addWidget(del_btn)
        vl.addLayout(btn_row)
        return panel

    def _on_tab_selection(self, item: QListWidgetItem | None,
                          active_list: QListWidget,
                          other_list: QListWidget) -> None:
        """Clear selection on the other list then dispatch to the normal handler."""
        if item is None:
            return
        other_list.blockSignals(True)
        other_list.clearSelection()
        other_list.setCurrentItem(None)
        other_list.blockSignals(False)
        self._on_theme_selected(item)

    # ══════════════════════════════════════════════════════════════════════════
    # CENTER PANEL — editor + preview  /  generator (stacked)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Single unified toolbar ────────────────────────────────────────────
        # Layout: [Edit pill][Generate pill]  |  theme name (flex)  |  [Rename][Apply]
        top = QWidget(); top.setObjectName("SidebarHeader")
        tl = QHBoxLayout(top); tl.setContentsMargins(12, 8, 12, 8); tl.setSpacing(6)

        # Mode pills — fixed left
        self._mode_edit_btn = QPushButton("Edit")
        self._mode_edit_btn.setObjectName("ModePill")
        self._mode_edit_btn.setCheckable(True)
        self._mode_edit_btn.setChecked(True)
        self._mode_edit_btn.setFixedHeight(28)
        self._mode_edit_btn.clicked.connect(lambda: self._set_center_mode(0))

        self._mode_gen_btn = QPushButton("✦ Generate")
        self._mode_gen_btn.setObjectName("ModePill")
        self._mode_gen_btn.setCheckable(True)
        self._mode_gen_btn.setFixedHeight(28)
        self._mode_gen_btn.clicked.connect(lambda: self._set_center_mode(1))

        tl.addWidget(self._mode_edit_btn)
        tl.addWidget(self._mode_gen_btn)

        # Vertical divider
        div = QFrame(); div.setFrameShape(QFrame.VLine)
        div.setObjectName("Separator"); div.setFixedHeight(20)
        tl.addWidget(div)

        # Theme name — stretches to fill space, elides if needed
        self._theme_name_lbl = QLabel("Select a theme")
        self._theme_name_lbl.setObjectName("CardTitle")
        self._theme_name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tl.addWidget(self._theme_name_lbl, 1)

        # Action buttons — fixed right
        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("SecondaryButton")
        rename_btn.setFixedHeight(28)
        rename_btn.setToolTip("Rename this theme")
        rename_btn.clicked.connect(self._rename_theme)

        self._apply_btn = QPushButton("⚡ Apply")
        self._apply_btn.setObjectName("PrimaryButton")
        self._apply_btn.setFixedHeight(28)
        self._apply_btn.clicked.connect(self._apply_and_save)
        self._apply_btn.setEnabled(False)

        tl.addWidget(rename_btn)
        tl.addWidget(self._apply_btn)
        vl.addWidget(top)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        # ── Stacked widget ───────────────────────────────────────────────────
        self._center_stack = QStackedWidget()
        vl.addWidget(self._center_stack, 1)

        # Page 0: editor
        editor_page = QWidget()
        ep_vl = QVBoxLayout(editor_page)
        ep_vl.setContentsMargins(0, 0, 0, 0)
        ep_vl.setSpacing(0)

        self._preview = ThemePreview()
        self._preview.setContentsMargins(16, 16, 16, 0)
        ep_vl.addWidget(self._preview)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setObjectName("Separator")
        ep_vl.addWidget(sep2)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self._editor_layout = QVBoxLayout(content)
        self._editor_layout.setContentsMargins(16, 16, 16, 24)
        self._editor_layout.setSpacing(20)
        self._editor_layout.addStretch(1)
        scroll.setWidget(content)
        ep_vl.addWidget(scroll, 1)

        self._color_rows: dict[str, ColorRow] = {}
        self._center_stack.addWidget(editor_page)      # index 0

        # Page 1: generator
        self._generator = ThemeGeneratorPanel()
        self._generator.theme_ready.connect(self._on_theme_generated)
        self._center_stack.addWidget(self._generator)  # index 1

        return panel

    def _set_center_mode(self, index: int) -> None:
        self._center_stack.setCurrentIndex(index)
        self._mode_edit_btn.setChecked(index == 0)
        self._mode_gen_btn.setChecked(index == 1)
        # Apply/Rename only make sense in Edit mode
        self._apply_btn.setVisible(index == 0)

    def _build_color_groups(self, theme: AppTheme) -> None:
        # Clear old rows
        while self._editor_layout.count() > 1:
            item = self._editor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._color_rows.clear()

        for group in _COLOR_GROUPS:
            card, body = _make_editor_card(group["title"], group["desc"])
            for field, label in group["fields"]:
                row = ColorRow(label, getattr(theme, field, "000000"))
                row.changed.connect(lambda h, f=field: self._on_color_changed(f, h))
                body.addWidget(row)
                self._color_rows[field] = row
            self._editor_layout.insertWidget(self._editor_layout.count() - 1, card)

    def _refresh_color_rows(self, theme: AppTheme) -> None:
        for field, row in self._color_rows.items():
            val = getattr(theme, field, "000000")
            row.set_value(val)

    # ══════════════════════════════════════════════════════════════════════════
    # RIGHT PANEL — per-panel overrides
    # ══════════════════════════════════════════════════════════════════════════

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(); panel.setObjectName("SidebarPanel")
        vl = QVBoxLayout(panel); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(0)

        header = QWidget(); header.setObjectName("SidebarHeader")
        hl = QHBoxLayout(header); hl.setContentsMargins(14, 12, 14, 12)
        lbl = QLabel("Stage Panels"); lbl.setObjectName("CardTitle")
        hint = QLabel("Color each panel differently"); hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        hl.addWidget(lbl, 1)
        vl.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
        vl.addWidget(sep)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self._panel_editor_layout = QVBoxLayout(content)
        self._panel_editor_layout.setContentsMargins(12, 12, 12, 12)
        self._panel_editor_layout.setSpacing(12)

        hint2 = QLabel(
            "Each stage panel can have its own accent color, background, "
            "and title bar gradient — making it easy to tell panels apart at a glance."
        )
        hint2.setObjectName("CardDescription")
        hint2.setWordWrap(True)
        self._panel_editor_layout.addWidget(hint2)

        self._panel_widgets: dict[str, _PanelColorCard] = {}
        for panel_id, (icon, label) in _PANEL_LABELS.items():
            card = _PanelColorCard(panel_id, icon, label, on_changed=self._on_panel_color_changed)
            self._panel_widgets[panel_id] = card
            self._panel_editor_layout.addWidget(card)

        reset_btn = QPushButton("Reset All Panels to Default")
        reset_btn.setObjectName("SecondaryButton")
        reset_btn.clicked.connect(self._reset_panel_overrides)
        self._panel_editor_layout.addWidget(reset_btn)
        self._panel_editor_layout.addStretch(1)

        scroll.setWidget(content)
        vl.addWidget(scroll, 1)
        return panel

    # ══════════════════════════════════════════════════════════════════════════
    # EVENTS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme_selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        theme_id = item.data(Qt.UserRole)
        theme = self._repo.get(theme_id)
        if theme is None:
            return
        # Work on a deep copy so edits don't affect the stored theme until Apply
        self._editing = copy.deepcopy(theme)
        self._theme_name_lbl.setText(theme.name)
        self._apply_btn.setEnabled(True)

        # Rebuild color rows if not yet built
        if not self._color_rows:
            self._build_color_groups(self._editing)
        else:
            self._refresh_color_rows(self._editing)

        # Load panel overrides
        overrides_raw = self._repo.get_panel_overrides_for_active()
        theme_overrides = {k: PanelTheme.from_dict(v) for k, v in overrides_raw.items()}
        # Also include overrides stored on the theme itself
        if hasattr(theme, "panel_overrides"):
            for k, v in theme.panel_overrides.items():
                if k not in theme_overrides:
                    theme_overrides[k] = v
        for pid, card in self._panel_widgets.items():
            card.load(theme_overrides.get(pid))

        self._preview.set_theme(self._editing)

    def _on_color_changed(self, field: str, hex_val: str) -> None:
        if self._editing is None:
            return
        setattr(self._editing, field, f"#{hex_val}")
        self._preview.set_theme(self._editing)
        self._apply_timer.start()

    def _on_panel_color_changed(self, panel_id: str, pt: PanelTheme) -> None:
        if self._editing is not None:
            self._editing.panel_overrides[panel_id] = pt
        # Apply immediately to live panels
        from stream_controller.ui.stage_view.stage_panel import StagePanel
        from PySide6.QtWidgets import QApplication
        for widget in QApplication.allWidgets():
            if isinstance(widget, StagePanel) and widget.panel_id == panel_id:
                theme_engine.apply_panel_theme(widget, pt)

    def _apply_current(self) -> None:
        """Debounced live update while editing."""
        if self._editing:
            theme_engine.apply_theme(self._editing)

    def _apply_and_save(self) -> None:
        if self._editing is None:
            return
        theme_engine.apply_theme(self._editing)
        self._repo.set_active_theme_id(self._editing.theme_id)
        if not self._editing.builtin:
            self._repo.save_custom(self._editing)
        # Save panel overrides
        for pid, card in self._panel_widgets.items():
            pt = card.current_panel_theme()
            if pt is not None:
                self._repo.save_panel_override_to_active(pid, pt)
        self._show_toast("Theme applied and saved.")

    # ── theme list management ─────────────────────────────────────────────────

    def _refresh_theme_list(self) -> None:
        active_id = self._repo.get_active_theme_id()
        active_is_custom = False

        self._builtin_list.blockSignals(True)
        self._builtin_list.clear()
        for t in BUILTIN_THEMES:
            item = QListWidgetItem(f"  {t.name}")
            item.setData(Qt.UserRole, t.theme_id)
            self._builtin_list.addItem(item)
            if t.theme_id == active_id:
                self._builtin_list.setCurrentItem(item)
        self._builtin_list.blockSignals(False)

        self._custom_list.blockSignals(True)
        self._custom_list.clear()
        for t in self._repo.list_custom():
            item = QListWidgetItem(f"  ✦ {t.name}")
            item.setData(Qt.UserRole, t.theme_id)
            self._custom_list.addItem(item)
            if t.theme_id == active_id:
                self._custom_list.setCurrentItem(item)
                active_is_custom = True
        self._custom_list.blockSignals(False)

        # Switch to the tab that owns the active theme
        if active_is_custom:
            self._theme_tabs.setCurrentIndex(1)
        else:
            self._theme_tabs.setCurrentIndex(0)

        # Fall back to first built-in if nothing matched
        if not self._builtin_list.currentItem() and not self._custom_list.currentItem():
            if self._builtin_list.count():
                self._builtin_list.setCurrentRow(0)

    def _new_theme(self) -> None:
        name, ok = QInputDialog.getText(self, "New Theme", "Theme name:", text="My Theme")
        if not ok or not name.strip():
            return
        base = self._editing if self._editing else BUILTIN_THEMES[0]
        new = copy.deepcopy(base)
        new.theme_id = str(uuid.uuid4())
        new.name = name.strip()
        new.builtin = False
        self._repo.save_custom(new)
        self._refresh_theme_list()
        # Switch to Custom tab and select the new theme
        self._theme_tabs.setCurrentIndex(1)
        for i in range(self._custom_list.count()):
            if self._custom_list.item(i).data(Qt.UserRole) == new.theme_id:
                self._custom_list.setCurrentRow(i)
                break

    def _duplicate_theme(self) -> None:
        if self._editing is None:
            return
        dup = copy.deepcopy(self._editing)
        dup.theme_id = str(uuid.uuid4())
        dup.name = f"{dup.name} (copy)"
        dup.builtin = False
        self._repo.save_custom(dup)
        self._refresh_theme_list()

    def _delete_theme(self) -> None:
        item = self._custom_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Delete Theme", "Only custom themes can be deleted.")
            return
        theme_id = item.data(Qt.UserRole)
        t = self._repo.get(theme_id)
        if t and t.builtin:
            QMessageBox.information(self, "Delete Theme", "Built-in themes cannot be deleted.")
            return
        btn = QMessageBox.question(self, "Delete Theme",
                                   f"Delete '{t.name if t else theme_id}'?",
                                   QMessageBox.Yes | QMessageBox.Cancel)
        if btn == QMessageBox.Yes:
            self._repo.delete_custom(theme_id)
            if self._editing and self._editing.theme_id == theme_id:
                self._editing = None
                self._apply_btn.setEnabled(False)
            self._refresh_theme_list()

    def _on_theme_generated(self, theme) -> None:
        """Receive a theme from the generator, save it, and select it."""
        self._repo.save_custom(theme)
        self._refresh_theme_list()
        # Switch to Custom tab and select the new theme
        self._theme_tabs.setCurrentIndex(1)
        for i in range(self._custom_list.count()):
            if self._custom_list.item(i).data(Qt.UserRole) == theme.theme_id:
                self._custom_list.setCurrentRow(i)
                break
        # Return to Edit mode so user can fine-tune
        self._set_center_mode(0)
        self._show_toast(f"'{theme.name}' saved to Custom themes.")

    def _rename_theme(self) -> None:
        if self._editing is None:
            return
        if self._editing.builtin:
            QMessageBox.information(self, "Rename", "Duplicate a built-in theme first to rename it.")
            return
        name, ok = QInputDialog.getText(self, "Rename Theme", "New name:", text=self._editing.name)
        if ok and name.strip():
            self._editing.name = name.strip()
            self._theme_name_lbl.setText(self._editing.name)
            self._repo.save_custom(self._editing)
            self._refresh_theme_list()

    def _reset_panel_overrides(self) -> None:
        for card in self._panel_widgets.values():
            card.reset()
        from stream_controller.ui.stage_view.stage_panel import StagePanel
        from PySide6.QtWidgets import QApplication
        for widget in QApplication.allWidgets():
            if isinstance(widget, StagePanel):
                theme_engine.apply_panel_theme(widget, None)

    def _show_toast(self, msg: str) -> None:
        self._theme_name_lbl.setText(f"✓  {msg}")
        QTimer.singleShot(2500, lambda: self._theme_name_lbl.setText(
            self._editing.name if self._editing else ""))


# ══════════════════════════════════════════════════════════════════════════════
# PER-PANEL COLOR CARD
# ══════════════════════════════════════════════════════════════════════════════

class _PanelColorCard(QFrame):
    def __init__(self, panel_id: str, icon: str, label: str,
                 on_changed: Callable[[str, PanelTheme], None]) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._panel_id = panel_id
        self._on_changed = on_changed
        self._enabled = False
        self._pt: PanelTheme | None = None

        vl = QVBoxLayout(self); vl.setContentsMargins(12, 10, 12, 10); vl.setSpacing(8)

        # Header row
        hl = QHBoxLayout(); hl.setSpacing(8)
        icon_lbl = QLabel(icon); icon_lbl.setObjectName("CardTitle")
        name_lbl = QLabel(label); name_lbl.setObjectName("CardTitle")
        hl.addWidget(icon_lbl); hl.addWidget(name_lbl, 1)

        from PySide6.QtWidgets import QCheckBox
        self._toggle = QCheckBox("Custom")
        self._toggle.setObjectName("OverlayCheckBox")
        self._toggle.toggled.connect(self._on_toggle)
        hl.addWidget(self._toggle)
        vl.addLayout(hl)

        # Color rows (hidden when toggle is off)
        self._color_area = QWidget()
        cl = QVBoxLayout(self._color_area); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(4)

        self._accent_row = ColorRow("Accent Color", "7c3aed")
        self._bg_row = ColorRow("Background", "121a23")
        self._grad_start_row = ColorRow("Title Gradient Start", "4c1d95")
        self._grad_end_row = ColorRow("Title Gradient End", "6d28d9")
        self._border_row = ColorRow("Border Color", "1f2c38")

        for row in (self._accent_row, self._bg_row, self._grad_start_row,
                    self._grad_end_row, self._border_row):
            row.changed.connect(self._emit_change)
            cl.addWidget(row)

        vl.addWidget(self._color_area)
        self._color_area.setVisible(False)

    def load(self, pt: PanelTheme | None) -> None:
        self._pt = pt
        self._toggle.blockSignals(True)
        self._toggle.setChecked(pt is not None)
        self._toggle.blockSignals(False)
        self._color_area.setVisible(pt is not None)
        if pt:
            self._accent_row.set_value(pt.accent or "7c3aed")
            self._bg_row.set_value(pt.bg or "121a23")
            self._grad_start_row.set_value(pt.title_gradient_start or "4c1d95")
            self._grad_end_row.set_value(pt.title_gradient_end or "6d28d9")
            self._border_row.set_value(pt.border or "1f2c38")

    def reset(self) -> None:
        self.load(None)

    def current_panel_theme(self) -> PanelTheme | None:
        if not self._toggle.isChecked():
            return None
        return PanelTheme(
            panel_id=self._panel_id,
            accent=f"#{self._accent_row.hex_value()}",
            bg=f"#{self._bg_row.hex_value()}",
            title_gradient_start=f"#{self._grad_start_row.hex_value()}",
            title_gradient_end=f"#{self._grad_end_row.hex_value()}",
            border=f"#{self._border_row.hex_value()}",
        )

    def _on_toggle(self, checked: bool) -> None:
        self._color_area.setVisible(checked)
        self._emit_change()

    def _emit_change(self) -> None:
        pt = self.current_panel_theme()
        self._on_changed(self._panel_id, pt)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_editor_card(title: str, desc: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame(); card.setObjectName("Card")
    vl = QVBoxLayout(card); vl.setContentsMargins(16, 14, 16, 16); vl.setSpacing(10)
    title_lbl = QLabel(title); title_lbl.setObjectName("CardTitle")
    desc_lbl = QLabel(desc); desc_lbl.setObjectName("CardDescription"); desc_lbl.setWordWrap(True)
    vl.addWidget(title_lbl); vl.addWidget(desc_lbl)
    sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("Separator")
    vl.addWidget(sep)
    body = QVBoxLayout(); body.setSpacing(6)
    vl.addLayout(body)
    return card, body
