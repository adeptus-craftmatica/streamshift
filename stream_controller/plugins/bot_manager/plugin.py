from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QTimer

from stream_controller.plugins.bot_manager.bot_database import BotDatabase
from stream_controller.plugins.bot_manager.bot_engine import BotEngine
from stream_controller.plugins.bot_manager.bot_repository import BotRepository

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "bot_manager"
_TICK_INTERVAL_MS = 30_000


class BotManagerPlugin:
    """
    Bot Manager — multi-platform Twitch and Discord bot management.
    Manages multiple bot instances, each with their own engine and database.
    """

    def __init__(self) -> None:
        self._repo: BotRepository | None = None
        self._engines: dict[str, BotEngine] = {}
        self._dbs: dict[str, BotDatabase] = {}
        self._timer: QTimer | None = None
        self._page_widget = None

    def register(self, app_context) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._repo = BotRepository(_DATA_DIR / "bots.json")

        for bot in self._repo.list_bots():
            if bot.bot_id not in self._dbs:
                db_path = _DATA_DIR / f"{bot.bot_id}.db"
                self._dbs[bot.bot_id] = BotDatabase(db_path)

        self._timer = QTimer()
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick_all)
        self._timer.start()

        self._register_page(app_context)

        app_context.set_status("Bot Manager loaded.", timeout_ms=3000)
        logger.info("Bot Manager plugin registered")

    def unregister(self, app_context) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

        engines = list(self._engines.values())
        self._engines.clear()
        for engine in engines:
            threading.Thread(target=engine.stop, daemon=True).start()

        for db in self._dbs.values():
            db.close()
        self._dbs.clear()

        self._repo = None
        self._page_widget = None
        logger.info("Bot Manager plugin unregistered")

    def _ensure_db(self, bot_id: str) -> "BotDatabase":
        if bot_id not in self._dbs:
            db_path = _DATA_DIR / f"{bot_id}.db"
            self._dbs[bot_id] = BotDatabase(db_path)
        return self._dbs[bot_id]

    # ── registration ──────────────────────────────────────────────────────────

    def _register_page(self, app_context) -> None:
        from stream_controller.plugins.bot_manager.ui.bot_manager_page import BotManagerPage

        self._page_widget = BotManagerPage(
            repo=self._repo,
            engines=self._engines,
            dbs=self._dbs,
            get_or_create_db=self._ensure_db,
            start_bot=self._start_bot,
            stop_bot=self._stop_bot,
        )
        app_context.register_plugin_page(
            page_id="bot_manager",
            title="Bot Manager",
            subtitle="Twitch and Discord bots — commands, timed messages, and event responses.",
            widget=self._page_widget,
            help_text=(
                "<h3>Bot Manager</h3>"
                "<p>Bot Manager lets you configure and run Twitch and Discord bots that respond to "
                "chat commands, send timed messages, and react to stream events.</p>"
                "<h4>Adding a bot</h4>"
                "<ol>"
                "<li>Click <b>Add Bot</b> and choose the platform (Twitch or Discord).</li>"
                "<li>Enter the bot's username and OAuth token (for Twitch) or bot token (for Discord).</li>"
                "<li>Click <b>Start</b> to bring the bot online.</li>"
                "</ol>"
                "<h4>Commands</h4>"
                "<p>Add chat commands with a trigger (e.g. <code>!hello</code>) and a response. "
                "Commands can include variables like <code>{user}</code> for the chatter's name.</p>"
                "<h4>Timed messages</h4>"
                "<p>Set up messages that post automatically at a set interval — useful for reminders, "
                "social links, or stream rules.</p>"
                "<h4>Using in macros</h4>"
                "<p>The <b>Send Chat Message</b> and <b>Raid Channel</b> macro steps use the bots "
                "configured here to send messages to chat.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="Bot Manager",
            description="Manage your Twitch and Discord bots.",
            widget=self._build_dashboard_panel(),
        )
        app_context.register_stage_widget(
            panel_id="bots.live",
            title="Bot Activity",
            icon="🤖",
            factory=self._make_bot_tile,
        )
        app_context.register_stage_widget(
            panel_id="bots.commands",
            title="Commands",
            icon="⌨",
            factory=lambda: self._make_commands_card(app_context),
        )
        app_context.register_stage_widget(
            panel_id="bots.notifications",
            title="Event Log",
            icon="🔔",
            factory=lambda: self._make_notification_log_card(app_context),
        )
        app_context.register_stage_widget(
            panel_id="bots.hype_train",
            title="Hype Train",
            icon="🚂",
            factory=lambda: self._make_hype_train_card(app_context),
        )

    def _make_bot_tile(self):
        from stream_controller.plugins.bot_manager.ui.bot_tile import BotTile
        return BotTile(engines=self._engines, repo=self._repo)

    def _make_commands_card(self, app_context):
        from stream_controller.plugins.bot_manager.ui.commands_card import CommandsCard
        return CommandsCard(engines=self._engines, app_context=app_context)

    def _make_notification_log_card(self, app_context):
        from stream_controller.plugins.bot_manager.ui.notification_log_card import NotificationLogCard
        return NotificationLogCard(app_context=app_context)

    def _make_hype_train_card(self, app_context):
        from stream_controller.plugins.bot_manager.ui.hype_train_card import HypeTrainCard
        return HypeTrainCard(app_context=app_context)

    def _build_dashboard_panel(self):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Bot Manager active — open the sidebar to manage your bots.")
        lbl.setObjectName("CardDescription")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        return panel

    # ── engine lifecycle ──────────────────────────────────────────────────────

    def _start_bot(self, bot) -> None:
        if bot.bot_id in self._engines:
            return
        # Reuse the existing db connection — never create a second one for the same bot.
        # The editor tabs hold a reference to this same object; replacing it would leave them
        # pointing at a closed connection the next time _stop_bot is called.
        if bot.bot_id not in self._dbs:
            db_path = _DATA_DIR / f"{bot.bot_id}.db"
            self._dbs[bot.bot_id] = BotDatabase(db_path)
        db = self._dbs[bot.bot_id]
        engine = BotEngine(bot, db)
        self._engines[bot.bot_id] = engine
        engine.start()
        if self._page_widget is not None:
            self._page_widget.refresh(self._engines, self._dbs)

    def _stop_bot(self, bot_id: str) -> None:
        engine = self._engines.pop(bot_id, None)
        # Refresh the UI immediately so the toggle snaps back visually
        if self._page_widget is not None:
            self._page_widget.refresh(self._engines, self._dbs)
        if engine:
            # Run disconnect joins on a background thread — each client join()
            # can block up to 4s, which would freeze the Qt main thread.
            threading.Thread(
                target=engine.stop,
                daemon=True,
                name=f"bot-stop-{bot_id}",
            ).start()

    def start_all_bots(self, on_alert=None) -> None:
        """Start all configured bots, enabling all commands and event responses.

        on_alert: optional callable(event_type, username, extra) called for each
        EventSub event (subs, bits, raids, follows, channel points). Used by
        Quick Connect to push alerts into ChatStateManager.
        """
        if self._repo is None:
            return
        for bot in self._repo.list_bots_with_secrets():
            # Enable all commands and event responses in the DB before starting
            if bot.bot_id not in self._dbs:
                db_path = _DATA_DIR / f"{bot.bot_id}.db"
                self._dbs[bot.bot_id] = BotDatabase(db_path)
            db = self._dbs[bot.bot_id]
            db.enable_all_commands()
            db.enable_all_event_responses(bot_id=bot.bot_id)

            if bot.bot_id not in self._engines:
                self._start_bot_with_alert(bot, on_alert)

    def _start_bot_with_alert(self, bot, on_alert=None) -> None:
        """Internal: start a bot engine with an optional alert callback."""
        if bot.bot_id in self._engines:
            return
        if bot.bot_id not in self._dbs:
            db_path = _DATA_DIR / f"{bot.bot_id}.db"
            self._dbs[bot.bot_id] = BotDatabase(db_path)
        db = self._dbs[bot.bot_id]
        engine = BotEngine(bot, db, on_alert=on_alert)
        self._engines[bot.bot_id] = engine
        engine.start()
        if self._page_widget is not None:
            self._page_widget.refresh(self._engines, self._dbs)

    def stop_all_bots(self) -> None:
        """Stop all running bots."""
        for bot_id in list(self._engines.keys()):
            self._stop_bot(bot_id)

    def get_bot_states(self) -> dict:
        """Return {bot_id: BotRunState} for all engines."""
        return {bid: eng.state for bid, eng in self._engines.items()}

    def _tick_all(self) -> None:
        for engine in list(self._engines.values()):
            try:
                engine.tick()
            except Exception as exc:
                logger.warning("Engine tick error: %s", exc)
