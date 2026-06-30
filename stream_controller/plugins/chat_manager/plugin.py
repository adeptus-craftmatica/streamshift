from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.chat_manager.actions import ACTION_DEFINITIONS, make_action_handlers
from stream_controller.plugins.chat_manager.chat_repository import ChatRepository
from stream_controller.plugins.chat_manager.chat_state import ChatStateManager
from stream_controller.plugins.chat_manager.overlay_server import ChatOverlayServer

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "chat_manager"


class ChatManagerPlugin:
    """
    Chat Manager — live Twitch chat, moderation tools, and chat overlays.
    Registered through the StreamShift plugin system.
    """

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo: ChatRepository | None = None
        self._chat_state: ChatStateManager | None = None
        self._overlay_server: ChatOverlayServer | None = None
        self._page_widget = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._repo = ChatRepository(_DATA_DIR / "chat_settings.json")
        self._chat_state = ChatStateManager(self._repo)

        self._overlay_server = ChatOverlayServer(self._chat_state)
        self._overlay_server.start()

        self._register_actions(app_context)
        self._register_page(app_context)

        app_context.register_stage_widget(
            panel_id="chat.live",
            title="Live Chat",
            icon="💬",
            factory=lambda: __import__(
                'stream_controller.plugins.chat_manager.ui.chat_tile',
                fromlist=['ChatDashboardCard']
            ).ChatDashboardCard(self._chat_state),
        )
        app_context.register_stage_widget(
            panel_id="chat.alerts",
            title="Stream Alerts",
            icon="🔔",
            factory=lambda: __import__(
                'stream_controller.plugins.chat_manager.ui.alerts_tile',
                fromlist=['AlertsTile']
            ).AlertsTile(self._chat_state),
        )

        app_context.set_status("Chat Manager loaded.", timeout_ms=3000)
        logger.info("Chat Manager plugin registered")

    def unregister(self, app_context: AppContext) -> None:
        if self._chat_state is not None:
            self._chat_state.disconnect()

        if self._overlay_server is not None:
            self._overlay_server.stop()

        self._app_context = None
        self._repo = None
        self._chat_state = None
        self._overlay_server = None
        self._page_widget = None
        logger.info("Chat Manager plugin unregistered")

    # ── private ───────────────────────────────────────────────────────────────

    def _register_actions(self, app_context: AppContext) -> None:
        handlers = make_action_handlers(self._chat_state)
        handlers["chat.open_panel"] = self._open_panel

        for defn in ACTION_DEFINITIONS:
            aid = defn["action_id"]
            factory = None
            if aid == "chat.chat_tile":
                factory = self._make_chat_tile
            app_context.register_action(
                action_id=aid,
                title=defn["title"],
                description=defn["description"],
                execute=handlers.get(aid, lambda: None),
                icon=defn.get("icon", "CH"),
                page=defn.get("page", "Chat"),
                group=defn.get("group", "Chat Manager"),
                default_shortcut=defn.get("default_shortcut"),
                widget_factory=factory,
            )

    def _make_chat_tile(self):
        from stream_controller.plugins.chat_manager.ui.chat_tile import ChatTile
        return ChatTile(self._chat_state)

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.chat_manager.ui.chat_page import ChatPage
        overlay_url = self._overlay_server.base_url if self._overlay_server else ""
        self._page_widget = ChatPage(
            chat_state=self._chat_state,
            repo=self._repo,
            overlay_base_url=overlay_url,
        )
        app_context.register_plugin_page(
            page_id="chat_manager",
            title="Chat Manager",
            subtitle="Live Twitch chat, moderation tools, and browser-source chat overlays.",
            widget=self._page_widget,
            help_text=(
                "<h3>Chat Manager</h3>"
                "<p>Chat Manager displays your live Twitch chat inside StreamShift and provides "
                "moderation tools and a browser-source chat overlay for OBS.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Bot Manager must be configured and connected first — Chat Manager uses the bot's "
                "Twitch connection to read chat.</li>"
                "<li>Connect via Quick Connect or the Chat Manager connect button.</li>"
                "</ol>"
                "<h4>Chat overlay for OBS</h4>"
                "<p>The Chat Manager runs a local web server with a styled chat overlay. Copy the "
                "browser-source URL from the Chat page and add it to OBS to show live chat on screen.</p>"
                "<h4>Moderation</h4>"
                "<p>You can timeout, ban, or delete messages directly from the chat view inside StreamShift "
                "without switching to a browser.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="Chat Manager",
            description="Live Twitch chat monitoring and moderation.",
            widget=self._build_dashboard_panel(),
        )

    def _build_dashboard_panel(self):
        from stream_controller.plugins.chat_manager.ui.chat_tile import ChatDashboardCard
        return ChatDashboardCard(self._chat_state)

    def _open_panel(self) -> None:
        if self._app_context is not None:
            self._app_context.show_page("chat_manager")
