from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext
    from stream_controller.plugins.redemption_tracker.redemption_client import RedemptionClient
    from stream_controller.plugins.redemption_tracker.redemption_store import RedemptionStore
    from stream_controller.plugins.redemption_tracker.reward_actions import RewardActionMapping

from stream_controller.plugins.redemption_tracker.ui.redemption_panel import RedemptionPanel


class RedemptionPage(QWidget):
    """Full plugin page — settings, reward action mappings, and live queue."""

    fulfil_setting_changed = Signal(bool)

    def __init__(
        self,
        store: "RedemptionStore",
        client: "RedemptionClient",
        mappings: "RewardActionMapping",
        app_context: "AppContext",
    ) -> None:
        super().__init__()
        self._store       = store
        self._client      = client
        self._mappings    = mappings
        self._app_context = app_context

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        title = QLabel("Redemption Tracker")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        desc = QLabel(
            "Tracks channel point redemptions and bit cheers in real time. "
            "Map reward names to actions so redemptions trigger things automatically."
        )
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        root.addWidget(desc)

        tabs = QTabWidget()
        tabs.addTab(self._build_queue_tab(), "Live Queue")
        tabs.addTab(self._build_actions_tab(), "Reward Actions")
        tabs.addTab(self._build_settings_tab(), "Settings")
        root.addWidget(tabs, 1)

    # ── Live Queue tab ────────────────────────────────────────────────────────

    def _build_queue_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 8, 0, 0)
        vl.setSpacing(8)

        self._status_lbl = QLabel("Waiting for Twitch connection…")
        self._status_lbl.setObjectName("MetaText")
        self._status_lbl.setWordWrap(True)
        vl.addWidget(self._status_lbl)

        panel = RedemptionPanel(self._store, self._client, fulfil_on_complete=True)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._panel = panel
        vl.addWidget(panel, 1)
        return w

    # ── Reward Actions tab ────────────────────────────────────────────────────

    def _build_actions_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 12, 0, 0)
        vl.setSpacing(12)

        info = QLabel(
            "Map a channel point reward name to any StreamShift action. "
            "When a viewer redeems that reward, the action fires instantly.\n\n"
            'Reward name matching is case-insensitive. Example: map '
            '"Random Song" -> Play Random Song.'
        )
        info.setObjectName("CardDescription")
        info.setWordWrap(True)
        vl.addWidget(info)

        # Scroll area holding mapping rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._mappings_container = QWidget()
        self._mappings_layout = QVBoxLayout(self._mappings_container)
        self._mappings_layout.setContentsMargins(0, 0, 0, 0)
        self._mappings_layout.setSpacing(6)
        self._mappings_layout.addStretch(1)
        scroll.setWidget(self._mappings_container)
        vl.addWidget(scroll, 1)

        # Add mapping button
        add_btn = QPushButton("+ Add Reward Action")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_mapping_row)
        vl.addWidget(add_btn)

        # Populate existing mappings
        for reward_name, action_id in self._mappings.all_mappings():
            self._insert_row(reward_name, action_id)

        return w

    def _available_actions(self) -> list[tuple[str, str]]:
        """Return (display_label, action_id) sorted by label."""
        actions = self._app_context.action_registry.list_actions()
        return [(f"{a.title}  [{a.group}]", a.action_id) for a in actions]

    def _add_mapping_row(self, reward_name: str = "", action_id: str = "") -> None:
        self._insert_row(reward_name, action_id)

    def _insert_row(self, reward_name: str = "", action_id: str = "") -> None:
        layout = self._mappings_layout
        row_widget = QFrame()
        row_widget.setObjectName("CardFrame")
        row_widget.setStyleSheet(
            "QFrame#CardFrame { border-radius:8px; background:rgba(255,255,255,0.04);"
            "border:1px solid rgba(255,255,255,0.08); padding:2px; }"
        )
        hl = QHBoxLayout(row_widget)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(8)

        reward_edit = QLineEdit()
        reward_edit.setPlaceholderText("Reward name (e.g. Random Song)")
        reward_edit.setText(reward_name)
        reward_edit.setFixedWidth(200)
        hl.addWidget(reward_edit)

        arrow = QLabel("→")
        arrow.setObjectName("MetaText")
        hl.addWidget(arrow)

        action_combo = QComboBox()
        action_combo.addItem("— select action —", "")
        for label, aid in self._available_actions():
            action_combo.addItem(label, aid)
        if action_id:
            for i in range(action_combo.count()):
                if action_combo.itemData(i) == action_id:
                    action_combo.setCurrentIndex(i)
                    break
        hl.addWidget(action_combo, 1)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setFixedWidth(60)
        hl.addWidget(save_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(32)
        del_btn.setStyleSheet("color:#f87171; font-weight:bold;")
        hl.addWidget(del_btn)

        def _save() -> None:
            name = reward_edit.text().strip()
            aid  = action_combo.currentData() or ""
            if name and aid:
                self._mappings.set(name, aid)

        def _delete() -> None:
            name = reward_edit.text().strip()
            if name:
                self._mappings.remove(name)
            idx = layout.indexOf(row_widget)
            if idx >= 0:
                layout.takeAt(idx)
            row_widget.deleteLater()

        save_btn.clicked.connect(_save)
        del_btn.clicked.connect(_delete)
        reward_edit.editingFinished.connect(_save)
        action_combo.currentIndexChanged.connect(lambda _: _save())

        layout.insertWidget(layout.count() - 1, row_widget)

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 12, 0, 0)
        vl.setSpacing(12)

        conn_box = QGroupBox("Connection")
        cl = QVBoxLayout(conn_box)
        cl.setContentsMargins(12, 10, 12, 10)
        conn_info = QLabel(
            "Uses the Twitch OAuth token from Stream Stats. "
            "Connect Stream Stats first and this plugin connects automatically."
        )
        conn_info.setObjectName("MetaText")
        conn_info.setWordWrap(True)
        cl.addWidget(conn_info)
        vl.addWidget(conn_box)

        fulfil_box = QGroupBox("Fulfilment")
        fl = QVBoxLayout(fulfil_box)
        fl.setContentsMargins(12, 10, 12, 10)
        self._fulfil_cb = QCheckBox(
            "Auto-fulfil channel point redemptions on Twitch when marked complete"
        )
        self._fulfil_cb.setChecked(True)
        self._fulfil_cb.toggled.connect(self._on_fulfil_toggled)
        fl.addWidget(self._fulfil_cb)
        vl.addWidget(fulfil_box)

        vl.addStretch(1)
        return w

    # ── Public API ────────────────────────────────────────────────────────────

    def set_status(self, text: str, connected: bool = False) -> None:
        self._status_lbl.setText(text)
        color = "#22c55e" if connected else "#94a3b8"
        self._status_lbl.setStyleSheet(f"color: {color};")

    def _on_fulfil_toggled(self, checked: bool) -> None:
        self._panel._fulfil_on_complete = checked
        self.fulfil_setting_changed.emit(checked)
