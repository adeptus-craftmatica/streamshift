from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stream_controller.plugins.bot_manager.bot_engine import BotEngine
from stream_controller.plugins.bot_manager.bot_models import BotActivity, BotRunState
from stream_controller.plugins.bot_manager.bot_repository import BotRepository

_MAX_FEED_ENTRIES = 8

# ────────────────────────── helpers ─────────────────────────────


def _kind_color(kind: str) -> str:
    return {
        "command": "#7c3aed",
        "timed": "#3b82f6",
        "event": "#f59e0b",
        "system": "#64748b",
    }.get(kind, "#64748b")


def _dot(connected: bool) -> QLabel:
    lbl = QLabel("●")
    lbl.setStyleSheet(
        f"color:{'#22c55e' if connected else '#64748b'}; font-size:11px;"
    )
    return lbl


# ────────────────────────── BotStatusRow ────────────────────────


class BotStatusRow(QWidget):
    def __init__(self, bot_id: str, name: str, icon: str, state: BotRunState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bot_id = bot_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        icon_lbl = QLabel(icon or "🤖")
        icon_lbl.setStyleSheet("font-size:16px;")
        icon_lbl.setFixedWidth(22)
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size:12px; font-weight:600;")
        layout.addWidget(name_lbl)

        layout.addStretch()

        twitch_icon = QLabel("T")
        twitch_icon.setStyleSheet("font-size:10px; color:#64748b;")
        layout.addWidget(twitch_icon)
        self._twitch_dot = _dot(state.twitch_connected)
        layout.addWidget(self._twitch_dot)

        discord_icon = QLabel("D")
        discord_icon.setStyleSheet("font-size:10px; color:#64748b;")
        layout.addWidget(discord_icon)
        self._discord_dot = _dot(state.discord_connected)
        layout.addWidget(self._discord_dot)

        self._cmds_lbl = QLabel(f"{state.commands_handled} cmds")
        self._cmds_lbl.setStyleSheet("font-size:10px; color:#64748b;")
        layout.addWidget(self._cmds_lbl)

    def update_state(self, state: BotRunState) -> None:
        self._twitch_dot.setStyleSheet(
            f"color:{'#22c55e' if state.twitch_connected else '#64748b'}; font-size:11px;"
        )
        self._discord_dot.setStyleSheet(
            f"color:{'#22c55e' if state.discord_connected else '#64748b'}; font-size:11px;"
        )
        self._cmds_lbl.setText(f"{state.commands_handled} cmds")


# ────────────────────────── FeedEntry ───────────────────────────


class FeedEntry(QWidget):
    def __init__(self, activity: BotActivity, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(6)

        ts = datetime.fromtimestamp(activity.ts).strftime("%H:%M:%S")
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet("font-family:monospace; font-size:10px; color:#475569;")
        ts_lbl.setFixedWidth(54)
        layout.addWidget(ts_lbl)

        color = _kind_color(activity.kind)
        kind_lbl = QLabel(activity.kind[:6].upper())
        kind_lbl.setStyleSheet(
            f"background:{color}22; color:{color}; font-size:9px;"
            "padding:1px 4px; border-radius:3px; font-weight:600;"
        )
        kind_lbl.setFixedWidth(52)
        layout.addWidget(kind_lbl)

        text_lbl = QLabel(activity.text)
        text_lbl.setStyleSheet("font-size:11px; color:#94a3b8;")
        text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_lbl.setTextFormat(Qt.PlainText)
        layout.addWidget(text_lbl)


# ────────────────────────── BotTile ─────────────────────────────


class BotTile(QFrame):
    def __init__(self, engines: dict[str, BotEngine], repo: BotRepository) -> None:
        super().__init__()
        self._engines = engines
        self._repo = repo
        self._bot_rows: dict[str, BotStatusRow] = {}
        self._seen_ts: set[float] = set()
        self._feed_entries: list[BotActivity] = []

        self.setObjectName("Card")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("🤖 Bots")
        title.setObjectName("CardTitle")
        title.setStyleSheet("font-size:13px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        self._global_twitch_dot = QLabel("●")
        self._global_twitch_dot.setStyleSheet("color:#64748b; font-size:12px;")
        self._global_discord_dot = QLabel("●")
        self._global_discord_dot.setStyleSheet("color:#64748b; font-size:12px;")
        header.addWidget(QLabel("T"))
        header.addWidget(self._global_twitch_dot)
        header.addWidget(QLabel("D"))
        header.addWidget(self._global_discord_dot)
        root.addLayout(header)

        # ── Bot status rows ──
        self._status_area = QWidget()
        self._status_layout = QVBoxLayout(self._status_area)
        self._status_layout.setContentsMargins(0, 0, 0, 0)
        self._status_layout.setSpacing(2)
        root.addWidget(self._status_area)

        # ── Divider ──
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color:#1e293b;")
        root.addWidget(divider)

        # ── Activity feed ──
        feed_label = QLabel("Recent Activity")
        feed_label.setStyleSheet("font-size:11px; font-weight:600; color:#64748b;")
        root.addWidget(feed_label)

        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(True)
        self._feed_scroll.setFrameShape(QFrame.NoFrame)
        self._feed_scroll.setFixedHeight(160)
        self._feed_scroll.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #94a3b8;"
            "background: #0d1117; border-radius:4px; padding:4px;"
        )

        self._feed_widget = QWidget()
        self._feed_layout = QVBoxLayout(self._feed_widget)
        self._feed_layout.setContentsMargins(4, 4, 4, 4)
        self._feed_layout.setSpacing(1)
        self._feed_layout.addStretch()
        self._feed_scroll.setWidget(self._feed_widget)
        root.addWidget(self._feed_scroll)

        # ── Quick-send ──
        self._bot_selector = QComboBox()
        self._bot_selector.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._bot_selector.setMinimumContentsLength(12)
        self._bot_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._bot_selector)

        send_row = QHBoxLayout()
        self._message_input = QLineEdit()
        self._message_input.setPlaceholderText("Send a chat message…")
        self._message_input.returnPressed.connect(self._send_message)
        send_row.addWidget(self._message_input)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("StagePrimaryBtn")
        send_btn.setFixedWidth(60)
        send_btn.clicked.connect(self._send_message)
        send_row.addWidget(send_btn)
        root.addLayout(send_row)

        # Init
        self._build_status_rows()
        self._populate_bot_selector()

        # Subscribe to all engines
        for bot_id, engine in self._engines.items():
            engine.subscribe(self._make_callback(bot_id))

        self.destroyed.connect(self._unsubscribe_all)

    # ── Build / Rebuild ──────────────────────────────────────────

    def _build_status_rows(self) -> None:
        # Clear existing
        while self._status_layout.count():
            item = self._status_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._bot_rows.clear()

        bots = self._repo.list_bots()
        for bot in bots:
            engine = self._engines.get(bot.bot_id)
            state = engine.state if engine else _empty_state()
            row = BotStatusRow(bot.bot_id, bot.name, bot.icon or "🤖", state)
            self._status_layout.addWidget(row)
            self._bot_rows[bot.bot_id] = row

        if not bots:
            empty = QLabel("No bots configured.")
            empty.setStyleSheet("color:#475569; font-size:11px;")
            self._status_layout.addWidget(empty)

    def _populate_bot_selector(self) -> None:
        self._bot_selector.clear()
        bots = self._repo.list_bots()
        for bot in bots:
            self._bot_selector.addItem(f"{bot.icon or '🤖'} {bot.name}", bot.bot_id)

    # ── Engine callbacks ─────────────────────────────────────────

    def _make_callback(self, bot_id: str):
        def _cb(state: BotRunState) -> None:
            self._on_engine_update(bot_id, state)
        return _cb

    def _on_engine_update(self, bot_id: str, state: BotRunState) -> None:
        # Update status row
        if bot_id in self._bot_rows:
            self._bot_rows[bot_id].update_state(state)

        # Update global dots
        any_twitch = any(
            e.state.twitch_connected for e in self._engines.values()
        )
        any_discord = any(
            e.state.discord_connected for e in self._engines.values()
        )
        self._global_twitch_dot.setStyleSheet(
            f"color:{'#22c55e' if any_twitch else '#64748b'}; font-size:12px;"
        )
        self._global_discord_dot.setStyleSheet(
            f"color:{'#22c55e' if any_discord else '#64748b'}; font-size:12px;"
        )

        # Add new feed entries (keep last 8)
        new_entries = [a for a in state.activity if a.ts not in self._seen_ts]
        for activity in new_entries:
            self._seen_ts.add(activity.ts)
            self._feed_entries.append(activity)
            entry = FeedEntry(activity)
            self._feed_layout.insertWidget(self._feed_layout.count() - 1, entry)

        # Trim feed to max 8
        while len(self._feed_entries) > _MAX_FEED_ENTRIES:
            self._feed_entries.pop(0)
            # Remove oldest widget (index 0)
            item = self._feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Scroll to bottom
        if new_entries:
            sb = self._feed_scroll.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _unsubscribe_all(self) -> None:
        for engine in self._engines.values():
            try:
                engine.unsubscribe(self._make_callback)
            except Exception:
                pass

    # ── Quick send ───────────────────────────────────────────────

    def _send_message(self) -> None:
        text = self._message_input.text().strip()
        if not text:
            return
        bot_id = self._bot_selector.currentData()
        if bot_id and bot_id in self._engines:
            self._engines[bot_id].send_chat_message(text)
            self._message_input.clear()

    # ── Public refresh ───────────────────────────────────────────

    def refresh(self, engines: dict[str, BotEngine]) -> None:
        # Unsubscribe old
        for engine in self._engines.values():
            try:
                engine.unsubscribe(self._make_callback)
            except Exception:
                pass

        self._engines = engines
        self._seen_ts.clear()
        self._build_status_rows()
        self._populate_bot_selector()

        for bot_id, engine in self._engines.items():
            engine.subscribe(self._make_callback(bot_id))


# ────────────────────────── util ────────────────────────────────


def _empty_state() -> BotRunState:
    return BotRunState(
        twitch_connected=False,
        discord_connected=False,
        messages_sent=0,
        commands_handled=0,
        last_chat_ts=0.0,
        activity=[],
    )
