from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from stream_controller.ui.theme import create_card
from stream_controller.plugins.scene_manager.scene_models import ConnectionStatus, SceneManagerState

if TYPE_CHECKING:
    from stream_controller.plugins.scene_manager.scene_client import SceneClient
    from stream_controller.plugins.scene_manager.scene_repository import SceneRepository


# ══════════════════════════════════════════════════════════════════════════════
# SCENE PAGE — tabbed: Scenes | Overlays | Settings
# ══════════════════════════════════════════════════════════════════════════════

class ScenePage(QWidget):
    def __init__(
        self,
        client: "SceneClient",
        repo: "SceneRepository",
        overlay_base_url: str = "",
    ) -> None:
        super().__init__()
        self._client = client
        self._repo = repo
        self._overlay_base_url = overlay_base_url

        # overlay customisation state
        self._ov_accent = str(repo.get("overlay_accent", "7c3aed"))
        self._ov_text = str(repo.get("overlay_text", "f0f0ff"))
        self._ov_opacity = int(repo.get("overlay_opacity", 92))
        self._ov_url_labels: list[QLabel] = []

        # current scene name (updated on state change)
        self._current_scene: str = ""

        # Tracks scene cards so we can update them in-place without destroying widgets
        self._scene_cards: dict[str, QFrame] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_tab_bar())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_scenes_tab())
        self._stack.addWidget(self._build_overlays_tab())
        self._stack.addWidget(self._build_settings_tab())
        saved_tab = int(QSettings("StreamShift", "StreamController").value("scene_manager/tab", 0))
        self._stack.setCurrentIndex(saved_tab if 0 <= saved_tab < 3 else 0)
        root.addWidget(self._stack, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("MusicTabBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 0)
        layout.setSpacing(4)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)

        saved_tab = int(QSettings("StreamShift", "StreamController").value("scene_manager/tab", 0))
        for i, label in enumerate(["Scenes", "Overlays", "Settings"]):
            btn = QPushButton(label)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == saved_tab)
            btn.clicked.connect(lambda _=False, idx=i: self._on_tab_change(idx))
            self._tab_group.addButton(btn, i)
            layout.addWidget(btn)

        layout.addStretch(1)
        return bar

    def _on_tab_change(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        QSettings("StreamShift", "StreamController").setValue("scene_manager/tab", idx)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 0 — SCENES
    # ══════════════════════════════════════════════════════════════════════════

    def _build_scenes_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(20, 16, 20, 16)
        outer_layout.setSpacing(12)

        # Status bar
        outer_layout.addWidget(self._build_status_bar())

        # Scrollable scene grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._scenes_container = QWidget()
        self._scenes_grid = QGridLayout(self._scenes_container)
        self._scenes_grid.setContentsMargins(0, 0, 0, 0)
        self._scenes_grid.setSpacing(10)
        self._scenes_grid.setColumnStretch(0, 1)
        self._scenes_grid.setColumnStretch(1, 1)

        self._empty_scenes_label = QLabel(
            "Not connected to OBS — go to Settings tab to connect"
        )
        self._empty_scenes_label.setObjectName("EmptyState")
        self._empty_scenes_label.setAlignment(Qt.AlignCenter)
        self._empty_scenes_label.setWordWrap(True)
        self._scenes_grid.addWidget(self._empty_scenes_label, 0, 0, 1, 2)

        scroll.setWidget(self._scenes_container)
        outer_layout.addWidget(scroll, 1)

        return outer

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("SceneStatusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Coloured dot
        self._status_dot = QLabel()
        self._status_dot.setObjectName("SceneStatusDot")
        self._status_dot.setFixedSize(10, 10)
        layout.addWidget(self._status_dot, 0, Qt.AlignVCenter)

        # Status text
        self._status_label = QLabel("Disconnected")
        self._status_label.setObjectName("SceneStatusText")
        layout.addWidget(self._status_label, 1)

        # Right-side buttons
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.clicked.connect(self._on_refresh)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setVisible(False)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.clicked.connect(self._on_connect_now)

        layout.addWidget(self._refresh_btn)
        layout.addWidget(self._disconnect_btn)
        layout.addWidget(self._connect_btn)

        self._update_status_bar(ConnectionStatus.DISCONNECTED)
        return bar

    def _update_status_bar(self, status: ConnectionStatus, error: str = "") -> None:
        dot_colours = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#6b7280",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        status_texts = {
            ConnectionStatus.CONNECTED:    "Connected to OBS",
            ConnectionStatus.CONNECTING:   "Connecting...",
            ConnectionStatus.DISCONNECTED: "Disconnected",
            ConnectionStatus.ERROR:        f"Error: {error}" if error else "Connection error",
        }
        colour = dot_colours.get(status, "#6b7280")
        self._status_dot.setStyleSheet(
            f"QLabel {{ background: {colour}; border-radius: 5px; }}"
        )
        self._status_label.setText(status_texts.get(status, "Unknown"))

        connected = status == ConnectionStatus.CONNECTED
        connecting = status == ConnectionStatus.CONNECTING
        self._connect_btn.setVisible(not connected and not connecting)
        self._disconnect_btn.setVisible(connected or connecting)
        self._refresh_btn.setVisible(connected)

    # ── Scene card grid ───────────────────────────────────────────────────────

    def _rebuild_scene_cards(self, state: SceneManagerState) -> None:
        scenes = [s for s in state.scenes if not s.is_group]
        scene_names = [s.name for s in scenes]

        # If the scene list is unchanged, only update active-state styling in place.
        # This avoids deleteLater() calls that can cause macOS to surface the main
        # window while a fullscreen stage view is open.
        if scene_names == list(self._scene_cards.keys()):
            for scene in scenes:
                card = self._scene_cards.get(scene.name)
                if card is None:
                    continue
                obj = "SceneCardActive" if scene.is_current else "SceneCard"
                if card.objectName() != obj:
                    card.setObjectName(obj)
                    card.style().unpolish(card)
                    card.style().polish(card)
                    # Update the LIVE badge inside the card
                    for child in card.findChildren(QLabel):
                        if child.objectName() == "SceneLiveBadge":
                            child.setVisible(scene.is_current)
            return

        # Scene list changed — full rebuild.
        self._scene_cards.clear()
        while self._scenes_grid.count():
            item = self._scenes_grid.takeAt(0)
            if item and item.widget() and item.widget() is not self._empty_scenes_label:
                item.widget().deleteLater()

        has_scenes = bool(scenes)
        self._empty_scenes_label.setVisible(not has_scenes)
        if not has_scenes:
            self._scenes_grid.addWidget(self._empty_scenes_label, 0, 0, 1, 2)
            return

        for i, scene in enumerate(scenes):
            card = self._make_scene_card(scene, self._scenes_container)
            self._scene_cards[scene.name] = card
            self._scenes_grid.addWidget(card, i // 2, i % 2)

        # Trailing spacer row
        spacer = QWidget(self._scenes_container)
        spacer.setFixedHeight(1)
        self._scenes_grid.addWidget(spacer, (len(scenes) + 1) // 2, 0, 1, 2)

    def _make_scene_card(self, scene, parent=None) -> QFrame:
        is_active = scene.is_current
        card = QFrame(parent)
        card.setObjectName("SceneCardActive" if is_active else "SceneCard")
        card.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        name_lbl = QLabel(scene.name)
        name_lbl.setObjectName("SceneCardTitle")
        font = name_lbl.font()
        font.setBold(True)
        name_lbl.setFont(font)
        header_row.addWidget(name_lbl, 1)

        live_badge = QLabel("LIVE")
        live_badge.setObjectName("SceneLiveBadge")
        live_badge.setVisible(is_active)
        header_row.addWidget(live_badge, 0, Qt.AlignVCenter)

        layout.addLayout(header_row)

        # Make the entire card clickable
        card.mousePressEvent = lambda _event, n=scene.name: self._on_scene_card_clicked(n)

        return card

    def _on_scene_card_clicked(self, name: str) -> None:
        if self._client:
            self._client.switch_scene(name)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — OVERLAYS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_overlays_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_overlay_appearance_card())
        layout.addWidget(self._build_overlay_grid())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_overlay_appearance_card(self) -> QFrame:
        card, body = create_card(
            "Appearance",
            "Customise colours and opacity. URLs update automatically — copy them into OBS or Streamlabs.",
        )
        body.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(20)

        self._accent_edit, accent_swatch = self._make_color_picker(
            "Accent Colour", self._ov_accent, "7c3aed"
        )
        accent_col = QVBoxLayout()
        accent_col.setSpacing(5)
        accent_col.addWidget(_field_label("Accent Colour"))
        accent_col.addLayout(_color_picker_row(self._accent_edit, accent_swatch))
        row.addLayout(accent_col)

        self._text_edit, text_swatch = self._make_color_picker(
            "Text Colour", self._ov_text, "f0f0ff"
        )
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        text_col.addWidget(_field_label("Text Colour"))
        text_col.addLayout(_color_picker_row(self._text_edit, text_swatch))
        row.addLayout(text_col)

        bg_col = QVBoxLayout()
        bg_col.setSpacing(5)
        self._bg_opacity_label = _field_label(f"Background Opacity  ({self._ov_opacity}%)")
        bg_col.addWidget(self._bg_opacity_label)
        self._bg_slider = QSlider(Qt.Horizontal)
        self._bg_slider.setObjectName("MusicVolumeSlider")
        self._bg_slider.setRange(0, 100)
        self._bg_slider.setValue(self._ov_opacity)
        self._bg_slider.setFixedWidth(180)
        self._bg_slider.valueChanged.connect(self._on_bg_opacity_changed)
        bg_col.addWidget(self._bg_slider)
        row.addLayout(bg_col)

        row.addStretch(1)
        body.addLayout(row)
        return card

    def _make_color_picker(self, name: str, initial_hex: str, placeholder: str):
        """Return (QLineEdit, swatch QPushButton) wired together."""
        edit = QLineEdit(initial_hex)
        edit.setObjectName("OverlayTextField")
        edit.setMaximumWidth(90)
        edit.setPlaceholderText(placeholder)

        swatch = QPushButton()
        swatch.setObjectName("ColorSwatch")
        swatch.setFixedSize(32, 32)
        swatch.setToolTip(f"Pick {name}")

        def _apply_hex(hex_str: str) -> None:
            hex_str = hex_str.strip().lstrip("#")
            color = QColor(f"#{hex_str}")
            if color.isValid():
                swatch.setStyleSheet(
                    f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                    f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                    f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
                )

        def _open_picker() -> None:
            current = QColor(f"#{edit.text().strip().lstrip('#')}")
            color = QColorDialog.getColor(
                current if current.isValid() else QColor(f"#{placeholder}"),
                self,
                f"Choose {name}",
            )
            if color.isValid():
                hex_val = color.name().lstrip("#")
                edit.blockSignals(True)
                edit.setText(hex_val)
                edit.blockSignals(False)
                _apply_hex(hex_val)
                self._on_overlay_param_changed()

        _apply_hex(initial_hex)
        edit.textChanged.connect(lambda t: (_apply_hex(t), self._on_overlay_param_changed()))
        swatch.clicked.connect(_open_picker)
        return edit, swatch

    def _build_overlay_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        overlays = [
            {
                "name": "Scene Name",
                "path": "/name",
                "obs_size": "200 × 60 px",
                "desc": "Compact pill showing the current scene name in the accent colour. Great for a corner overlay.",
                "preview": self._make_preview_name,
            },
            {
                "name": "Lower Third Bar",
                "path": "/bar",
                "obs_size": "1920 × 120 px",
                "desc": "Full-width bar fixed to the bottom of the screen, scene name left-aligned. Classic broadcast lower third.",
                "preview": self._make_preview_bar,
            },
            {
                "name": "Scene Grid",
                "path": "/grid",
                "obs_size": "400 × 200 px",
                "desc": "All scenes displayed as small tiles. The current scene is highlighted in the accent colour.",
                "preview": self._make_preview_grid,
            },
            {
                "name": "Transition Flash",
                "path": "/transition",
                "obs_size": "1920 × 1080 px",
                "desc": "Brief fullscreen overlay that flashes on scene change. Adds a dramatic glow pulse to mark transitions.",
                "preview": self._make_preview_transition,
            },
        ]

        for i, ov in enumerate(overlays):
            card = self._make_overlay_card(ov)
            grid.addWidget(card, i // 2, i % 2)

        return container

    def _make_overlay_card(self, ov: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        preview = ov["preview"]()
        layout.addWidget(preview)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = QLabel(ov["name"])
        name_lbl.setObjectName("OverlayCardTitle")
        obs_lbl = QLabel(ov["obs_size"])
        obs_lbl.setObjectName("OverlayOBSHint")
        name_row.addWidget(name_lbl)
        name_row.addStretch(1)
        name_row.addWidget(obs_lbl)
        layout.addLayout(name_row)

        desc = QLabel(ov["desc"])
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        url_lbl = QLabel()
        url_lbl.setObjectName("OverlayURL")
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_lbl.setWordWrap(False)
        url_lbl.setProperty("_path", ov["path"])
        url_lbl.setText(self._overlay_url(ov["path"]))
        self._ov_url_labels.append(url_lbl)
        layout.addWidget(url_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(lambda _=False, lbl=url_lbl: QGuiApplication.clipboard().setText(lbl.text()))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        return card

    # ── Overlay preview widgets ───────────────────────────────────────────────

    def _make_preview_name(self) -> QFrame:
        """Small rounded pill with scene name in accent colour."""
        f = QFrame()
        f.setObjectName("OverlayMockMinimalWrap")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)

        pill = QFrame()
        pill.setObjectName("OverlayMockMinimal")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(14, 8, 14, 8)
        pill_layout.setSpacing(8)

        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(8, 8)

        scene_lbl = QLabel("Gaming")
        scene_lbl.setObjectName("OverlayMockTitle")

        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addWidget(scene_lbl)

        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        return f

    def _make_preview_bar(self) -> QFrame:
        """Dark full-width bar with scene name left-aligned."""
        f = QFrame()
        f.setObjectName("OverlayMockTicker")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(14)

        strip = QFrame()
        strip.setObjectName("OverlayMockBannerStrip")
        strip.setFixedWidth(4)
        layout.addWidget(strip)

        scene_lbl = QLabel("Gaming")
        scene_lbl.setObjectName("OverlayMockTitle")
        layout.addWidget(scene_lbl, 1, Qt.AlignVCenter)
        return f

    def _make_preview_grid(self) -> QFrame:
        """2x2 grid of small rounded boxes, one highlighted in accent colour."""
        f = QFrame()
        f.setObjectName("OverlayMockCard")
        f.setFixedHeight(100)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(5)

        tiles = ["Gaming", "Just Chatting", "BRB", "Starting Soon"]
        for i, title in enumerate(tiles):
            tile = QFrame()
            if i == 0:
                tile.setObjectName("SceneCardActive")
            else:
                tile.setObjectName("SceneCard")
            tile.setFixedHeight(28)
            tile_layout = QHBoxLayout(tile)
            tile_layout.setContentsMargins(6, 2, 6, 2)
            lbl = QLabel(title)
            lbl.setObjectName("OverlayMockArtist")
            tile_layout.addWidget(lbl)
            grid.addWidget(tile, i // 2, i % 2)

        layout.addLayout(grid)
        return f

    def _make_preview_transition(self) -> QFrame:
        """Dark box with glow pulse animation preview text."""
        f = QFrame()
        f.setObjectName("OverlayMockTimerFullscreen")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        scene_lbl = QLabel("Gaming")
        scene_lbl.setObjectName("OverlayMockTitle")
        scene_lbl.setAlignment(Qt.AlignCenter)

        hint = QLabel("scene transition")
        hint.setObjectName("OverlayMockEQLabel")
        hint.setAlignment(Qt.AlignCenter)

        layout.addWidget(scene_lbl)
        layout.addWidget(hint)
        return f

    # ── Overlay URL helpers ───────────────────────────────────────────────────

    def _overlay_url(self, path: str) -> str:
        base = self._overlay_base_url or "http://localhost:47892"
        params = []

        accent = self._accent_edit.text().strip().lstrip("#") if hasattr(self, "_accent_edit") else self._ov_accent
        text = self._text_edit.text().strip().lstrip("#") if hasattr(self, "_text_edit") else self._ov_text
        opacity = self._ov_opacity

        if accent:
            params.append(f"accent={accent}")
        if text:
            params.append(f"text={text}")
        if opacity != 92:
            params.append(f"opacity={opacity}")

        qs = ("?" + "&".join(params)) if params else ""
        suffix = "" if self._overlay_base_url else "  (overlay server not running)"
        return f"{base}{path}{qs}{suffix}"

    def _on_bg_opacity_changed(self, value: int) -> None:
        self._ov_opacity = value
        self._bg_opacity_label.setText(f"Background Opacity  ({value}%)")
        self._refresh_overlay_urls()

    def _on_overlay_param_changed(self) -> None:
        self._ov_accent = self._accent_edit.text().strip().lstrip("#")
        self._ov_text = self._text_edit.text().strip().lstrip("#")
        self._refresh_overlay_urls()

    def _refresh_overlay_urls(self) -> None:
        for lbl in self._ov_url_labels:
            path = lbl.property("_path")
            if path:
                lbl.setText(self._overlay_url(path))

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — SETTINGS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_connection_card())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_connection_card(self) -> QFrame:
        card, body = create_card(
            "OBS Connection",
            "Connect to OBS via the WebSocket server. Enable it in OBS under Tools > WebSocket Server Settings.",
        )
        body.setSpacing(12)

        from PySide6.QtWidgets import QFormLayout
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Host
        self._host_edit = QLineEdit(str(self._repo.get("host", "localhost")))
        self._host_edit.setObjectName("OverlayTextField")
        self._host_edit.setPlaceholderText("localhost")
        form.addRow("Host", self._host_edit)

        # Port
        self._port_spin = QSpinBox()
        self._port_spin.setObjectName("TimerTransportBtn")
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(int(self._repo.get("port", 4455)))
        form.addRow("Port", self._port_spin)

        # Password
        self._password_edit = QLineEdit(str(self._repo.get("password", "")))
        self._password_edit.setObjectName("OverlayTextField")
        self._password_edit.setEchoMode(QLineEdit.Password)
        self._password_edit.setPlaceholderText("Leave blank if no password set")
        form.addRow("Password", self._password_edit)

        body.addLayout(form)

        # Auto-connect checkbox
        self._auto_connect_cb = QCheckBox("Auto-connect on startup")
        self._auto_connect_cb.setObjectName("OverlayCheckBox")
        self._auto_connect_cb.setChecked(bool(self._repo.get("auto_connect", False)))
        self._auto_connect_cb.toggled.connect(self._save_settings)
        body.addWidget(self._auto_connect_cb)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._connect_now_btn = QPushButton("Connect Now")
        self._connect_now_btn.setObjectName("PrimaryButton")
        self._connect_now_btn.clicked.connect(self._on_connect_now)

        self._disconnect_settings_btn = QPushButton("Disconnect")
        self._disconnect_settings_btn.setObjectName("SecondaryButton")
        self._disconnect_settings_btn.clicked.connect(self._on_disconnect)

        btn_row.addWidget(self._connect_now_btn)
        btn_row.addWidget(self._disconnect_settings_btn)
        btn_row.addStretch(1)
        body.addLayout(btn_row)

        # Error label
        self._error_label = QLabel()
        self._error_label.setObjectName("SceneErrorLabel")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("QLabel { color: #ef4444; }")
        self._error_label.setVisible(False)
        body.addWidget(self._error_label)

        return card

    def _save_settings(self) -> None:
        self._repo.set("host", self._host_edit.text().strip() or "localhost")
        self._repo.set("port", self._port_spin.value())
        self._repo.set("password", self._password_edit.text())
        self._repo.set("auto_connect", self._auto_connect_cb.isChecked())

    def _on_connect_now(self) -> None:
        self._save_settings()
        self._error_label.setVisible(False)
        if self._client:
            self._client.connect(
                host=self._host_edit.text().strip() or "localhost",
                port=self._port_spin.value(),
                password=self._password_edit.text(),
            )

    def _on_disconnect(self) -> None:
        if self._client:
            self._client.disconnect()

    def _on_refresh(self) -> None:
        if self._client:
            self._client.refresh()

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC — called by plugin.py on every OBS state update
    # ══════════════════════════════════════════════════════════════════════════

    def on_state_changed(self, state: SceneManagerState) -> None:
        self._current_scene = state.current_scene

        # Update status bar
        self._update_status_bar(state.status, state.error)

        # Rebuild scene cards
        connected = state.status == ConnectionStatus.CONNECTED
        if connected:
            self._rebuild_scene_cards(state)
        else:
            # Show empty state with appropriate message
            while self._scenes_grid.count():
                item = self._scenes_grid.takeAt(0)
                if item and item.widget() and item.widget() is not self._empty_scenes_label:
                    item.widget().deleteLater()

            if state.status == ConnectionStatus.ERROR and state.error:
                self._empty_scenes_label.setText(f"Connection error: {state.error}")
            elif state.status == ConnectionStatus.CONNECTING:
                self._empty_scenes_label.setText("Connecting to OBS…")
            else:
                self._empty_scenes_label.setText(
                    "Not connected to OBS — go to Settings tab to connect"
                )
            self._empty_scenes_label.setVisible(True)
            self._scenes_grid.addWidget(self._empty_scenes_label, 0, 0, 1, 2)

        # Update error label in settings tab
        if hasattr(self, "_error_label"):
            if state.status == ConnectionStatus.ERROR and state.error:
                self._error_label.setText(state.error)
                self._error_label.setVisible(True)
            else:
                self._error_label.setVisible(False)

        # Refresh overlay URLs (scene name may appear in some overlays)
        self._refresh_overlay_urls()


# ── helpers ───────────────────────────────────────────────────────────────────

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("MusicFieldLabel")
    return lbl


def _color_picker_row(edit: QLineEdit, swatch: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(swatch)
    row.addWidget(edit)
    return row
