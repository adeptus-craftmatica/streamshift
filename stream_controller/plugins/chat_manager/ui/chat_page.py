from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.chat_manager.chat_models import ChatMessage, ChatState, ConnectionStatus
    from stream_controller.plugins.chat_manager.chat_repository import ChatRepository
    from stream_controller.plugins.chat_manager.chat_state import ChatStateManager

logger = logging.getLogger(__name__)


class ChatPage(QWidget):
    def __init__(
        self,
        chat_state: "ChatStateManager",
        repo: "ChatRepository",
        overlay_base_url: str = "",
    ) -> None:
        super().__init__()
        self._chat_state = chat_state
        self._repo = repo
        self._overlay_base_url = overlay_base_url
        self._auto_scroll = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setObjectName("PluginTabWidget")
        tabs.addTab(self._build_live_chat_tab(), "Live Chat")
        tabs.addTab(self._build_moderation_tab(), "Moderation")
        tabs.addTab(self._build_overlays_tab(), "Overlays")
        tabs.addTab(self._build_settings_tab(), "Settings")
        saved_tab = int(QSettings("StreamShift", "StreamController").value("chat/tab", 0))
        tabs.setCurrentIndex(saved_tab if 0 <= saved_tab < tabs.count() else 0)
        tabs.currentChanged.connect(lambda i: QSettings("StreamShift", "StreamController").setValue("chat/tab", i))
        layout.addWidget(tabs)

        self._chat_state.subscribe(self._on_chat_updated)

        # auto-connect if configured
        if self._repo.get("auto_connect") and self._repo.get("channel"):
            QTimer.singleShot(500, self._chat_state.connect)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Live Chat
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_live_chat_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Status bar
        status_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("ChatStatusDot")
        self._status_dot.setFixedWidth(16)
        self._status_label = QLabel("Disconnected")
        self._status_label.setObjectName("MetaText")
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.setMinimumWidth(100)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setMinimumWidth(110)
        self._disconnect_btn.clicked.connect(self._chat_state.disconnect)
        self._disconnect_btn.setEnabled(False)
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label, 1)
        status_row.addWidget(self._connect_btn)
        status_row.addWidget(self._disconnect_btn)
        root.addLayout(status_row)

        # Message list
        self._chat_list = QListWidget()
        self._chat_list.setObjectName("ChatMessageList")
        self._chat_list.setWordWrap(True)
        self._chat_list.setSpacing(2)
        self._chat_list.setSelectionMode(QListWidget.NoSelection)
        self._chat_list.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        self._chat_list.verticalScrollBar().valueChanged.connect(self._on_scroll_moved)
        root.addWidget(self._chat_list, 1)

        # Auto-scroll toggle
        scroll_row = QHBoxLayout()
        self._autoscroll_btn = QPushButton("Auto-scroll: On")
        self._autoscroll_btn.setObjectName("ChatToggleButton")
        self._autoscroll_btn.setCheckable(True)
        self._autoscroll_btn.setChecked(True)
        self._autoscroll_btn.clicked.connect(self._toggle_autoscroll)
        self._clear_local_btn = QPushButton("Clear Display")
        self._clear_local_btn.setObjectName("SecondaryButton")
        self._clear_local_btn.clicked.connect(self._chat_state.clear_local_messages)
        scroll_row.addWidget(self._autoscroll_btn)
        scroll_row.addStretch(1)
        scroll_row.addWidget(self._clear_local_btn)
        root.addLayout(scroll_row)

        # Send box (only enabled when authenticated)
        send_row = QHBoxLayout()
        send_row.setSpacing(8)
        self._send_input = QLineEdit()
        self._send_input.setObjectName("ChatSendInput")
        self._send_input.setPlaceholderText("Send a message… (requires OAuth token)")
        self._send_input.setEnabled(False)
        self._send_input.returnPressed.connect(self._send_message)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("PrimaryButton")
        self._send_btn.setFixedWidth(80)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._send_message)
        send_row.addWidget(self._send_input, 1)
        send_row.addWidget(self._send_btn)
        root.addLayout(send_row)

        return w

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Moderation
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_moderation_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # Quick actions row
        qa_label = _section_label("Quick Actions")
        root.addWidget(qa_label)

        qa_row = QHBoxLayout()
        qa_row.setSpacing(8)

        self._clear_chat_btn = QPushButton("Clear Chat")
        self._clear_chat_btn.setObjectName("ModActionButton")
        self._clear_chat_btn.clicked.connect(self._chat_state.clear_chat)

        self._slow_mode_btn = QPushButton("Slow: Off")
        self._slow_mode_btn.setObjectName("ModActionButton")
        self._slow_mode_btn.setCheckable(True)
        self._slow_mode_btn.clicked.connect(self._toggle_slow_mode)

        self._sub_only_btn = QPushButton("Sub Only: Off")
        self._sub_only_btn.setObjectName("ModActionButton")
        self._sub_only_btn.setCheckable(True)
        self._sub_only_btn.clicked.connect(self._toggle_sub_only)

        self._emote_only_btn = QPushButton("Emote Only: Off")
        self._emote_only_btn.setObjectName("ModActionButton")
        self._emote_only_btn.setCheckable(True)
        self._emote_only_btn.clicked.connect(self._toggle_emote_only)

        qa_row.addWidget(self._clear_chat_btn)
        qa_row.addWidget(self._slow_mode_btn)
        qa_row.addWidget(self._sub_only_btn)
        qa_row.addWidget(self._emote_only_btn)
        qa_row.addStretch(1)
        root.addLayout(qa_row)

        # Manual moderation
        manual_label = _section_label("Manual Commands")
        root.addWidget(manual_label)

        manual_frame = QFrame()
        manual_frame.setObjectName("CardFrame")
        manual_layout = QFormLayout(manual_frame)
        manual_layout.setContentsMargins(16, 14, 16, 14)
        manual_layout.setSpacing(10)

        self._mod_user_input = QLineEdit()
        self._mod_user_input.setObjectName("ChatSendInput")
        self._mod_user_input.setPlaceholderText("username")
        manual_layout.addRow("User:", self._mod_user_input)

        self._timeout_secs = QSpinBox()
        self._timeout_secs.setRange(1, 1209600)
        self._timeout_secs.setValue(600)
        self._timeout_secs.setSuffix(" s")
        manual_layout.addRow("Timeout:", self._timeout_secs)

        self._mod_reason_input = QLineEdit()
        self._mod_reason_input.setObjectName("ChatSendInput")
        self._mod_reason_input.setPlaceholderText("reason (optional)")
        manual_layout.addRow("Reason:", self._mod_reason_input)

        btn_row = QHBoxLayout()
        timeout_btn = QPushButton("Timeout")
        timeout_btn.setObjectName("ModActionButton")
        timeout_btn.clicked.connect(self._do_timeout)
        ban_btn = QPushButton("Ban")
        ban_btn.setObjectName("ModDangerButton")
        ban_btn.clicked.connect(self._do_ban)
        btn_row.addWidget(timeout_btn)
        btn_row.addWidget(ban_btn)
        btn_row.addStretch(1)
        manual_layout.addRow("", btn_row)
        root.addWidget(manual_frame)

        # Recent messages with per-message mod actions
        recent_label = _section_label("Recent Messages")
        root.addWidget(recent_label)

        self._mod_list = QListWidget()
        self._mod_list.setObjectName("ChatMessageList")
        self._mod_list.setWordWrap(True)
        self._mod_list.setSpacing(2)
        self._mod_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._mod_list.customContextMenuRequested.connect(self._on_mod_context_menu)
        root.addWidget(self._mod_list, 1)

        return w

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Overlays
    # ═══════════════════════════════════════════════════════════════════════════

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
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(10)

        title = QLabel("Appearance")
        title.setObjectName("OverlayCardTitle")
        body.addWidget(title)

        desc = QLabel("Customise colours and style. URLs update automatically — copy into OBS as Browser Source.")
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        body.addWidget(desc)

        row = QHBoxLayout()
        row.setSpacing(24)

        # Accent colour
        ac = QVBoxLayout(); ac.setSpacing(5)
        ac.addWidget(_section_label("Accent Colour"))
        self._accent_edit, accent_sw = self._make_color_picker("Accent", self._repo.get("overlay_accent") or "7c3aed")
        ac_pick = QHBoxLayout(); ac_pick.setSpacing(6)
        ac_pick.addWidget(accent_sw); ac_pick.addWidget(self._accent_edit)
        ac.addLayout(ac_pick)
        row.addLayout(ac)

        # Text colour
        tc = QVBoxLayout(); tc.setSpacing(5)
        tc.addWidget(_section_label("Text Colour"))
        self._text_edit, text_sw = self._make_color_picker("Text", self._repo.get("overlay_text") or "f0f0ff")
        tc_pick = QHBoxLayout(); tc_pick.setSpacing(6)
        tc_pick.addWidget(text_sw); tc_pick.addWidget(self._text_edit)
        tc.addLayout(tc_pick)
        row.addLayout(tc)

        # BG colour
        bg = QVBoxLayout(); bg.setSpacing(5)
        bg.addWidget(_section_label("Background"))
        self._bg_edit, bg_sw = self._make_color_picker("Background", self._repo.get("overlay_bg") or "0d0d0f")
        bg_pick = QHBoxLayout(); bg_pick.setSpacing(6)
        bg_pick.addWidget(bg_sw); bg_pick.addWidget(self._bg_edit)
        bg.addLayout(bg_pick)
        row.addLayout(bg)

        # Opacity
        op = QVBoxLayout(); op.setSpacing(5)
        self._ov_opacity_lbl = _section_label(f"BG Opacity  ({self._repo.get('overlay_opacity') or 90}%)")
        op.addWidget(self._ov_opacity_lbl)
        self._ov_opacity_slider = QSlider(Qt.Horizontal)
        self._ov_opacity_slider.setObjectName("MusicVolumeSlider")
        self._ov_opacity_slider.setRange(0, 100)
        self._ov_opacity_slider.setValue(int(self._repo.get("overlay_opacity") or 90))
        self._ov_opacity_slider.setFixedWidth(160)
        self._ov_opacity_slider.valueChanged.connect(self._on_bg_opacity_changed)
        op.addWidget(self._ov_opacity_slider)
        row.addLayout(op)

        # Font size
        fs = QVBoxLayout(); fs.setSpacing(5)
        fs.addWidget(_section_label("Font Size"))
        self._ov_font_size = QSpinBox()
        self._ov_font_size.setRange(10, 36)
        self._ov_font_size.setValue(int(self._repo.get("overlay_font_size") or 14))
        self._ov_font_size.setSuffix("px")
        self._ov_font_size.valueChanged.connect(self._on_overlay_param_changed)
        fs.addWidget(self._ov_font_size)
        row.addLayout(fs)

        row.addStretch(1)
        body.addLayout(row)
        return card

    def _make_color_picker(self, name: str, initial_hex: str):
        edit = QLineEdit(initial_hex.lstrip("#"))
        edit.setObjectName("OverlayTextField")
        edit.setMaximumWidth(90)

        swatch = QPushButton()
        swatch.setObjectName("ColorSwatch")
        swatch.setFixedSize(32, 32)
        swatch.setToolTip(f"Pick {name} colour")

        def _apply(hex_str: str) -> None:
            color = QColor(f"#{hex_str.strip().lstrip('#')}")
            if color.isValid():
                swatch.setStyleSheet(
                    f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                    f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                    f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
                )

        def _open() -> None:
            cur = QColor(f"#{edit.text().strip().lstrip('#')}")
            c = QColorDialog.getColor(cur if cur.isValid() else QColor("#7c3aed"), self, f"Choose {name}")
            if c.isValid():
                v = c.name().lstrip("#")
                edit.blockSignals(True)
                edit.setText(v)
                edit.blockSignals(False)
                _apply(v)
                self._on_overlay_param_changed()

        _apply(initial_hex)
        edit.textChanged.connect(lambda t: (_apply(t), self._on_overlay_param_changed()))
        swatch.clicked.connect(_open)
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
                "name": "Chat Feed",
                "path": "/feed",
                "desc": "Scrolling live chat — new messages slide in at the bottom, old ones scroll out. Great for a side panel or scene corner.",
                "obs_size": "400 × 600 px",
                "preview": self._make_feed_preview,
            },
            {
                "name": "Chat Popup",
                "path": "/popup",
                "desc": "Shows each new message as a bold popup card that fades in then auto-hides after a few seconds. Eye-catching but non-intrusive.",
                "obs_size": "600 × 120 px",
                "preview": self._make_popup_preview,
            },
            {
                "name": "Chat Ticker",
                "path": "/ticker",
                "desc": "Single-line horizontal ticker scrolling recent messages across the bottom of the scene. Perfect for news-bar style placement.",
                "obs_size": "1920 × 44 px",
                "preview": self._make_ticker_preview,
            },
            {
                "name": "Minimal Pill",
                "path": "/minimal",
                "desc": "Tiny rounded pill that slides in with the latest message and fades out automatically. Zero screen footprint — ideal for busy layouts.",
                "obs_size": "480 × 52 px",
                "preview": self._make_minimal_preview,
            },
            {
                "name": "Event Alert",
                "path": "/alert",
                "desc": "Events-only overlay — triggers on subs, gift subs, bits, raids, channel point redemptions, and announcements. Ignores regular chat. Dramatic centre-screen pop with animated icon and glowing accent border.",
                "obs_size": "700 × 160 px",
                "preview": self._make_alert_preview,
            },
            {
                "name": "Sidebar",
                "path": "/sidebar",
                "desc": "Vertical stacked feed with a Live Chat header — shows the last few messages with usernames and message text. Great for a narrow side column.",
                "obs_size": "320 × 500 px",
                "preview": self._make_sidebar_preview,
            },
            {
                "name": "Neon Pulse",
                "path": "/neon",
                "desc": "Glowing chat feed where every message card pulses with the user's chat colour. Glassmorphism cards slide in from the right with a neon glow animation. Optional scanline texture (?scan=1). Params: max, fade, scan.",
                "obs_size": "420 × 650 px",
                "preview": self._make_neon_preview,
            },
            {
                "name": "Spotlight",
                "path": "/spotlight",
                "desc": "Cinema-mode single-message display. Each new message scales into view centre-screen with a vignette, a glowing accent bar, and a countdown progress strip. Ideal for reaction or just-chatting streams. Params: duration, vignette.",
                "obs_size": "800 × 180 px",
                "preview": self._make_spotlight_preview,
            },
            {
                "name": "Bubble Float",
                "path": "/bubbles",
                "desc": "Messages spawn as speech bubbles that drift upward with a gentle sine-wave float and fade as they rise. Each bubble glows in the sender's colour. Great for high-energy streams or fullscreen layouts. Params: speed, spread.",
                "obs_size": "1920 × 1080 px",
                "preview": self._make_bubbles_preview,
            },
        ]

        self._ov_url_labels: list[QLabel] = []

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

        layout.addWidget(ov["preview"]())

        name_row = QHBoxLayout()
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
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(lambda _=False, lbl=url_lbl: QGuiApplication.clipboard().setText(lbl.text()))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        return card

    def _overlay_url(self, path: str) -> str:
        base = self._overlay_base_url or "http://localhost:47892"
        params = []
        if hasattr(self, "_accent_edit"):
            a = self._accent_edit.text().strip().lstrip("#")
            if a and a != "7c3aed":
                params.append(f"accent={a}")
        if hasattr(self, "_text_edit"):
            t = self._text_edit.text().strip().lstrip("#")
            if t and t != "f0f0ff":
                params.append(f"text={t}")
        if hasattr(self, "_bg_edit"):
            b = self._bg_edit.text().strip().lstrip("#")
            if b and b != "0d0d0f":
                params.append(f"bg={b}")
        if hasattr(self, "_ov_opacity_slider"):
            v = self._ov_opacity_slider.value()
            if v != 90:
                params.append(f"opacity={v}")
        if hasattr(self, "_ov_font_size"):
            fs = self._ov_font_size.value()
            if fs != 14:
                params.append(f"size={fs}")
        qs = ("?" + "&".join(params)) if params else ""
        return f"{base}{path}{qs}"

    def _refresh_overlay_urls(self) -> None:
        for lbl in getattr(self, "_ov_url_labels", []):
            path = lbl.property("_path")
            if path:
                lbl.setText(self._overlay_url(path))

    def _on_bg_opacity_changed(self, value: int) -> None:
        self._ov_opacity_lbl.setText(f"BG Opacity  ({value}%)")
        self._repo.set("overlay_opacity", value)
        self._refresh_overlay_urls()

    # ── Static preview widgets ────────────────────────────────────────────────

    def _make_feed_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockChat")
        f.setFixedHeight(120)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        msgs = [
            ("StreamerFan99", "#ff6b6b", "PogChamp that was insane!!"),
            ("ModeratorMike", "#00d4aa", "Welcome to the stream everyone!"),
            ("CasualViewer", "#a78bfa", "lurking 👀"),
        ]
        for name, color, text in msgs:
            row = QHBoxLayout()
            row.setSpacing(6)
            name_lbl = QLabel(name + ":")
            name_lbl.setObjectName("ChatMockName")
            name_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")
            name_lbl.setFixedWidth(100)
            text_lbl = QLabel(text)
            text_lbl.setObjectName("ChatMockText")
            row.addWidget(name_lbl)
            row.addWidget(text_lbl, 1)
            layout.addLayout(row)
        layout.addStretch(1)
        return f

    def _make_popup_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockPopup")
        f.setFixedHeight(80)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        label = QLabel("Chat")
        label.setObjectName("ChatMockPopupLabel")
        name = QLabel("StreamerFan99")
        name.setObjectName("ChatMockPopupName")
        text = QLabel("PogChamp that was absolutely insane!!")
        text.setObjectName("ChatMockPopupText")
        layout.addWidget(label)
        layout.addWidget(name)
        layout.addWidget(text)
        return f

    def _make_ticker_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTicker")
        f.setFixedHeight(38)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        badge = QFrame()
        badge.setObjectName("OverlayMockTickerBadge")
        badge.setFixedWidth(56)
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_lbl = QLabel("CHAT")
        badge_lbl.setObjectName("OverlayMockTickerLabel")
        badge_lbl.setAlignment(Qt.AlignCenter)
        badge_layout.addWidget(badge_lbl)
        scroll_lbl = QLabel("  StreamerFan99: PogChamp!  ★  ModeratorMike: Welcome!  ★  CasualViewer: lurking 👀")
        scroll_lbl.setObjectName("OverlayMockTickerText")
        layout.addWidget(badge)
        layout.addWidget(scroll_lbl, 1)
        return f

    def _make_minimal_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockMinimalWrap")
        f.setFixedHeight(44)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(10, 0, 10, 0)
        pill = QFrame()
        pill.setObjectName("OverlayMockMinimalPill")
        pill_row = QHBoxLayout(pill)
        pill_row.setContentsMargins(10, 6, 14, 6)
        pill_row.setSpacing(8)
        dot = QLabel("●")
        dot.setObjectName("OverlayMockMinimalDot")
        name = QLabel("StreamerFan99")
        name.setObjectName("OverlayMockMinimalName")
        sep = QLabel("·")
        sep.setObjectName("OverlayMockMinimalSep")
        text = QLabel("PogChamp that was insane!!")
        text.setObjectName("OverlayMockMinimalText")
        pill_row.addWidget(dot)
        pill_row.addWidget(name)
        pill_row.addWidget(sep)
        pill_row.addWidget(text, 1)
        layout.addWidget(pill)
        layout.addStretch(1)
        return f

    def _make_alert_preview(self) -> QFrame:
        outer = QFrame()
        outer.setObjectName("OverlayMockAlertOuter")
        outer.setFixedHeight(88)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Accent bar at top
        bar = QFrame()
        bar.setObjectName("OverlayMockAlertBar")
        bar.setFixedHeight(4)
        outer_layout.addWidget(bar)

        f = QFrame()
        f.setObjectName("OverlayMockAlertCard")
        inner = QHBoxLayout(f)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(14)

        icon = QLabel("🎉")
        icon.setObjectName("OverlayMockAlertIcon")

        body = QVBoxLayout()
        body.setSpacing(3)
        badge_row = QHBoxLayout()
        badge = QFrame()
        badge.setObjectName("OverlayMockAlertBadge")
        badge_inner = QHBoxLayout(badge)
        badge_inner.setContentsMargins(6, 1, 6, 1)
        badge_lbl = QLabel("New Sub")
        badge_lbl.setObjectName("OverlayMockAlertBadgeLabel")
        badge_inner.addWidget(badge_lbl)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)

        name = QLabel("StreamerFan99")
        name.setObjectName("OverlayMockAlertName")
        text = QLabel("StreamerFan99 subscribed for the first time!")
        text.setObjectName("OverlayMockAlertText")
        body.addLayout(badge_row)
        body.addWidget(name)
        body.addWidget(text)

        inner.addWidget(icon, 0, Qt.AlignVCenter)
        inner.addLayout(body, 1)
        outer_layout.addWidget(f, 1)
        return outer

    def _make_sidebar_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockSidebar")
        f.setFixedHeight(110)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("OverlayMockSidebarDot")
        hdr = QLabel("LIVE CHAT")
        hdr.setObjectName("OverlayMockSidebarHeader")
        header.addWidget(dot)
        header.addWidget(hdr)
        header.addStretch(1)
        layout.addLayout(header)
        sep = QFrame()
        sep.setObjectName("OverlayMockSidebarSep")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(5)
        msgs = [
            ("StreamerFan99", "#ff6b6b", "PogChamp!!"),
            ("ModeratorMike", "#00d4aa", "Welcome everyone!"),
            ("CasualViewer",  "#a78bfa", "lurking 👀"),
        ]
        for uname, color, txt in msgs:
            row = QHBoxLayout()
            row.setSpacing(5)
            n = QLabel(uname)
            n.setObjectName("ChatMockName")
            n.setStyleSheet(f"color:{color};font-weight:bold;font-size:10px;")
            n.setFixedWidth(90)
            t = QLabel(txt)
            t.setObjectName("ChatMockText")
            row.addWidget(n)
            row.addWidget(t, 1)
            layout.addLayout(row)
        return f

    def _make_neon_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockChat")
        f.setFixedHeight(120)
        f.setStyleSheet("#OverlayMockChat { background: #0d0d0f; border-radius: 8px; }")
        layout = QVBoxLayout(f)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)
        msgs = [
            ("StreamerFan99", "#ff6b6b", "PogChamp that was insane!!"),
            ("ModeratorMike", "#00d4aa", "Welcome to the stream!"),
            ("CasualViewer",  "#a78bfa", "lurking 👀"),
        ]
        for name, color, text in msgs:
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ border: 1px solid {color}; border-radius: 6px; "
                f"background: rgba(13,13,15,0.85); }}"
            )
            rl = QVBoxLayout(row)
            rl.setContentsMargins(8, 4, 8, 4)
            rl.setSpacing(1)
            n = QLabel(name)
            n.setStyleSheet(f"color:{color}; font-weight: 800; font-size: 10px; border: none; background: transparent;")
            t = QLabel(text)
            t.setStyleSheet("color: #f0f0ff; font-size: 10px; border: none; background: transparent;")
            rl.addWidget(n)
            rl.addWidget(t)
            layout.addWidget(row)
        layout.addStretch(1)
        return f

    def _make_spotlight_preview(self) -> QFrame:
        outer = QFrame()
        outer.setObjectName("OverlayMockAlertOuter")
        outer.setFixedHeight(88)
        outer.setStyleSheet("#OverlayMockAlertOuter { background: #0a0a10; border-radius: 8px; }")
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(12, 10, 12, 10)
        ol.setSpacing(6)

        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet("background: #7c3aed; border-radius: 2px;")
        ol.addWidget(bar)

        name_lbl = QLabel("StreamerFan99")
        name_lbl.setStyleSheet(
            "color: #a78bfa; font-weight: 800; font-size: 10px; "
            "letter-spacing: 2px; text-transform: uppercase;"
        )
        msg_lbl = QLabel("PogChamp that was absolutely insane!!")
        msg_lbl.setStyleSheet("color: #f0f0ff; font-size: 13px;")
        msg_lbl.setWordWrap(True)

        prog = QFrame()
        prog.setFixedHeight(3)
        prog.setStyleSheet("background: rgba(124,58,237,0.4); border-radius: 2px;")

        ol.addWidget(name_lbl)
        ol.addWidget(msg_lbl, 1)
        ol.addWidget(prog)
        return outer

    def _make_bubbles_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockChat")
        f.setFixedHeight(120)
        f.setStyleSheet("#OverlayMockChat { background: transparent; }")
        layout = QVBoxLayout(f)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        bubbles = [
            ("StreamerFan99", "#ff6b6b", "PogChamp!!"),
            ("CasualViewer",  "#a78bfa", "lurking 👀"),
        ]
        offsets = [0, 60]
        for (name, color, text), offset in zip(bubbles, offsets):
            row = QHBoxLayout()
            row.addSpacing(offset)
            bubble = QFrame()
            bubble.setStyleSheet(
                f"QFrame {{ border: 1.5px solid {color}; border-radius: 12px; "
                f"background: rgba(13,13,15,0.88); padding: 2px 6px; }}"
            )
            bl = QVBoxLayout(bubble)
            bl.setContentsMargins(6, 3, 6, 3)
            bl.setSpacing(1)
            n = QLabel(name)
            n.setStyleSheet(f"color:{color}; font-weight: 800; font-size: 9px; border: none; background: transparent;")
            t = QLabel(text)
            t.setStyleSheet("color: #f0f0ff; font-size: 10px; border: none; background: transparent;")
            bl.addWidget(n)
            bl.addWidget(t)
            row.addWidget(bubble)
            row.addStretch(1)
            layout.addLayout(row)
        layout.addStretch(1)
        return f

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4 — Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 16, 20, 24)
        root.setSpacing(16)
        scroll.setWidget(inner)

        root.addWidget(_section_label("Twitch Connection"))

        conn_frame = QFrame()
        conn_frame.setObjectName("CardFrame")
        form = QFormLayout(conn_frame)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(12)

        self._channel_input = QLineEdit(self._repo.get("channel") or "")
        self._channel_input.setObjectName("ChatSendInput")
        self._channel_input.setPlaceholderText("your_channel_name")
        self._channel_input.textChanged.connect(lambda t: self._repo.set("channel", t.strip().lower()))
        form.addRow("Channel:", self._channel_input)

        self._client_id_input = QLineEdit(self._repo.get("client_id") or "")
        self._client_id_input.setObjectName("ChatSendInput")
        self._client_id_input.setPlaceholderText("Paste your Twitch Client ID here")
        self._client_id_input.textChanged.connect(lambda t: self._repo.set("client_id", t.strip()))
        form.addRow("Client ID:", self._client_id_input)

        root.addWidget(conn_frame)

        # Client ID helper
        client_id_hint = _hint_label(
            "Need a Client ID? Go to dev.twitch.tv/console → Register Your Application.\n"
            "Set OAuth Redirect URL to: http://localhost:47893/callback\n"
            "Copy the Client ID here, then click Authorize below."
        )
        root.addWidget(client_id_hint)

        # ── Authorization row ──────────────────────────────────────────────────
        auth_frame = QFrame()
        auth_frame.setObjectName("CardFrame")
        auth_layout = QVBoxLayout(auth_frame)
        auth_layout.setContentsMargins(16, 14, 16, 14)
        auth_layout.setSpacing(10)

        auth_top = QHBoxLayout()
        self._auth_status_label = QLabel()
        self._auth_status_label.setObjectName("MetaText")
        self._auth_status_label.setWordWrap(True)
        self._auth_btn = QPushButton("Authorize with Twitch")
        self._auth_btn.setObjectName("TwitchAuthButton")
        self._auth_btn.setFixedWidth(200)
        self._auth_btn.clicked.connect(self._on_authorize_clicked)
        self._revoke_btn = QPushButton("Revoke Access")
        self._revoke_btn.setObjectName("SecondaryButton")
        self._revoke_btn.setMinimumWidth(110)
        self._revoke_btn.clicked.connect(self._on_revoke_clicked)
        auth_top.addWidget(self._auth_btn)
        auth_top.addWidget(self._revoke_btn)
        auth_top.addStretch(1)
        auth_layout.addLayout(auth_top)
        auth_layout.addWidget(self._auth_status_label)
        root.addWidget(auth_frame)
        self._refresh_auth_status()

        # Connection controls
        ctrl_row = QHBoxLayout()
        connect_btn = QPushButton("Connect Now")
        connect_btn.setObjectName("PrimaryButton")
        connect_btn.clicked.connect(self._on_connect_clicked)
        ctrl_row.addWidget(connect_btn)
        ctrl_row.addStretch(1)
        root.addLayout(ctrl_row)

        root.addWidget(_section_label("Display Options"))

        opts_frame = QFrame()
        opts_frame.setObjectName("CardFrame")
        opts_form = QFormLayout(opts_frame)
        opts_form.setContentsMargins(16, 14, 16, 14)
        opts_form.setSpacing(10)

        max_msgs = QSpinBox()
        max_msgs.setRange(50, 2000)
        max_msgs.setValue(int(self._repo.get("max_messages") or 500))
        max_msgs.setSuffix(" messages")
        max_msgs.valueChanged.connect(lambda v: self._repo.set("max_messages", v))
        opts_form.addRow("Buffer Size:", max_msgs)

        root.addWidget(opts_frame)
        root.addStretch(1)
        return scroll

    # ═══════════════════════════════════════════════════════════════════════════
    # Twitch OAuth
    # ═══════════════════════════════════════════════════════════════════════════

    def _refresh_auth_status(self) -> None:
        token = self._repo.get("oauth_token") or ""
        username = self._repo.get("username") or ""
        if token and username:
            self._auth_status_label.setText(f"Authorized as @{username}")
            self._auth_status_label.setStyleSheet("color: #22c55e;")
            self._auth_btn.setText("Re-authorize")
            self._revoke_btn.setEnabled(True)
        elif token:
            self._auth_status_label.setText("Authorized (username unknown — connect once to verify)")
            self._auth_status_label.setStyleSheet("color: #f59e0b;")
            self._auth_btn.setText("Re-authorize")
            self._revoke_btn.setEnabled(True)
        else:
            self._auth_status_label.setText("Not authorized — read-only mode")
            self._auth_status_label.setStyleSheet("color: #64748b;")
            self._auth_btn.setText("Authorize with Twitch")
            self._revoke_btn.setEnabled(False)

    def _on_authorize_clicked(self) -> None:
        from stream_controller.plugins.chat_manager.twitch_auth import TwitchAuthFlow
        client_id = self._client_id_input.text().strip()
        if not client_id:
            self._auth_status_label.setText("Enter your Client ID first.")
            self._auth_status_label.setStyleSheet("color: #ef4444;")
            return

        self._auth_btn.setEnabled(False)
        self._auth_btn.setText("Waiting for browser…")
        self._auth_status_label.setText("Opening Twitch authorization in your browser…")
        self._auth_status_label.setStyleSheet("color: #f59e0b;")

        flow = TwitchAuthFlow(
            client_id=client_id,
            on_complete=self._on_auth_complete,
            on_error=self._on_auth_error,
        )
        flow.start()

    def _on_auth_complete(self, token: str, username: str) -> None:
        from PySide6.QtCore import QMetaObject, Qt
        # Called from background thread — must marshal to main thread
        QMetaObject.invokeMethod(
            self, "_apply_auth_result",
            Qt.QueuedConnection,
            *_qt_args(token, username),
        )

    def _on_auth_error(self, message: str) -> None:
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self, "_apply_auth_error",
            Qt.QueuedConnection,
            *_qt_args(message),
        )

    from PySide6.QtCore import Slot

    @Slot(str, str)
    def _apply_auth_result(self, token: str, username: str) -> None:
        self._repo.set("oauth_token", token)
        if username:
            self._repo.set("username", username)
            if hasattr(self, "_username_input"):
                self._username_input.setText(username) if hasattr(self, "_username_input") else None
        self._auth_btn.setEnabled(True)
        self._refresh_auth_status()
        # Update send box placeholder if connected
        if self._chat_state.client.can_write:
            self._send_input.setPlaceholderText("Send a message to chat…")
            self._send_input.setEnabled(True)
            self._send_btn.setEnabled(True)

    @Slot(str)
    def _apply_auth_error(self, message: str) -> None:
        self._auth_btn.setEnabled(True)
        self._auth_btn.setText("Authorize with Twitch")
        self._auth_status_label.setText(f"Authorization failed: {message}")
        self._auth_status_label.setStyleSheet("color: #ef4444;")

    def _on_revoke_clicked(self) -> None:
        self._repo.set("oauth_token", "")
        self._refresh_auth_status()
        self._send_input.setEnabled(False)
        self._send_btn.setEnabled(False)

    # ═══════════════════════════════════════════════════════════════════════════
    # State updates
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_chat_updated(self, messages: list, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus
        self._update_connection_ui(state)
        self._refresh_chat_list(messages)
        self._refresh_mod_list(messages)
        self._refresh_mod_buttons(state)

    def _update_connection_ui(self, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus
        s = state.status
        color_map = {
            ConnectionStatus.CONNECTED: "#22c55e",
            ConnectionStatus.CONNECTING: "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR: "#ef4444",
        }
        label_map = {
            ConnectionStatus.CONNECTED: f"Connected — #{state.channel}",
            ConnectionStatus.CONNECTING: state.error_message or "Connecting…",
            ConnectionStatus.DISCONNECTED: "Disconnected",
            ConnectionStatus.ERROR: state.error_message or "Error",
        }
        self._status_dot.setStyleSheet(f"color: {color_map.get(s, '#64748b')};")
        self._status_label.setText(label_map.get(s, "Unknown"))
        connected = s == ConnectionStatus.CONNECTED
        self._connect_btn.setEnabled(s != ConnectionStatus.CONNECTING and not connected)
        self._disconnect_btn.setEnabled(connected or s == ConnectionStatus.CONNECTING)
        can_write = self._chat_state.client.can_write
        self._send_input.setEnabled(can_write)
        self._send_btn.setEnabled(can_write)
        if can_write:
            self._send_input.setPlaceholderText("Send a message to chat…")
        else:
            self._send_input.setPlaceholderText("Read-only mode (add OAuth token to send messages)")

    def _refresh_chat_list(self, messages: list) -> None:
        self._chat_list.clear()
        for msg in messages[-200:]:
            item = self._make_chat_item(msg)
            self._chat_list.addItem(item)
        if self._auto_scroll:
            self._chat_list.scrollToBottom()

    def _refresh_mod_list(self, messages: list) -> None:
        self._mod_list.clear()
        for msg in reversed(messages[-100:]):
            item = self._make_chat_item(msg, show_mod_hint=True)
            self._mod_list.addItem(item)

    def _refresh_mod_buttons(self, state: "ChatState") -> None:
        self._slow_mode_btn.setChecked(state.slow_mode > 0)
        self._slow_mode_btn.setText(
            f"Slow: {state.slow_mode}s" if state.slow_mode > 0 else "Slow: Off"
        )
        self._sub_only_btn.setChecked(state.sub_only)
        self._sub_only_btn.setText("Sub Only: On" if state.sub_only else "Sub Only: Off")
        self._emote_only_btn.setChecked(state.emote_only)
        self._emote_only_btn.setText("Emote Only: On" if state.emote_only else "Emote Only: Off")

    def _make_chat_item(self, msg: "ChatMessage", show_mod_hint: bool = False) -> QListWidgetItem:
        from stream_controller.plugins.chat_manager.chat_models import MsgType
        time_str = msg.ts.strftime("%H:%M") if self._repo.get("show_timestamps") else ""
        time_prefix = f"[{time_str}] " if time_str else ""

        if msg.deleted:
            text = f"{time_prefix}[deleted] {msg.display_name}"
        elif msg.is_event:
            icon = msg.event_icon
            label = msg.event_label
            if msg.msg_type == MsgType.BITS:
                text = f"{time_prefix}{icon} {msg.display_name} cheered {msg.bits} bits! — {msg.text}"
            elif msg.msg_type == MsgType.CHANNEL_POINTS:
                text = f"{time_prefix}{icon} {msg.display_name} redeemed Channel Points — {msg.text}"
            else:
                text = f"{time_prefix}{icon} {msg.text}"
        else:
            badges = "".join(msg.badge_labels)
            prefix = f"{badges} " if badges else ""
            text = f"{time_prefix}{prefix}{msg.display_name}: {msg.text}"

        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, msg.msg_id)
        item.setData(Qt.UserRole + 1, msg.username)

        if msg.deleted:
            item.setForeground(QColor("#555566"))
        elif msg.msg_type == MsgType.BITS:
            item.setForeground(QColor("#fbbf24"))   # gold
        elif msg.msg_type == MsgType.CHANNEL_POINTS:
            item.setForeground(QColor("#2dd4bf"))   # teal
        elif msg.is_event:
            item.setForeground(QColor("#a78bfa"))   # purple for all sub/raid/ritual events
        return item

    # ═══════════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_connect_clicked(self) -> None:
        self._chat_state.connect()

    def _send_message(self) -> None:
        text = self._send_input.text().strip()
        if not text:
            return
        self._chat_state.send_message(text)
        self._send_input.clear()

    def _toggle_autoscroll(self, checked: bool) -> None:
        self._auto_scroll = checked
        self._autoscroll_btn.setText("Auto-scroll: On" if checked else "Auto-scroll: Off")

    def _on_scroll_range_changed(self, _min, _max) -> None:
        if self._auto_scroll:
            self._chat_list.scrollToBottom()

    def _on_scroll_moved(self, value: int) -> None:
        bar = self._chat_list.verticalScrollBar()
        at_bottom = value >= bar.maximum() - 4
        if not at_bottom:
            self._auto_scroll = False
            self._autoscroll_btn.setChecked(False)
            self._autoscroll_btn.setText("Auto-scroll: Off")

    def _toggle_slow_mode(self, checked: bool) -> None:
        self._chat_state.set_slow_mode(30 if checked else 0)

    def _toggle_sub_only(self, checked: bool) -> None:
        self._chat_state.set_sub_only(checked)

    def _toggle_emote_only(self, checked: bool) -> None:
        self._chat_state.set_emote_only(checked)

    def _do_timeout(self) -> None:
        user = self._mod_user_input.text().strip()
        if not user:
            return
        reason = self._mod_reason_input.text().strip()
        self._chat_state.timeout_user(user, self._timeout_secs.value(), reason)
        self._mod_user_input.clear()
        self._mod_reason_input.clear()

    def _do_ban(self) -> None:
        user = self._mod_user_input.text().strip()
        if not user:
            return
        reason = self._mod_reason_input.text().strip()
        self._chat_state.ban_user(user, reason)
        self._mod_user_input.clear()
        self._mod_reason_input.clear()

    def _on_mod_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._mod_list.itemAt(pos)
        if not item:
            return
        msg_id = item.data(Qt.UserRole)
        username = item.data(Qt.UserRole + 1)
        if not username:
            return

        menu = QMenu(self)
        menu.addAction(f"Timeout {username} (10 min)", lambda: self._chat_state.timeout_user(username, 600))
        menu.addAction(f"Ban {username}", lambda: self._chat_state.ban_user(username))
        if msg_id:
            menu.addAction("Delete this message", lambda: self._chat_state.delete_message(msg_id))
        menu.addSeparator()
        menu.addAction(f"Copy username", lambda: _copy_to_clipboard(username))
        menu.exec(self._mod_list.mapToGlobal(pos))

    def _on_overlay_param_changed(self) -> None:
        if hasattr(self, "_accent_edit"):
            self._repo.set("overlay_accent", self._accent_edit.text().strip().lstrip("#"))
        if hasattr(self, "_text_edit"):
            self._repo.set("overlay_text", self._text_edit.text().strip().lstrip("#"))
        if hasattr(self, "_bg_edit"):
            self._repo.set("overlay_bg", self._bg_edit.text().strip().lstrip("#"))
        if hasattr(self, "_ov_font_size"):
            self._repo.set("overlay_font_size", self._ov_font_size.value())
        self._refresh_overlay_urls()

    def closeEvent(self, event) -> None:
        self._chat_state.unsubscribe(self._on_chat_updated)
        super().closeEvent(event)


# ── helpers ───────────────────────────────────────────────────────────────────

def _qt_args(*values):
    """Wrap values as Q_ARG objects for QMetaObject.invokeMethod."""
    from PySide6.QtCore import Q_ARG
    return [Q_ARG(str, str(v)) for v in values]

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionLabel")
    font = lbl.font()
    font.setPointSize(11)
    font.setBold(True)
    lbl.setFont(font)
    return lbl


def _hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("CardDescription")
    lbl.setWordWrap(True)
    return lbl


def _url_card(name: str, url: str, description: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("CardFrame")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)

    title = QLabel(name)
    title.setObjectName("CardTitle")
    font = title.font()
    font.setBold(True)
    title.setFont(font)
    layout.addWidget(title)

    desc = QLabel(description)
    desc.setObjectName("CardDescription")
    desc.setWordWrap(True)
    layout.addWidget(desc)

    url_row = QHBoxLayout()
    url_edit = QLineEdit(url)
    url_edit.setObjectName("OverlayUrlField")
    url_edit.setReadOnly(True)
    copy_btn = QPushButton("Copy URL")
    copy_btn.setObjectName("SecondaryButton")
    copy_btn.setFixedWidth(90)
    copy_btn.clicked.connect(lambda: _copy_to_clipboard(url))
    url_row.addWidget(url_edit, 1)
    url_row.addWidget(copy_btn)
    layout.addLayout(url_row)

    return frame


def _make_color_picker(
    repo_key: str,
    initial_hex: str,
    repo,
    on_changed,
) -> tuple[QLineEdit, QPushButton]:
    edit = QLineEdit(initial_hex)
    edit.setObjectName("OverlayHexInput")
    edit.setFixedWidth(80)
    edit.setMaxLength(6)
    edit.setPlaceholderText("rrggbb")

    swatch = QPushButton()
    swatch.setObjectName("ColorSwatch")
    swatch.setFixedSize(32, 32)
    swatch.setToolTip("Click to pick a color")
    _apply_swatch(swatch, initial_hex)

    def _on_edit_changed(text: str) -> None:
        if len(text) == 6:
            _apply_swatch(swatch, text)
            repo.set(repo_key, text)
            on_changed()

    def _on_swatch_clicked() -> None:
        initial = QColor(f"#{edit.text()}" if len(edit.text()) == 6 else "#7c3aed")
        color = QColorDialog.getColor(initial, None, "Pick a Color")
        if color.isValid():
            hex_val = color.name().lstrip("#")
            edit.setText(hex_val)
            _apply_swatch(swatch, hex_val)
            repo.set(repo_key, hex_val)
            on_changed()

    edit.textChanged.connect(_on_edit_changed)
    swatch.clicked.connect(_on_swatch_clicked)
    return edit, swatch


def _apply_swatch(btn: QPushButton, hex_val: str) -> None:
    if len(hex_val) == 6:
        btn.setStyleSheet(
            f"QPushButton#ColorSwatch {{ background: #{hex_val}; border: 2px solid #444; border-radius: 6px; }}"
        )


def _copy_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(text)
