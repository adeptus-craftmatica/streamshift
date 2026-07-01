from __future__ import annotations

import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Qt, QSettings, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from stream_controller.plugins.bot_manager.bot_database import BotDatabase
from stream_controller.plugins.bot_manager.bot_engine import BotEngine
from stream_controller.plugins.bot_manager.bot_models import (
    BotActivity,
    BotCommand,
    BotConfig,
    BotRunState,
    DiscordRoute,
    EventResponse,
    RewardSelection,
    TimedMessage,
)
from stream_controller.plugins.bot_manager.bot_repository import BotRepository
from stream_controller.constants import BOT_OAUTH_PORT as _OAUTH_PORT

# ─────────────────────────── helpers ────────────────────────────


def _make_card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    return frame, layout


def _make_field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("MusicFieldLabel")
    return lbl


def _make_pill_toggle() -> QPushButton:
    """ON/OFF pill toggle button — drop-in replacement for QCheckBox."""
    btn = QPushButton("OFF")
    btn.setCheckable(True)
    btn.setFixedHeight(26)
    btn.setMinimumWidth(54)
    btn.setStyleSheet(
        "QPushButton{"
        "  border-radius:13px; font-size:10px; font-weight:700;"
        "  padding:0 12px; background:#1e293b; color:#64748b; border:1px solid #334155;"
        "}"
        "QPushButton:checked{"
        "  background:#166534; color:#22c55e; border:1px solid #22c55e;"
        "}"
    )
    btn.toggled.connect(lambda checked, b=btn: b.setText("ON" if checked else "OFF"))
    return btn


def _status_dot(connected: bool | None = None) -> QLabel:
    dot = QLabel("●")
    if connected is True:
        dot.setStyleSheet("color:#22c55e;")
    elif connected is False:
        dot.setStyleSheet("color:#ef4444;")
    else:
        dot.setStyleSheet("color:#64748b;")
    return dot


def _kind_color(kind: str) -> str:
    return {
        "command": "#7c3aed",
        "timed": "#3b82f6",
        "event": "#f59e0b",
        "system": "#64748b",
    }.get(kind, "#64748b")


# ─────────────────────────── BotSidebarItem ─────────────────────


class BotSidebarItem(QFrame):
    selected = Signal(str)  # bot_id
    toggle_enabled = Signal(str, bool)  # bot_id, enabled

    def __init__(self, bot: BotConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bot_id = bot.bot_id
        self._active = False
        self.setObjectName("SidebarItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        self._apply_style(False)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        self._icon_lbl = QLabel(bot.icon or "🤖")
        self._icon_lbl.setFixedSize(28, 28)
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet("font-size:20px;")
        root.addWidget(self._icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._name_lbl = QLabel(bot.name)
        self._name_lbl.setStyleSheet("font-weight:600; font-size:13px;")
        self._chan_lbl = QLabel(f"#{bot.twitch_channel}" if bot.twitch_channel else "No channel")
        self._chan_lbl.setStyleSheet("font-size:11px; color:#64748b;")
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("font-size:10px; color:#ef4444;")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.hide()
        text_col.addWidget(self._name_lbl)
        text_col.addWidget(self._chan_lbl)
        text_col.addWidget(self._status_lbl)
        root.addLayout(text_col)
        root.addStretch()

        # Connection status dot
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b; font-size:10px;")
        self._dot.setFixedWidth(14)
        root.addWidget(self._dot)

        # Enable/disable toggle — pill style ON/OFF
        self._toggle = QPushButton("ON" if bot.enabled else "OFF")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(bot.enabled)
        self._toggle.setFixedSize(38, 22)
        self._toggle.setStyleSheet(
            "QPushButton{border:1px solid #2b3948; border-radius:11px;"
            "background:#1a2535; color:#64748b; font-size:9px; font-weight:700; padding:0;}"
            "QPushButton:checked{background:#166534; border-color:#22c55e; color:#22c55e;}"
            "QPushButton:hover{border-color:#3a4c60;}"
        )
        def _on_toggle(checked: bool) -> None:
            self._toggle.setText("ON" if checked else "OFF")
            self.toggle_enabled.emit(self.bot_id, checked)
        self._toggle.clicked.connect(_on_toggle)
        root.addWidget(self._toggle)

    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "SidebarItem{border-left:3px solid #7c3aed;"
                "background:rgba(124,58,237,0.08);"
                "border-radius:4px;}"
            )
        else:
            self.setStyleSheet(
                "SidebarItem{border-left:3px solid transparent;"
                "background:transparent;"
                "border-radius:4px;}"
                "SidebarItem:hover{background:rgba(255,255,255,0.04);}"
            )

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style(active)

    def update_bot(self, bot: BotConfig) -> None:
        self._icon_lbl.setText(bot.icon or "🤖")
        self._name_lbl.setText(bot.name)
        self._chan_lbl.setText(f"#{bot.twitch_channel}" if bot.twitch_channel else "No channel")
        self._toggle.setChecked(bot.enabled)
        self._toggle.setText("ON" if bot.enabled else "OFF")

    def update_state(self, state: BotRunState) -> None:
        if state.twitch_connected or state.discord_connected:
            self._dot.setStyleSheet("color:#22c55e; font-size:10px;")
            self._status_lbl.hide()
        else:
            self._dot.setStyleSheet("color:#64748b; font-size:10px;")
            msg = state.status_message or ""
            _clean = msg.lower().rstrip(".…!").strip()
            if msg and _clean not in ("disconnected", "connecting", "connected", ""):
                self._status_lbl.setText(msg)
                self._status_lbl.show()
                self.setFixedHeight(80)
            else:
                self._status_lbl.hide()
                self.setFixedHeight(64)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.bot_id)
        super().mousePressEvent(event)


# ─────────────────────────── CommandRow ─────────────────────────


class CommandRow(QFrame):
    edit_requested = Signal(object)   # BotCommand
    delete_requested = Signal(str)    # command_id
    toggle_requested = Signal(str, bool)  # command_id, enabled

    def __init__(self, cmd: BotCommand, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cmd = cmd
        self.setObjectName("Card")
        self.setStyleSheet("#Card{margin:0;padding:0;}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        trigger_lbl = QLabel(cmd.trigger if cmd.trigger.startswith("!") else f"!{cmd.trigger}")
        trigger_lbl.setStyleSheet(
            "font-family:monospace; font-size:13px; color:#7c3aed; font-weight:600;"
        )
        trigger_lbl.setFixedWidth(130)
        layout.addWidget(trigger_lbl)

        if cmd.command_type == "list":
            preview = f"[List] {cmd.list_title or ''} ({len(cmd.list_items)} items)"
        else:
            preview = cmd.response[:60] + ("…" if len(cmd.response) > 60 else "")
        resp_lbl = QLabel(preview)
        resp_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        resp_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(resp_lbl)

        cd_lbl = QLabel(f"{cmd.cooldown_seconds}s")
        cd_lbl.setStyleSheet("font-size:11px; color:#64748b;")
        cd_lbl.setFixedWidth(36)
        layout.addWidget(cd_lbl)

        if cmd.is_builtin:
            badge = QLabel("BUILT-IN")
            badge.setStyleSheet(
                "background:#1e293b; color:#64748b; font-size:9px;"
                "padding:2px 5px; border-radius:3px;"
            )
            layout.addWidget(badge)

        toggle = _make_pill_toggle()
        toggle.setChecked(cmd.enabled)
        toggle.setToolTip("Turn this command ON or OFF — when OFF the bot ignores it")
        toggle.clicked.connect(lambda checked: self.toggle_requested.emit(cmd.command_id, checked))
        layout.addWidget(toggle)

        edit_btn = QPushButton("✏ Edit")
        edit_btn.setObjectName("StageToolbarBtn")
        edit_btn.setFixedHeight(26)
        edit_btn.setToolTip("Edit the trigger word, response text, and cooldown for this command")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.cmd))
        layout.addWidget(edit_btn)

        if not cmd.is_builtin:
            del_btn = QPushButton("🗑 Delete")
            del_btn.setObjectName("StageToolbarBtn")
            del_btn.setFixedHeight(26)
            del_btn.setStyleSheet("color:#ef4444;")
            del_btn.setToolTip("Permanently delete this command — cannot be undone")
            del_btn.clicked.connect(lambda: self.delete_requested.emit(cmd.command_id))
            layout.addWidget(del_btn)


# ─────────────────────────── TimedMessageRow ────────────────────


class TimedMessageRow(QFrame):
    edit_requested = Signal(object)
    delete_requested = Signal(str)
    toggle_requested = Signal(str, bool)

    def __init__(self, msg: TimedMessage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.msg = msg
        self.setObjectName("Card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        # Left column: message preview + metadata badges
        info = QVBoxLayout()
        info.setSpacing(3)

        text_lbl = QLabel(msg.message[:80] + ("…" if len(msg.message) > 80 else ""))
        text_lbl.setStyleSheet("font-size:12px; color:#e2e8f0;")
        text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info.addWidget(text_lbl)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        interval_badge = QLabel(f"⏱ every {msg.interval_minutes} min")
        interval_badge.setStyleSheet(
            "background:#1e3a5f; color:#60a5fa; font-size:10px;"
            "padding:2px 7px; border-radius:4px;"
        )
        meta_row.addWidget(interval_badge)

        if msg.only_when_active:
            live_badge = QLabel("📡 live only")
            live_badge.setStyleSheet(
                "background:#3b0764; color:#c084fc; font-size:10px;"
                "padding:2px 7px; border-radius:4px;"
            )
            meta_row.addWidget(live_badge)

        meta_row.addStretch()
        info.addLayout(meta_row)
        layout.addLayout(info)

        # Right controls: ON/OFF pill + edit + delete
        toggle = _make_pill_toggle()
        toggle.setChecked(msg.enabled)
        toggle.setToolTip("Turn this timed message ON or OFF — when OFF it will never be sent")
        toggle.clicked.connect(lambda checked: self.toggle_requested.emit(msg.msg_id, checked))
        layout.addWidget(toggle)

        edit_btn = QPushButton("✏ Edit")
        edit_btn.setObjectName("StageToolbarBtn")
        edit_btn.setFixedHeight(28)
        edit_btn.setToolTip("Edit the message text, interval, and active-only setting")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.msg))
        layout.addWidget(edit_btn)

        del_btn = QPushButton("🗑 Delete")
        del_btn.setObjectName("StageToolbarBtn")
        del_btn.setFixedHeight(28)
        del_btn.setStyleSheet("color:#ef4444;")
        del_btn.setToolTip("Permanently delete this timed message — cannot be undone")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(msg.msg_id))
        layout.addWidget(del_btn)


# ─────────────────────────── ActivityEntry ──────────────────────


class ActivityEntry(QWidget):
    def __init__(self, activity: BotActivity, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        ts = datetime.fromtimestamp(activity.ts).strftime("%H:%M:%S")
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet("font-family:monospace; font-size:11px; color:#475569;")
        ts_lbl.setFixedWidth(60)
        layout.addWidget(ts_lbl)

        color = _kind_color(activity.kind)
        kind_lbl = QLabel(activity.kind.upper())
        kind_lbl.setStyleSheet(
            f"background:{color}22; color:{color}; font-size:9px;"
            "padding:2px 5px; border-radius:3px; font-weight:600;"
        )
        kind_lbl.setFixedWidth(70)
        layout.addWidget(kind_lbl)

        text_lbl = QLabel(activity.text)
        text_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(text_lbl)


# ─────────────────────────── Tab: General ───────────────────────


class GeneralTab(QScrollArea):
    save_requested = Signal(object)   # BotConfig
    delete_requested = Signal(str)    # bot_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._bot: BotConfig | None = None
        self._oauth_server: HTTPServer | None = None

        container = QWidget()
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # ── Identity card ──
        id_card, id_lay = _make_card()
        id_title = QLabel("Bot Identity")
        id_title.setObjectName("CardTitle")
        id_lay.addWidget(id_title)

        id_lay.addWidget(_make_field_label("Bot Name"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("My Awesome Bot")
        id_lay.addWidget(self._name)

        id_lay.addWidget(_make_field_label("Icon (emoji)"))
        self._icon = QLineEdit()
        self._icon.setPlaceholderText("🤖")
        self._icon.setMaxLength(4)
        self._icon.setFixedWidth(60)
        id_lay.addWidget(self._icon)

        bot_en_row = QHBoxLayout()
        bot_en_lbl = QLabel("Bot Enabled")
        bot_en_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        bot_en_row.addWidget(bot_en_lbl)
        bot_en_row.addStretch()
        self._enabled_cb = _make_pill_toggle()
        self._enabled_cb.setToolTip(
            "Controls whether this bot is allowed to connect.\n"
            "You can also toggle this from the sidebar."
        )
        bot_en_row.addWidget(self._enabled_cb)
        id_lay.addLayout(bot_en_row)
        bot_en_desc = QLabel("When ON the bot will connect to Twitch/Discord when you save or toggle it in the sidebar.")
        bot_en_desc.setStyleSheet("font-size:10px; color:#475569;")
        bot_en_desc.setWordWrap(True)
        id_lay.addWidget(bot_en_desc)
        root.addWidget(id_card)

        # ── Twitch Setup card ──
        tw_card, tw_lay = _make_card()
        tw_title = QLabel("Twitch Setup")
        tw_title.setObjectName("CardTitle")
        tw_lay.addWidget(tw_title)

        tw_step1 = QLabel("Step 1 — Create a bot account")
        tw_step1.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:4px;")
        tw_lay.addWidget(tw_step1)
        tw_info1 = QLabel(
            "Go to twitch.tv and sign up for a second account to use as your bot "
            "(e.g. MyChannelBot). This keeps your bot separate from your streamer account."
        )
        tw_info1.setObjectName("CardDescription")
        tw_info1.setWordWrap(True)
        tw_lay.addWidget(tw_info1)

        tw_step2 = QLabel("Step 2 — Register an app and get a Client ID")
        tw_step2.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:8px;")
        tw_lay.addWidget(tw_step2)
        tw_info2 = QLabel(
            "Log into the Twitch Dev Console as your bot account. Create a new application — "
            "set the OAuth redirect URL to http://localhost:47896/callback and category to Chat Bot. "
            "Copy the Client ID and paste it below."
        )
        tw_info2.setObjectName("CardDescription")
        tw_info2.setWordWrap(True)
        tw_lay.addWidget(tw_info2)
        tw_dev_link = QLabel('<a href="https://dev.twitch.tv/console/apps/create" style="color:#3b82f6;">→ Open Twitch Dev Console</a>')
        tw_dev_link.setOpenExternalLinks(True)
        tw_lay.addWidget(tw_dev_link)

        # Copyable redirect URI row
        redirect_label = QLabel("OAuth Redirect URL to paste into Dev Console:")
        redirect_label.setStyleSheet("font-size:11px; color:#64748b; margin-top:6px;")
        tw_lay.addWidget(redirect_label)
        redirect_row = QHBoxLayout()
        redirect_row.setSpacing(6)
        _REDIRECT_URI = f"http://localhost:{_OAUTH_PORT}/callback"
        redirect_uri_lbl = QLabel(_REDIRECT_URI)
        redirect_uri_lbl.setStyleSheet(
            "font-family: monospace; font-size:12px; color:#94a3b8;"
            "background:#0a1520; border:1px solid #1e293b; border-radius:6px;"
            "padding: 4px 10px;"
        )
        redirect_uri_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        redirect_row.addWidget(redirect_uri_lbl)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("StageToolbarBtn")
        copy_btn.setFixedWidth(54)
        copy_btn.setFixedHeight(28)
        def _copy_redirect():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(_REDIRECT_URI)
            copy_btn.setText("✓")
            QTimer.singleShot(1500, lambda: copy_btn.setText("Copy"))
        copy_btn.clicked.connect(_copy_redirect)
        redirect_row.addWidget(copy_btn)
        redirect_row.addStretch()
        tw_lay.addLayout(redirect_row)

        tw_step3 = QLabel("Step 3 — Generate your OAuth token")
        tw_step3.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:8px;")
        tw_lay.addWidget(tw_step3)
        tw_info3 = QLabel(
            "Fill in your Channel, Bot Username, and Client ID below, then click "
            "\"Authorize Bot\" — StreamShift will open Twitch in your browser and catch the token automatically. "
            "Alternatively use the Twitch Token Generator (third-party) while logged in as the bot account."
        )
        tw_info3.setObjectName("CardDescription")
        tw_info3.setWordWrap(True)
        tw_lay.addWidget(tw_info3)
        tw_token_link = QLabel('<a href="https://twitchtokengenerator.com/" style="color:#3b82f6;">→ Twitch Token Generator (third-party alternative)</a>')
        tw_token_link.setOpenExternalLinks(True)
        tw_lay.addWidget(tw_token_link)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1e293b;")
        tw_lay.addWidget(sep)

        tw_lay.addWidget(_make_field_label("Your Channel (to join)"))
        self._twitch_channel = QLineEdit()
        self._twitch_channel.setPlaceholderText("your_channel_name")
        tw_lay.addWidget(self._twitch_channel)

        tw_lay.addWidget(_make_field_label("Bot Username"))
        self._twitch_username = QLineEdit()
        self._twitch_username.setPlaceholderText("your_bot_account_name")
        tw_lay.addWidget(self._twitch_username)

        tw_lay.addWidget(_make_field_label("Client ID"))
        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText("from Twitch Dev Console")
        tw_lay.addWidget(self._client_id)

        tw_lay.addWidget(_make_field_label("OAuth Token"))
        oauth_row = QHBoxLayout()
        self._oauth_token = QLineEdit()
        self._oauth_token.setPlaceholderText("oauth:xxxxxxxxxxxxxxx  (auto-filled after Authorize)")
        self._oauth_token.setEchoMode(QLineEdit.Password)
        oauth_row.addWidget(self._oauth_token)
        show_oauth = QPushButton("👁")
        show_oauth.setObjectName("StageToolbarBtn")
        show_oauth.setFixedSize(30, 30)
        show_oauth.setCheckable(True)
        show_oauth.toggled.connect(
            lambda checked: self._oauth_token.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        oauth_row.addWidget(show_oauth)
        tw_lay.addLayout(oauth_row)

        auth_btn = QPushButton("Authorize Bot")
        auth_btn.setObjectName("StagePrimaryBtn")
        auth_btn.clicked.connect(self._authorize_twitch)
        tw_lay.addWidget(auth_btn)

        tw_step4 = QLabel("Step 4 — Authorize broadcaster account (for channel points)")
        tw_step4.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:8px;")
        tw_lay.addWidget(tw_step4)
        tw_info4 = QLabel(
            "To track channel point redemptions, authorize your main broadcaster account "
            "(not the bot account). Required scopes: channel points, follows, subs, and bits. "
            "This is separate from the bot token above."
        )
        tw_info4.setObjectName("CardDescription")
        tw_info4.setWordWrap(True)
        tw_lay.addWidget(tw_info4)

        auth_bc_btn = QPushButton("🔑 Authorize Broadcaster Account")
        auth_bc_btn.setObjectName("StagePrimaryBtn")
        auth_bc_btn.clicked.connect(self._authorize_broadcaster)
        tw_lay.addWidget(auth_bc_btn)

        self._broadcaster_token_status = QLabel("")
        self._broadcaster_token_status.setStyleSheet("font-size:10px; color:#22c55e;")
        tw_lay.addWidget(self._broadcaster_token_status)

        root.addWidget(tw_card)

        # ── Discord Setup card ──
        dc_card, dc_lay = _make_card()
        dc_title = QLabel("Discord Setup")
        dc_title.setObjectName("CardTitle")
        dc_lay.addWidget(dc_title)

        dc_step1 = QLabel("Step 1 — Create a Discord application")
        dc_step1.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:4px;")
        dc_lay.addWidget(dc_step1)
        dc_info1 = QLabel(
            "Open the Discord Developer Portal and click New Application. "
            "Give it a name, then go to the Bot section and click Add Bot. "
            "Copy the Application ID from the General Information tab — you'll need it below."
        )
        dc_info1.setObjectName("CardDescription")
        dc_info1.setWordWrap(True)
        dc_lay.addWidget(dc_info1)
        dc_link = QLabel('<a href="https://discord.com/developers/applications" style="color:#3b82f6;">→ Open Discord Developer Portal</a>')
        dc_link.setOpenExternalLinks(True)
        dc_lay.addWidget(dc_link)

        dc_step2 = QLabel("Step 2 — Configure the Bot & enable intents")
        dc_step2.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:8px;")
        dc_lay.addWidget(dc_step2)
        dc_info2 = QLabel(
            "In the Developer Portal, click Bot in the left sidebar, then:\n"
            "  1. Click Reset Token — copy it and paste it into the Bot Token field below.\n"
            "  2. Scroll to Privileged Gateway Intents and turn ON all three:\n"
            "       • Presence Intent\n"
            "       • Server Members Intent\n"
            "       • Message Content Intent  ← required or the bot will disconnect immediately\n"
            "  3. Click Save Changes."
        )
        dc_info2.setObjectName("CardDescription")
        dc_info2.setWordWrap(True)
        dc_lay.addWidget(dc_info2)

        dc_step3 = QLabel("Step 3 — Invite the bot to your server")
        dc_step3.setStyleSheet("font-size:12px; font-weight:700; color:#94a3b8; margin-top:8px;")
        dc_lay.addWidget(dc_step3)
        dc_info3 = QLabel(
            "Enter your Application ID below, then click Invite Bot to Server. "
            "Select your server and confirm."
        )
        dc_info3.setObjectName("CardDescription")
        dc_info3.setWordWrap(True)
        dc_lay.addWidget(dc_info3)

        dc_sep = QFrame()
        dc_sep.setFrameShape(QFrame.HLine)
        dc_sep.setStyleSheet("color:#1e293b;")
        dc_lay.addWidget(dc_sep)

        dc_en_row = QHBoxLayout()
        dc_en_lbl = QLabel("Discord Enabled")
        dc_en_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        dc_en_row.addWidget(dc_en_lbl)
        dc_en_row.addStretch()
        self._discord_enabled = _make_pill_toggle()
        self._discord_enabled.setToolTip(
            "Turn ON to connect this bot to the Discord gateway.\n"
            "Requires a valid Bot Token above."
        )
        dc_en_row.addWidget(self._discord_enabled)
        dc_lay.addLayout(dc_en_row)
        dc_en_desc = QLabel("When ON the bot connects to Discord and can post messages + respond to commands there.")
        dc_en_desc.setStyleSheet("font-size:10px; color:#475569;")
        dc_en_desc.setWordWrap(True)
        dc_lay.addWidget(dc_en_desc)

        dc_lay.addWidget(_make_field_label("Application ID"))
        self._discord_client_id = QLineEdit()
        self._discord_client_id.setPlaceholderText("from General Information tab")
        dc_lay.addWidget(self._discord_client_id)

        dc_lay.addWidget(_make_field_label("Bot Token"))
        token_row = QHBoxLayout()
        self._discord_token = QLineEdit()
        self._discord_token.setPlaceholderText("from Bot tab → Reset Token")
        self._discord_token.setEchoMode(QLineEdit.Password)
        token_row.addWidget(self._discord_token)
        show_dc = QPushButton("👁")
        show_dc.setObjectName("StageToolbarBtn")
        show_dc.setFixedSize(30, 30)
        show_dc.setCheckable(True)
        show_dc.toggled.connect(
            lambda checked: self._discord_token.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        token_row.addWidget(show_dc)
        dc_lay.addLayout(token_row)

        dc_lay.addWidget(_make_field_label("Server ID (Guild ID)"))
        self._guild_id = QLineEdit()
        self._guild_id.setPlaceholderText("Right-click your server → Copy Server ID")
        dc_lay.addWidget(self._guild_id)

        dc_lay.addWidget(_make_field_label("Announcement Channel ID"))
        self._announce_channel = QLineEdit()
        self._announce_channel.setPlaceholderText("Right-click the channel → Copy Channel ID")
        dc_lay.addWidget(self._announce_channel)

        invite_btn = QPushButton("Invite Bot to Server")
        invite_btn.setObjectName("StagePrimaryBtn")
        invite_btn.clicked.connect(self._invite_discord)
        dc_lay.addWidget(invite_btn)
        root.addWidget(dc_card)

        # ── Settings card ──
        s_card, s_lay = _make_card()
        s_title = QLabel("Extra Settings")
        s_title.setObjectName("CardTitle")
        s_lay.addWidget(s_title)

        s_lay.addWidget(_make_field_label("Discord URL"))
        self._discord_url = QLineEdit()
        self._discord_url.setPlaceholderText("https://discord.gg/...")
        s_lay.addWidget(self._discord_url)

        s_lay.addWidget(_make_field_label("Merch URL"))
        self._merch_url = QLineEdit()
        self._merch_url.setPlaceholderText("https://yourshop.com")
        s_lay.addWidget(self._merch_url)

        s_lay.addWidget(_make_field_label("Socials"))
        self._socials = QLineEdit()
        self._socials.setPlaceholderText("@yourhandle")
        s_lay.addWidget(self._socials)
        root.addWidget(s_card)

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Changes")
        save_btn.setObjectName("StagePrimaryBtn")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()

        del_btn = QPushButton("Delete Bot")
        del_btn.setStyleSheet("color:#ef4444; font-weight:600;")
        del_btn.setFlat(True)
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def load_bot(self, bot: BotConfig) -> None:
        self._bot = bot
        self._name.setText(bot.name)
        self._icon.setText(bot.icon or "🤖")
        self._enabled_cb.setChecked(bot.enabled)
        self._twitch_channel.setText(bot.twitch_channel or "")
        self._twitch_username.setText(bot.twitch_bot_username or "")
        self._oauth_token.setText(bot.twitch_oauth_token or "")
        self._client_id.setText(bot.twitch_client_id or "")
        self._discord_enabled.setChecked(bot.discord_enabled)
        self._discord_client_id.setText(bot.discord_client_id or "")
        self._discord_token.setText(bot.discord_bot_token or "")
        self._guild_id.setText(bot.discord_guild_id or "")
        self._announce_channel.setText(bot.discord_announce_channel_id or "")
        self._discord_url.setText(bot.discord_url or "")
        self._merch_url.setText(bot.merch_url or "")
        self._socials.setText(bot.socials or "")
        bc_token = getattr(bot, "twitch_broadcaster_token", "")
        if hasattr(self, "_broadcaster_token_status"):
            self._broadcaster_token_status.setText("✓ Broadcaster token saved" if bc_token else "")

    def _on_save(self) -> None:
        if not self._bot:
            return
        self._bot.name = self._name.text().strip() or self._bot.name
        self._bot.icon = self._icon.text().strip() or "🤖"
        self._bot.enabled = self._enabled_cb.isChecked()
        self._bot.twitch_channel = self._twitch_channel.text().strip()
        self._bot.twitch_bot_username = self._twitch_username.text().strip()
        self._bot.twitch_oauth_token = self._oauth_token.text().strip()
        self._bot.twitch_client_id = self._client_id.text().strip()
        self._bot.discord_enabled = self._discord_enabled.isChecked()
        self._bot.discord_client_id = self._discord_client_id.text().strip()
        self._bot.discord_bot_token = self._discord_token.text().strip()
        self._bot.discord_guild_id = self._guild_id.text().strip()
        self._bot.discord_announce_channel_id = self._announce_channel.text().strip()
        self._bot.discord_url = self._discord_url.text().strip()
        self._bot.merch_url = self._merch_url.text().strip()
        self._bot.socials = self._socials.text().strip()
        self.save_requested.emit(self._bot)

    def _on_delete(self) -> None:
        if not self._bot:
            return
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete Bot",
            f"Are you sure you want to delete \"{self._bot.name}\"?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(self._bot.bot_id)

    def _authorize_twitch(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        client_id = self._client_id.text().strip()
        if not client_id:
            QMessageBox.warning(
                self, "Client ID Required",
                "Please enter your Client ID from the Twitch Dev Console before authorizing.",
            )
            return

        redirect_uri = f"http://localhost:{_OAUTH_PORT}/callback"

        # HTML page served at /callback — browser-side JS extracts the token
        # from the URL fragment (Twitch implicit grant puts it there, not in the
        # query string, so the server itself never sees it).
        _CALLBACK_HTML = f"""<!DOCTYPE html>
<html>
<head>
  <title>StreamShift — Twitch Authorization</title>
  <style>
    body {{ font-family: sans-serif; background: #0e1a26; color: #e2eaf2;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; }}
    .box {{ text-align: center; padding: 40px; }}
    h2 {{ font-size: 24px; margin-bottom: 12px; }}
    p  {{ color: #94a3b8; }}
  </style>
</head>
<body>
<div class="box" id="msg">
  <h2>Authorizing...</h2>
  <p>Sending token to StreamShift.</p>
</div>
<script>
  const hash   = location.hash.substring(1);
  const params = new URLSearchParams(hash);
  const token  = params.get('access_token');
  if (token) {{
    fetch('/oauth-token?t=' + encodeURIComponent(token))
      .then(() => {{
        document.getElementById('msg').innerHTML =
          '<h2>✓ Authorized!</h2><p>You can close this tab and return to StreamShift.</p>';
      }});
  }} else {{
    document.getElementById('msg').innerHTML =
      '<h2>Authorization failed</h2><p>No token received. Please try again.</p>';
  }}
</script>
</body>
</html>"""

        # Signal bridge: lets the background HTTP thread safely update the Qt field.
        class _Bridge(QObject):
            token_ready = Signal(str)

        bridge = _Bridge()
        bridge.token_ready.connect(self._on_oauth_token_received)

        server_holder: list[HTTPServer] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/callback":
                    body = _CALLBACK_HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/oauth-token"):
                    token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
                    if token:
                        bridge.token_ready.emit("oauth:" + token)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    def _shutdown():
                        server_holder[0].shutdown()
                    threading.Thread(target=_shutdown, daemon=True).start()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass  # suppress console noise

        # Shut down any previous OAuth server before binding the port again.
        if self._oauth_server is not None:
            threading.Thread(target=self._oauth_server.shutdown, daemon=True).start()
            self._oauth_server = None

        try:
            class _ReuseServer(HTTPServer):
                allow_reuse_address = True
            srv = _ReuseServer(("localhost", _OAUTH_PORT), _Handler)
        except OSError:
            QMessageBox.warning(
                self, "Port In Use",
                f"Port {_OAUTH_PORT} is still in use by another process. "
                "Restart StreamShift and try again.",
            )
            return

        self._oauth_server = srv
        server_holder.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        url = (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=token"
            f"&scope=chat%3Aread+chat%3Aedit+moderator%3Aread%3Afollowers"
        )
        webbrowser.open(url)

    def _on_oauth_token_received(self, token: str) -> None:
        self._oauth_server = None
        self._oauth_token.setText(token)
        # Auto-save immediately so the token reaches the keychain without
        # requiring the user to manually click Save Changes.
        self._on_save()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Authorized",
            "Twitch token received and saved. Your bot is ready — enable it in the sidebar.",
        )

    def _authorize_broadcaster(self) -> None:
        if not self._bot:
            return
        client_id = self._client_id.text().strip()
        if not client_id:
            self._broadcaster_token_status.setText("Enter Client ID first.")
            return
        redirect = f"http://localhost:{_OAUTH_PORT}/callback"
        scope = "channel:read:redemptions+moderator:read:followers+channel:read:subscriptions+bits:read"
        url = (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect}"
            f"&response_type=token"
            f"&scope={scope}"
        )
        # Kill any existing OAuth server
        if hasattr(self, "_oauth_server") and self._oauth_server:
            try:
                self._oauth_server.shutdown()
            except Exception:
                pass
            self._oauth_server = None

        class _BroadcasterBridge(QObject):
            token_ready = Signal(str)

        bridge = _BroadcasterBridge()
        bridge.token_ready.connect(self._on_broadcaster_token_received)

        server_holder: list[HTTPServer] = []

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/callback":
                    html = (
                        b"<html><body><script>"
                        b"var t=location.hash.replace('#','').split('&')"
                        b".find(function(p){return p.startsWith('access_token=');});"
                        b"if(t){fetch('/bc-token?'+t).then(function(){document.write('Token captured! Return to StreamShift.')})}"
                        b"else{document.write('No token found.');}"
                        b"</script></body></html>"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html)
                elif self.path.startswith("/bc-token"):
                    params = parse_qs(urlparse(self.path).query)
                    tok = params.get("access_token", [""])[0]
                    if tok:
                        bridge.token_ready.emit(tok)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    def _shutdown():
                        server_holder[0].shutdown()
                    threading.Thread(target=_shutdown, daemon=True).start()
                else:
                    self.send_response(404)
                    self.end_headers()

        try:
            class _ReuseServer(HTTPServer):
                allow_reuse_address = True
            srv = _ReuseServer(("localhost", _OAUTH_PORT), _Handler)
        except OSError:
            self._broadcaster_token_status.setText(f"Port {_OAUTH_PORT} in use — restart StreamShift and try again.")
            return

        self._oauth_server = srv
        server_holder.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        webbrowser.open(url)
        self._broadcaster_token_status.setText("Waiting for authorization… (browser should open)")

    def _on_broadcaster_token_received(self, token: str) -> None:
        self._oauth_server = None
        if self._bot:
            self._bot.twitch_broadcaster_token = token
            self._broadcaster_token_status.setText("✓ Broadcaster token captured — click Save Changes to store it.")
            self._on_save()

    def _invite_discord(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        client_id = self._discord_client_id.text().strip()
        if not client_id:
            QMessageBox.warning(
                self, "Application ID Required",
                "Please enter your Discord Application ID first.\n"
                "Find it in the General Information tab of your application on the Developer Portal.",
            )
            return
        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&permissions=274878024704"
            f"&scope=bot+applications.commands"
        )
        webbrowser.open(url)


# ─────────────────────────── Tab: Commands ──────────────────────


class CommandsTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db: BotDatabase | None = None
        self._bot_id: str | None = None
        self._editing_cmd: BotCommand | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("＋ Add Command")
        add_btn.setObjectName("StagePrimaryBtn")
        add_btn.clicked.connect(self._add_command)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search commands…")
        self._search.setFixedWidth(200)
        self._search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search)
        root.addLayout(toolbar)

        # Scrollable list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        list_widget = QWidget()
        self._list_layout = QVBoxLayout(list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(list_widget)
        root.addWidget(scroll)

        # Inline editor (hidden by default)
        self._editor_frame, ed_lay = _make_card()
        ed_title = QLabel("Edit Command")
        ed_title.setObjectName("CardTitle")
        ed_lay.addWidget(ed_title)

        ed_lay.addWidget(_make_field_label("Trigger (without !)"))
        self._ed_trigger = QLineEdit()
        self._ed_trigger.setPlaceholderText("command")
        ed_lay.addWidget(self._ed_trigger)

        # Command type selector
        type_row = QHBoxLayout()
        type_lbl = QLabel("Type")
        type_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        type_row.addWidget(type_lbl)
        type_row.addStretch()
        self._ed_type = QComboBox()
        self._ed_type.addItem("Text response", "text")
        self._ed_type.addItem("List (items shown in chat)", "list")
        self._ed_type.currentIndexChanged.connect(self._on_type_changed)
        self._ed_type.setFixedWidth(220)
        type_row.addWidget(self._ed_type)
        ed_lay.addLayout(type_row)

        # Text response section
        self._ed_text_section = QWidget()
        text_sec_lay = QVBoxLayout(self._ed_text_section)
        text_sec_lay.setContentsMargins(0, 0, 0, 0)
        text_sec_lay.setSpacing(4)
        text_sec_lay.addWidget(_make_field_label("Response"))
        self._ed_response = QTextEdit()
        self._ed_response.setFixedHeight(80)
        text_sec_lay.addWidget(self._ed_response)
        hints = QLabel("Variables: {user} {channel} {uptime} {count} {commands} {discord_url} {merch_url} {input}")
        hints.setStyleSheet("font-size:10px; color:#475569;")
        hints.setWordWrap(True)
        text_sec_lay.addWidget(hints)
        ed_lay.addWidget(self._ed_text_section)

        # List section
        self._ed_list_section = QWidget()
        list_sec_lay = QVBoxLayout(self._ed_list_section)
        list_sec_lay.setContentsMargins(0, 0, 0, 0)
        list_sec_lay.setSpacing(4)
        list_sec_lay.addWidget(_make_field_label("List Title (shown in chat)"))
        self._ed_list_title = QLineEdit()
        self._ed_list_title.setPlaceholderText("e.g. Primed Models Available")
        list_sec_lay.addWidget(self._ed_list_title)
        list_sec_lay.addWidget(_make_field_label("List Items (one per line)"))
        self._ed_list_items = QTextEdit()
        self._ed_list_items.setFixedHeight(100)
        self._ed_list_items.setPlaceholderText("Mechanicus Skitarii\nAdeptus Custodes\n…")
        list_sec_lay.addWidget(self._ed_list_items)
        list_sec_lay.addWidget(_make_field_label("Triggered by Channel Points reward name (optional)"))
        self._ed_linked_reward = QLineEdit()
        self._ed_linked_reward.setPlaceholderText("e.g. Praise the Omnissiah")
        list_sec_lay.addWidget(self._ed_linked_reward)
        list_sec_lay.addWidget(_make_field_label("Triggered by minimum bits (0 = disabled)"))
        self._ed_linked_bits = QSpinBox()
        self._ed_linked_bits.setRange(0, 1000000)
        self._ed_linked_bits.setSingleStep(100)
        list_sec_lay.addWidget(self._ed_linked_bits)
        ed_lay.addWidget(self._ed_list_section)
        self._ed_list_section.setVisible(False)

        ed_lay.addWidget(_make_field_label("Cooldown (seconds)"))
        self._ed_cooldown = QSpinBox()
        self._ed_cooldown.setRange(0, 3600)
        ed_lay.addWidget(self._ed_cooldown)

        ed_en_row = QHBoxLayout()
        ed_en_lbl = QLabel("Command enabled")
        ed_en_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        ed_en_row.addWidget(ed_en_lbl)
        ed_en_row.addStretch()
        self._ed_enabled = _make_pill_toggle()
        self._ed_enabled.setToolTip("When OFF, the bot will ignore this command entirely")
        ed_en_row.addWidget(self._ed_enabled)
        ed_lay.addLayout(ed_en_row)

        ed_btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("StagePrimaryBtn")
        save_btn.clicked.connect(self._save_command)
        ed_btns.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("StageToolbarBtn")
        cancel_btn.clicked.connect(self._cancel_edit)
        ed_btns.addWidget(cancel_btn)
        ed_btns.addStretch()
        ed_lay.addLayout(ed_btns)

        self._editor_frame.setVisible(False)
        root.addWidget(self._editor_frame)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        self._bot_id = bot_id
        self._db = db
        self._refresh_list()

    def _refresh_list(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._db:
            return
        cmds = self._db.list_commands()
        q = self._search.text().lower()
        for cmd in cmds:
            if q and q not in cmd.trigger.lower() and q not in cmd.response.lower():
                continue
            row = CommandRow(cmd)
            row.edit_requested.connect(self._open_editor)
            row.delete_requested.connect(self._delete_command)
            row.toggle_requested.connect(self._toggle_command)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _on_type_changed(self) -> None:
        is_list = self._ed_type.currentData() == "list"
        self._ed_text_section.setVisible(not is_list)
        self._ed_list_section.setVisible(is_list)

    def _apply_filter(self) -> None:
        self._refresh_list()

    def _add_command(self) -> None:
        if not self._bot_id or not self._db:
            return
        new_cmd = BotCommand(
            command_id=str(uuid.uuid4()),
            bot_id=self._bot_id,
            trigger="newcommand",
            response="",
            cooldown_seconds=0,
            enabled=True,
            is_builtin=False,
        )
        self._open_editor(new_cmd)

    def _open_editor(self, cmd: BotCommand) -> None:
        self._editing_cmd = cmd
        self._ed_trigger.setText(cmd.trigger.lstrip("!"))
        self._ed_response.setPlainText(cmd.response)
        self._ed_cooldown.setValue(cmd.cooldown_seconds)
        self._ed_enabled.setChecked(cmd.enabled)
        idx = self._ed_type.findData(cmd.command_type or "text")
        self._ed_type.setCurrentIndex(max(0, idx))
        self._ed_list_title.setText(cmd.list_title or "")
        self._ed_list_items.setPlainText("\n".join(cmd.list_items or []))
        self._ed_linked_reward.setText(cmd.linked_reward or "")
        self._ed_linked_bits.setValue(cmd.linked_bits or 0)
        self._on_type_changed()
        self._editor_frame.setVisible(True)

    def _cancel_edit(self) -> None:
        self._editing_cmd = None
        self._editor_frame.setVisible(False)

    def _save_command(self) -> None:
        if not self._editing_cmd or not self._db:
            return
        raw = self._ed_trigger.text().strip().lstrip("!")
        self._editing_cmd.trigger = f"!{raw}" if raw else ""
        self._editing_cmd.command_type = self._ed_type.currentData() or "text"
        self._editing_cmd.response = self._ed_response.toPlainText()
        self._editing_cmd.list_title = self._ed_list_title.text().strip()
        items_text = self._ed_list_items.toPlainText()
        self._editing_cmd.list_items = [
            l.strip() for l in items_text.splitlines() if l.strip()
        ]
        self._editing_cmd.linked_reward = self._ed_linked_reward.text().strip()
        self._editing_cmd.linked_bits = self._ed_linked_bits.value()
        self._editing_cmd.cooldown_seconds = self._ed_cooldown.value()
        self._editing_cmd.enabled = self._ed_enabled.isChecked()
        self._db.save_command(self._editing_cmd)
        self._editor_frame.setVisible(False)
        self._editing_cmd = None
        self._refresh_list()

    def _delete_command(self, command_id: str) -> None:
        if self._db:
            self._db.delete_command(command_id)
            self._refresh_list()

    def _toggle_command(self, command_id: str, enabled: bool) -> None:
        if not self._db:
            return
        cmds = self._db.list_commands()
        for cmd in cmds:
            if cmd.command_id == command_id:
                cmd.enabled = enabled
                self._db.save_command(cmd)
                break


# ─────────────────────────── Tab: Timed Messages ────────────────


class TimedMessagesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db: BotDatabase | None = None
        self._bot_id: str | None = None
        self._editing_msg: TimedMessage | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("＋ Add Message")
        add_btn.setObjectName("StagePrimaryBtn")
        add_btn.clicked.connect(self._add_message)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        root.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        list_widget = QWidget()
        self._list_layout = QVBoxLayout(list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(list_widget)
        root.addWidget(scroll)

        # Inline editor
        self._editor_frame, ed_lay = _make_card()
        ed_title = QLabel("Edit Timed Message")
        ed_title.setObjectName("CardTitle")
        ed_lay.addWidget(ed_title)

        ed_lay.addWidget(_make_field_label("Message"))
        self._ed_message = QTextEdit()
        self._ed_message.setFixedHeight(80)
        ed_lay.addWidget(self._ed_message)

        ed_lay.addWidget(_make_field_label("Interval (minutes)"))
        self._ed_interval = QSpinBox()
        self._ed_interval.setRange(1, 1440)
        self._ed_interval.setValue(30)
        ed_lay.addWidget(self._ed_interval)

        # Only when active — labeled pill
        active_row = QHBoxLayout()
        active_lbl = QLabel("Only send when stream is active")
        active_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        active_row.addWidget(active_lbl)
        active_row.addStretch()
        self._ed_only_active = _make_pill_toggle()
        active_row.addWidget(self._ed_only_active)
        ed_lay.addLayout(active_row)

        # Enabled — labeled pill
        enabled_row = QHBoxLayout()
        enabled_lbl = QLabel("Message enabled")
        enabled_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        enabled_row.addWidget(enabled_lbl)
        enabled_row.addStretch()
        self._ed_enabled = _make_pill_toggle()
        enabled_row.addWidget(self._ed_enabled)
        ed_lay.addLayout(enabled_row)

        ed_btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("StagePrimaryBtn")
        save_btn.clicked.connect(self._save_message)
        ed_btns.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("StageToolbarBtn")
        cancel_btn.clicked.connect(self._cancel_edit)
        ed_btns.addWidget(cancel_btn)
        ed_btns.addStretch()
        ed_lay.addLayout(ed_btns)

        self._editor_frame.setVisible(False)
        root.addWidget(self._editor_frame)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        self._bot_id = bot_id
        self._db = db
        self._refresh_list()

    def _refresh_list(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._db:
            return
        for msg in self._db.list_timed_messages():
            row = TimedMessageRow(msg)
            row.edit_requested.connect(self._open_editor)
            row.delete_requested.connect(self._delete_message)
            row.toggle_requested.connect(self._toggle_message)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _add_message(self) -> None:
        if not self._bot_id or not self._db:
            return
        new_msg = TimedMessage(
            msg_id=str(uuid.uuid4()),
            bot_id=self._bot_id,
            message="",
            interval_minutes=30,
            enabled=True,
            only_when_active=True,
            last_sent_ts=0.0,
        )
        self._open_editor(new_msg)

    def _open_editor(self, msg: TimedMessage) -> None:
        self._editing_msg = msg
        self._ed_message.setPlainText(msg.message)
        self._ed_interval.setValue(msg.interval_minutes)
        self._ed_only_active.setChecked(msg.only_when_active)
        self._ed_enabled.setChecked(msg.enabled)
        self._editor_frame.setVisible(True)

    def _cancel_edit(self) -> None:
        self._editing_msg = None
        self._editor_frame.setVisible(False)

    def _save_message(self) -> None:
        if not self._editing_msg or not self._db:
            return
        self._editing_msg.message = self._ed_message.toPlainText()
        self._editing_msg.interval_minutes = self._ed_interval.value()
        self._editing_msg.only_when_active = self._ed_only_active.isChecked()
        self._editing_msg.enabled = self._ed_enabled.isChecked()
        self._db.save_timed_message(self._editing_msg)
        self._editor_frame.setVisible(False)
        self._editing_msg = None
        self._refresh_list()

    def _delete_message(self, msg_id: str) -> None:
        if self._db:
            self._db.delete_timed_message(msg_id)
            self._refresh_list()

    def _toggle_message(self, msg_id: str, enabled: bool) -> None:
        if not self._db:
            return
        for msg in self._db.list_timed_messages():
            if msg.msg_id == msg_id:
                msg.enabled = enabled
                self._db.save_timed_message(msg)
                break


# ─────────────────────────── Tab: Event Responses ───────────────

EVENT_TYPES = [
    ("sub", "🎉 New Sub", "{user} {months}"),
    ("resub", "🔄 Resub", "{user} {months}"),
    ("giftsub", "🎁 Gift Sub", "{user} {gifted}"),
    ("raid", "⚔️ Raid", "{user} {viewers}"),
    ("bits", "💎 Bits/Cheer", "{user} {amount}"),
    ("follow", "❤️ Follow", "{user}"),
]


class EventResponseCard(QFrame):
    def __init__(self, event_type: str, icon: str, variables: str, resp: EventResponse | None, db: BotDatabase, bot_id: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._db = db
        self._bot_id = bot_id
        self._event_type = event_type
        self._resp = resp
        self._expanded = False

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 14, 16, 14)
        self._root.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:18px;")
        header.addWidget(icon_lbl)

        type_lbl = QLabel(event_type.replace("giftsub", "Gift Sub").replace("bits", "Bits").title())
        type_lbl.setStyleSheet("font-weight:600; font-size:13px;")
        header.addWidget(type_lbl)
        header.addStretch()

        self._enabled_toggle = _make_pill_toggle()
        self._enabled_toggle.setChecked(resp.enabled if resp else False)
        self._enabled_toggle.setToolTip("Turn ON to make the bot post this response in chat when the event fires")
        header.addWidget(self._enabled_toggle)

        expand_btn = QPushButton("⚙ Edit")
        expand_btn.setObjectName("StageToolbarBtn")
        expand_btn.setFixedHeight(26)
        expand_btn.setToolTip("Expand to edit the response template and settings")
        expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(expand_btn)
        self._root.addLayout(header)

        # Expandable body
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 4, 0, 0)
        body_lay.setSpacing(8)

        body_lay.addWidget(_make_field_label("Response Template"))
        self._template = QTextEdit()
        self._template.setFixedHeight(60)
        self._template.setPlainText(resp.response_template if resp else "")
        body_lay.addWidget(self._template)

        vars_lbl = QLabel(f"Variables: {variables}")
        vars_lbl.setStyleSheet("font-size:10px; color:#475569;")
        body_lay.addWidget(vars_lbl)

        if event_type == "bits":
            body_lay.addWidget(_make_field_label("Minimum Bits"))
            self._min_bits = QSpinBox()
            self._min_bits.setRange(0, 100000)
            self._min_bits.setValue(resp.min_bits if resp and resp.min_bits else 0)
            body_lay.addWidget(self._min_bits)
        else:
            self._min_bits = None

        save_btn = QPushButton("Save")
        save_btn.setObjectName("StagePrimaryBtn")
        save_btn.clicked.connect(self._save)
        body_lay.addWidget(save_btn)

        self._body.setVisible(False)
        self._root.addWidget(self._body)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)

    def _save(self) -> None:
        if self._resp is None:
            self._resp = EventResponse(
                resp_id=str(uuid.uuid4()),
                bot_id=self._bot_id,
                event_type=self._event_type,
                response_template="",
                enabled=False,
                min_bits=0,
            )
        self._resp.response_template = self._template.toPlainText()
        self._resp.enabled = self._enabled_toggle.isChecked()
        if self._min_bits is not None:
            self._resp.min_bits = self._min_bits.value()
        self._db.save_event_response(self._resp)


class EventResponsesTab(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(12)
        self._layout.addStretch()
        self.setWidget(self._container)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        resps = {r.event_type: r for r in db.list_event_responses()}
        for et, icon, variables in EVENT_TYPES:
            card = EventResponseCard(et, icon, variables, resps.get(et), db, bot_id)
            self._layout.insertWidget(self._layout.count() - 1, card)


# ─────────────────────────── Tab: Activity ──────────────────────


class ActivityTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[BotActivity] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel("Recent Activity")
        title.setObjectName("CardTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("StageToolbarBtn")
        clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(clear_btn)
        root.addLayout(toolbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #94a3b8;"
            "background: #0d1117; border-radius:4px; padding:4px;"
        )

        self._feed_widget = QWidget()
        self._feed_layout = QVBoxLayout(self._feed_widget)
        self._feed_layout.setContentsMargins(4, 4, 4, 4)
        self._feed_layout.setSpacing(2)
        self._feed_layout.addStretch()
        self._scroll.setWidget(self._feed_widget)
        root.addWidget(self._scroll)

    def clear(self) -> None:
        self._entries.clear()
        while self._feed_layout.count() > 1:
            item = self._feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def update_activity(self, activities: list[BotActivity]) -> None:
        existing_ts = {a.ts for a in self._entries}
        new_entries = [a for a in activities if a.ts not in existing_ts]
        for activity in new_entries:
            self._entries.append(activity)
            entry_widget = ActivityEntry(activity)
            self._feed_layout.insertWidget(self._feed_layout.count() - 1, entry_widget)

        # Auto-scroll to bottom
        if new_entries:
            sb = self._scroll.verticalScrollBar()
            sb.setValue(sb.maximum())


# ─────────────────────────── Tab: Loyalty / User Stats ──────────


class LoyaltyTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db: BotDatabase | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        title = QLabel("Viewer Stats")
        title.setObjectName("CardTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("StageToolbarBtn")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)
        root.addLayout(toolbar)

        # Header row
        header = QFrame()
        header.setStyleSheet("background:#1e293b; border-radius:4px;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(10, 6, 10, 6)
        for col, width in [("Username", 140), ("Bits", 70), ("Subs", 60),
                            ("Gifted", 70), ("Points", 80), ("Msgs", 60), ("Last Seen", 130)]:
            lbl = QLabel(col)
            lbl.setStyleSheet("font-size:10px; font-weight:700; color:#64748b;")
            lbl.setFixedWidth(width)
            hlay.addWidget(lbl)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

        self._empty_lbl = QLabel("No viewer stats yet — stats are recorded when viewers interact during a live stream.")
        self._empty_lbl.setObjectName("CardDescription")
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._empty_lbl)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        self._db = db
        self._refresh()

    def _refresh(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._db:
            return
        try:
            stats = self._db.list_user_stats()
        except Exception:
            stats = []
        self._empty_lbl.setVisible(len(stats) == 0)
        for stat in stats:
            row = self._make_stat_row(stat)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _make_stat_row(self, stat) -> QWidget:
        row = QFrame()
        row.setObjectName("Card")
        row.setStyleSheet("QFrame#Card { padding: 4px 0; margin: 0; }")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(0)

        def cell(text: str, width: int, color: str = "#94a3b8") -> QLabel:
            lbl = QLabel(str(text))
            lbl.setStyleSheet(f"font-size:11px; color:{color};")
            lbl.setFixedWidth(width)
            return lbl

        lay.addWidget(cell(stat.username, 140, "#e2e8f0"))
        lay.addWidget(cell(f"{stat.bits_total:,}", 70, "#f59e0b" if stat.bits_total else "#475569"))
        lay.addWidget(cell(str(stat.subs_total), 60, "#22c55e" if stat.subs_total else "#475569"))
        lay.addWidget(cell(str(stat.gifted_subs_total), 70, "#a78bfa" if stat.gifted_subs_total else "#475569"))
        lay.addWidget(cell(f"{stat.channel_points_total:,}", 80, "#60a5fa" if stat.channel_points_total else "#475569"))
        lay.addWidget(cell(str(stat.messages_total), 60))
        last = datetime.fromtimestamp(stat.last_seen_ts).strftime("%m/%d %H:%M") if stat.last_seen_ts else "—"
        lay.addWidget(cell(last, 130, "#64748b"))
        return row


# ─────────────────────────── Tab: Discord Routes ────────────────

_ROUTE_EVENTS = [
    ("sub",            "🎉 New Sub"),
    ("resub",          "🔄 Resub"),
    ("subgift",        "🎁 Gifted Sub"),
    ("raid",           "⚔️ Raid"),
    ("bits",           "💎 Bits / Cheer"),
    ("channel_points", "🏆 Channel Points"),
    ("follow",         "❤️ Follow"),
    ("all",            "⭐ All Events"),
]

_ROUTE_VARS = {
    "sub":            "{user} {amount}",
    "resub":          "{user} {amount}",
    "subgift":        "{user} {amount}",
    "raid":           "{user} {amount}",
    "bits":           "{user} {amount}",
    "channel_points": "{user} {reward} {cost}",
    "follow":         "{user}",
    "all":            "{user} {amount}",
}


class DiscordRouteCard(QFrame):
    deleted = Signal(str)

    def __init__(self, route: DiscordRoute, db: BotDatabase, bot_id: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._db = db
        self._bot_id = bot_id
        self._route = route
        self._expanded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        label = dict(_ROUTE_EVENTS).get(route.event_type, route.event_type)
        title = QLabel(label)
        title.setStyleSheet("font-weight:600; font-size:13px;")
        header.addWidget(title)

        if route.channel_id:
            ch_lbl = QLabel(f"→ #{route.channel_id[:18]}")
            ch_lbl.setStyleSheet("font-size:10px; color:#60a5fa; padding: 2px 6px; background:#1e3a5f; border-radius:4px;")
            header.addWidget(ch_lbl)

        header.addStretch()

        self._pill = _make_pill_toggle()
        self._pill.setChecked(route.enabled)
        self._pill.clicked.connect(self._save)
        header.addWidget(self._pill)

        expand_btn = QPushButton("⚙ Edit")
        expand_btn.setObjectName("StageToolbarBtn")
        expand_btn.setFixedHeight(26)
        expand_btn.setToolTip("Expand to set the Discord channel ID and message template for this route")
        expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(expand_btn)

        del_btn = QPushButton("🗑 Remove")
        del_btn.setObjectName("StageToolbarBtn")
        del_btn.setFixedHeight(26)
        del_btn.setStyleSheet("color:#ef4444;")
        del_btn.setToolTip("Remove this route — the event will stop being posted to Discord")
        del_btn.clicked.connect(lambda: self.deleted.emit(route.route_id))
        header.addWidget(del_btn)

        root.addLayout(header)

        # Body
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 4, 0, 0)
        body_lay.setSpacing(8)

        body_lay.addWidget(_make_field_label("Discord Channel ID"))
        self._channel_id = QLineEdit(route.channel_id)
        self._channel_id.setPlaceholderText("Right-click channel → Copy Channel ID")
        body_lay.addWidget(self._channel_id)

        body_lay.addWidget(_make_field_label("Message Template"))
        self._template = QTextEdit()
        self._template.setFixedHeight(60)
        self._template.setPlainText(route.message_template)
        body_lay.addWidget(self._template)

        vars_hint = _ROUTE_VARS.get(route.event_type, "{user} {amount}")
        hint = QLabel(f"Variables: {vars_hint}")
        hint.setStyleSheet("font-size:10px; color:#475569;")
        body_lay.addWidget(hint)

        save_btn = QPushButton("Save Route")
        save_btn.setObjectName("StagePrimaryBtn")
        save_btn.clicked.connect(self._save)
        body_lay.addWidget(save_btn)

        self._body.setVisible(False)
        root.addWidget(self._body)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)

    def _save(self) -> None:
        self._route.channel_id = self._channel_id.text().strip()
        self._route.message_template = self._template.toPlainText()
        self._route.enabled = self._pill.isChecked()
        self._db.save_discord_route(self._route)


class DiscordRoutesTab(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._db: BotDatabase | None = None
        self._bot_id: str = ""
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(10)
        self._layout.addStretch()
        self.setWidget(self._container)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        self._bot_id = bot_id
        self._db = db
        self._refresh()

    def _refresh(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._db:
            return

        # Add button
        add_btn = QPushButton("＋ Add Discord Route")
        add_btn.setObjectName("StagePrimaryBtn")
        add_btn.clicked.connect(self._add_route)
        self._layout.insertWidget(0, add_btn)

        hint = QLabel(
            "Discord Routes send a message to a Discord channel whenever a Twitch event fires. "
            "You must have the Discord bot connected and have its Channel ID ready.\n"
            "Tip: Enable Developer Mode in Discord → User Settings → App Settings → Advanced, "
            "then right-click any channel → Copy Channel ID."
        )
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        self._layout.insertWidget(1, hint)

        for route in self._db.list_discord_routes():
            card = DiscordRouteCard(route, self._db, self._bot_id)
            card.deleted.connect(self._delete_route)
            self._layout.insertWidget(self._layout.count() - 1, card)

    def _add_route(self) -> None:
        if not self._db:
            return
        # Pick first event type not already routed
        existing = {r.event_type for r in self._db.list_discord_routes()}
        event_type = next((et for et, _ in _ROUTE_EVENTS if et not in existing), "all")
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Discord Route")
        dlg.setMinimumWidth(300)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Which event should trigger the Discord message?"))
        combo = QComboBox()
        for et, label in _ROUTE_EVENTS:
            combo.addItem(label, et)
        lay.addWidget(combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = combo.currentData()
        route = DiscordRoute(
            route_id=str(uuid.uuid4()),
            event_type=chosen,
            channel_id="",
            message_template="",
            enabled=True,
        )
        self._db.save_discord_route(route)
        self._refresh()

    def _delete_route(self, route_id: str) -> None:
        if self._db:
            self._db.delete_discord_route(route_id)
            self._refresh()


# ─────────────────────────── Bot Editor (tabbed) ────────────────


# ─────────────────────────── Tab: Redemptions ───────────────────


class RedemptionsTab(QWidget):
    """Shows reward selections (bits / channel points) made by viewers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db: BotDatabase | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        title = QLabel("Viewer Selections")
        title.setObjectName("CardTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setObjectName("StageToolbarBtn")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)
        root.addLayout(toolbar)

        info = QLabel(
            "When a viewer redeems a linked channel-point reward or donates linked bits, "
            "the bot shows them the list in chat and records their typed selection here."
        )
        info.setStyleSheet("font-size:11px; color:#64748b;")
        info.setWordWrap(True)
        root.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

    def load(self, bot_id: str, db: BotDatabase) -> None:
        self._db = db
        self._refresh()

    def _refresh(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._db:
            return
        selections = self._db.list_selections(limit=100)
        if not selections:
            empty = QLabel("No selections yet — link a list command to a channel-point reward or bits amount.")
            empty.setStyleSheet("font-size:12px; color:#64748b;")
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            return
        for sel in selections:
            row = self._make_row(sel)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _make_row(self, sel: RewardSelection) -> QFrame:
        from datetime import datetime
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        ts_str = datetime.fromtimestamp(sel.ts).strftime("%m/%d %H:%M") if sel.ts else ""
        ts_lbl = QLabel(ts_str)
        ts_lbl.setStyleSheet("font-size:10px; color:#475569;")
        ts_lbl.setFixedWidth(70)
        lay.addWidget(ts_lbl)

        user_lbl = QLabel(sel.username)
        user_lbl.setStyleSheet("font-size:12px; color:#7c3aed; font-weight:600;")
        user_lbl.setFixedWidth(110)
        lay.addWidget(user_lbl)

        reward_lbl = QLabel(sel.reward_name[:30])
        reward_lbl.setStyleSheet("font-size:11px; color:#64748b;")
        reward_lbl.setFixedWidth(150)
        lay.addWidget(reward_lbl)

        sel_lbl = QLabel(sel.selection[:80])
        sel_lbl.setStyleSheet("font-size:12px; color:#e2e8f0;")
        sel_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(sel_lbl)

        source_badge = QLabel(sel.source.upper().replace("_", " "))
        source_badge.setStyleSheet(
            "background:#1e293b; color:#38bdf8; font-size:9px; padding:2px 5px; border-radius:3px;"
        )
        lay.addWidget(source_badge)

        status_color = "#22c55e" if sel.status == "confirmed" else "#f59e0b"
        status_lbl = QLabel(sel.status.upper())
        status_lbl.setStyleSheet(
            f"background:#1e293b; color:{status_color}; font-size:9px; padding:2px 5px; border-radius:3px;"
        )
        lay.addWidget(status_lbl)

        return frame


# ─────────────────────────── BotEditorWidget ────────────────────


class BotEditorWidget(QWidget):
    save_requested = Signal(object)
    delete_requested = Signal(str)

    TABS = ["General", "Commands", "Timed Messages", "Event Responses", "Discord Routes", "Loyalty", "Redemptions", "Activity"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Tab bar
        tab_bar = QWidget()
        tab_bar.setObjectName("MusicTabBar")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(20, 12, 20, 0)
        tab_bar_layout.setSpacing(4)

        self._tab_buttons: list[QPushButton] = []
        self._stack = QStackedWidget()

        # Create tab pages
        self._general_tab = GeneralTab()
        self._general_tab.save_requested.connect(self.save_requested)
        self._general_tab.delete_requested.connect(self.delete_requested)

        self._commands_tab = CommandsTab()
        self._timed_tab = TimedMessagesTab()
        self._events_tab = EventResponsesTab()
        self._discord_routes_tab = DiscordRoutesTab()
        self._loyalty_tab = LoyaltyTab()
        self._redemptions_tab = RedemptionsTab()
        self._activity_tab = ActivityTab()

        tab_pages = [
            self._general_tab,
            self._commands_tab,
            self._timed_tab,
            self._events_tab,
            self._discord_routes_tab,
            self._loyalty_tab,
            self._redemptions_tab,
            self._activity_tab,
        ]

        saved_tab = int(QSettings("StreamShift", "StreamController").value("bot_editor/tab", 0))
        for i, (name, page) in enumerate(zip(self.TABS, tab_pages)):
            btn = QPushButton(name)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == saved_tab)
            idx = i
            btn.clicked.connect(lambda _, n=idx: self._switch_tab(n))
            tab_bar_layout.addWidget(btn)
            self._tab_buttons.append(btn)
            self._stack.addWidget(page)

        tab_bar_layout.addStretch()
        root.addWidget(tab_bar)
        self._stack.setCurrentIndex(saved_tab if 0 <= saved_tab < len(tab_pages) else 0)
        root.addWidget(self._stack)

    def _switch_tab(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)
        QSettings("StreamShift", "StreamController").setValue("bot_editor/tab", idx)

    def load_bot(self, bot: BotConfig, db: BotDatabase) -> None:
        self._general_tab.load_bot(bot)
        self._commands_tab.load(bot.bot_id, db)
        self._timed_tab.load(bot.bot_id, db)
        self._events_tab.load(bot.bot_id, db)
        self._loyalty_tab.load(bot.bot_id, db)
        self._discord_routes_tab.load(bot.bot_id, db)
        self._redemptions_tab.load(bot.bot_id, db)

    def update_activity(self, activities: list[BotActivity]) -> None:
        self._activity_tab.update_activity(activities)


# ─────────────────────────── BotManagerPage ─────────────────────


class BotManagerPage(QWidget):
    def __init__(
        self,
        repo: BotRepository,
        engines: dict[str, BotEngine],
        dbs: dict[str, BotDatabase],
        get_or_create_db: Callable | None = None,
        start_bot: Callable | None = None,
        stop_bot: Callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._engines = engines
        self._dbs = dbs
        self._get_or_create_db = get_or_create_db or (lambda bot_id: dbs.get(bot_id))
        self._start_bot = start_bot
        self._stop_bot = stop_bot
        self._selected_bot_id: str | None = None
        self._sidebar_items: dict[str, BotSidebarItem] = {}
        self._subscribed_engines: set = set()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left sidebar ──
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setObjectName("Sidebar")
        sidebar.setStyleSheet("#Sidebar{border-right:1px solid #1e293b;}")
        sidebar_root = QVBoxLayout(sidebar)
        sidebar_root.setContentsMargins(0, 0, 0, 0)
        sidebar_root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(16, 12, 16, 12)
        header_title = QLabel("🤖 Bot Manager")
        header_title.setObjectName("CardTitle")
        header_title.setStyleSheet("font-size:15px; font-weight:700;")
        header_lay.addWidget(header_title)
        header_lay.addStretch()
        sidebar_root.addWidget(header)

        # Scrollable bot list
        self._bot_scroll = QScrollArea()
        self._bot_scroll.setWidgetResizable(True)
        self._bot_scroll.setFrameShape(QFrame.NoFrame)
        self._bot_list_widget = QWidget()
        self._bot_list_layout = QVBoxLayout(self._bot_list_widget)
        self._bot_list_layout.setContentsMargins(8, 8, 8, 8)
        self._bot_list_layout.setSpacing(2)
        self._bot_list_layout.addStretch()
        self._bot_scroll.setWidget(self._bot_list_widget)
        sidebar_root.addWidget(self._bot_scroll)

        # Add Bot button
        add_btn = QPushButton("＋ Add Bot")
        add_btn.setObjectName("StagePrimaryBtn")
        add_btn.setFixedHeight(40)
        add_btn_container = QWidget()
        add_btn_lay = QHBoxLayout(add_btn_container)
        add_btn_lay.setContentsMargins(12, 8, 12, 12)
        add_btn_lay.addWidget(add_btn)
        add_btn.clicked.connect(self._add_bot)
        sidebar_root.addWidget(add_btn_container)

        root.addWidget(sidebar)

        # ── Right panel ──
        self._right_stack = QStackedWidget()

        # Welcome page
        welcome = QWidget()
        wlc_lay = QVBoxLayout(welcome)
        wlc_lay.setAlignment(Qt.AlignCenter)
        wlc_lay.setSpacing(16)
        wlc_emoji = QLabel("🤖")
        wlc_emoji.setStyleSheet("font-size:64px;")
        wlc_emoji.setAlignment(Qt.AlignCenter)
        wlc_lay.addWidget(wlc_emoji)
        wlc_title = QLabel("Welcome to Bot Manager")
        wlc_title.setObjectName("CardTitle")
        wlc_title.setStyleSheet("font-size:22px; font-weight:700;")
        wlc_title.setAlignment(Qt.AlignCenter)
        wlc_lay.addWidget(wlc_title)
        wlc_desc = QLabel(
            "Automate your stream with custom commands, timed messages,\n"
            "event responses and more. Create your first bot to get started."
        )
        wlc_desc.setObjectName("CardDescription")
        wlc_desc.setAlignment(Qt.AlignCenter)
        wlc_desc.setWordWrap(True)
        wlc_lay.addWidget(wlc_desc)
        wlc_btn = QPushButton("Create your first bot →")
        wlc_btn.setObjectName("StagePrimaryBtn")
        wlc_btn.setFixedWidth(220)
        wlc_btn.clicked.connect(self._add_bot)
        wlc_btn_row = QHBoxLayout()
        wlc_btn_row.addStretch()
        wlc_btn_row.addWidget(wlc_btn)
        wlc_btn_row.addStretch()
        wlc_lay.addLayout(wlc_btn_row)
        self._right_stack.addWidget(welcome)

        # Editor page
        self._editor = BotEditorWidget()
        self._editor.save_requested.connect(self._save_bot)
        self._editor.delete_requested.connect(self._delete_bot)
        self._right_stack.addWidget(self._editor)

        root.addWidget(self._right_stack)

        self._populate_sidebar()

    # ── Public API ──────────────────────────────────────────────

    def refresh(self, engines: dict[str, BotEngine], dbs: dict[str, BotDatabase]) -> None:
        self._engines = engines
        self._dbs = dbs
        self._populate_sidebar()
        self._subscribe_all_engines()

    # ── Sidebar ─────────────────────────────────────────────────

    def _populate_sidebar(self) -> None:
        bots = self._repo.list_bots()
        existing_ids = {b.bot_id for b in bots}

        # Remove stale items
        for bot_id in list(self._sidebar_items.keys()):
            if bot_id not in existing_ids:
                item = self._sidebar_items.pop(bot_id)
                item.setParent(None)
                item.deleteLater()

        # Add or update
        for bot in bots:
            if bot.bot_id in self._sidebar_items:
                self._sidebar_items[bot.bot_id].update_bot(bot)
            else:
                item = BotSidebarItem(bot)
                item.selected.connect(self._select_bot)
                item.toggle_enabled.connect(self._toggle_bot_enabled)
                self._bot_list_layout.insertWidget(
                    self._bot_list_layout.count() - 1, item
                )
                self._sidebar_items[bot.bot_id] = item

            # Update state if engine exists
            if bot.bot_id in self._engines:
                self._sidebar_items[bot.bot_id].update_state(
                    self._engines[bot.bot_id].state
                )

        if not bots:
            self._right_stack.setCurrentIndex(0)

    def _select_bot(self, bot_id: str) -> None:
        if self._selected_bot_id and self._selected_bot_id in self._sidebar_items:
            self._sidebar_items[self._selected_bot_id].set_active(False)
        self._unsubscribe_engine()

        self._selected_bot_id = bot_id
        if bot_id in self._sidebar_items:
            self._sidebar_items[bot_id].set_active(True)

        bot = self._repo.get_bot_with_secrets(bot_id)
        db = self._get_or_create_db(bot_id)
        if bot:
            self._editor.load_bot(bot, db)
            self._right_stack.setCurrentIndex(1)
            self._subscribe_engine(bot_id)

    def _subscribe_engine(self, bot_id: str) -> None:
        engine = self._engines.get(bot_id)
        if engine and engine not in self._subscribed_engines:
            self._subscribed_engines.add(engine)
            engine.subscribe(self._on_engine_update)

    def _subscribe_all_engines(self) -> None:
        for bot_id in self._engines:
            self._subscribe_engine(bot_id)

    def _unsubscribe_engine(self) -> None:
        for engine in list(self._subscribed_engines):
            engine.unsubscribe(self._on_engine_update)
        self._subscribed_engines.clear()

    def _on_engine_update(self, state: BotRunState) -> None:
        # Update the sidebar dot for whatever bot sent this state update.
        if state.bot_id and state.bot_id in self._sidebar_items:
            self._sidebar_items[state.bot_id].update_state(state)
        # Only push activity to the editor if this is the bot currently open.
        if state.bot_id == self._selected_bot_id:
            self._editor.update_activity(state.activity)

    # ── Bot CRUD ────────────────────────────────────────────────

    def _add_bot(self) -> None:
        new_bot = BotConfig(
            bot_id=str(uuid.uuid4()),
            name="New Bot",
            icon="🤖",
            enabled=False,
            twitch_channel="",
            twitch_bot_username="",
            twitch_oauth_token="",
            twitch_client_id="",
            discord_bot_token="",
            discord_guild_id="",
            discord_announce_channel_id="",
            discord_enabled=False,
            created_at=time.time(),
        )
        self._repo.save_bot(new_bot)
        self._get_or_create_db(new_bot.bot_id)
        self._populate_sidebar()
        self._select_bot(new_bot.bot_id)

    def _save_bot(self, bot: BotConfig) -> None:
        self._repo.save_bot(bot)
        if bot.bot_id in self._sidebar_items:
            self._sidebar_items[bot.bot_id].update_bot(bot)
        if bot.bot_id in self._engines:
            self._engines[bot.bot_id].update_config(bot)
        elif bot.enabled and self._start_bot:
            # First time this bot has been enabled — spin up the engine.
            self._start_bot(bot)
            self._subscribe_engine(bot.bot_id)
            # _start_bot creates a fresh BotDatabase and puts it in _dbs.
            # Reload the editor tabs with that new db so they don't hold a
            # stale reference to the pre-engine db connection.
            fresh_db = self._dbs.get(bot.bot_id) or self._get_or_create_db(bot.bot_id)
            self._editor.load_bot(bot, fresh_db)

    def _delete_bot(self, bot_id: str) -> None:
        self._unsubscribe_engine()
        self._repo.delete_bot(bot_id)
        if bot_id in self._sidebar_items:
            item = self._sidebar_items.pop(bot_id)
            item.setParent(None)
            item.deleteLater()
        self._selected_bot_id = None
        self._right_stack.setCurrentIndex(0)

    def _toggle_bot_enabled(self, bot_id: str, enabled: bool) -> None:
        # Use secrets so the engine gets credentials when starting.
        bot = self._repo.get_bot_with_secrets(bot_id)
        if not bot:
            return
        bot.enabled = enabled
        self._repo.save_bot(bot)
        if enabled:
            if bot_id in self._engines:
                self._engines[bot_id].update_config(bot)
            elif self._start_bot:
                self._start_bot(bot)
                if bot_id == self._selected_bot_id:
                    self._subscribe_engine(bot_id)
        else:
            if self._stop_bot:
                self._stop_bot(bot_id)
            elif bot_id in self._engines:
                self._engines[bot_id].update_config(bot)

    def closeEvent(self, event) -> None:
        self._unsubscribe_engine()
        super().closeEvent(event)
