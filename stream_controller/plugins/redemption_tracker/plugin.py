from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.redemption_tracker.redemption_client import RedemptionClient
from stream_controller.plugins.redemption_tracker.redemption_models import QueueItem
from stream_controller.plugins.redemption_tracker.redemption_store import RedemptionStore
from stream_controller.plugins.redemption_tracker.reward_actions import RewardActionMapping

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "redemption_tracker"


class RedemptionTrackerPlugin:
    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._store:    RedemptionStore    | None = None
        self._client:   RedemptionClient   | None = None
        self._mappings: RewardActionMapping | None = None
        self._page   = None
        self._connected = False

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._store    = RedemptionStore(_DATA_DIR / "queue.json")
        self._client   = RedemptionClient(on_item=self._on_item)
        self._mappings = RewardActionMapping(_DATA_DIR / "reward_actions.json")

        from stream_controller.plugins.redemption_tracker.ui.redemption_page import RedemptionPage
        self._page = RedemptionPage(self._store, self._client, self._mappings, app_context)

        app_context.register_plugin_page(
            page_id="redemption_tracker",
            title="Redemption Tracker",
            subtitle="Track and complete channel point redemptions and bit cheers from your stage view.",
            widget=self._page,
            help_text=(
                "<h3>Redemption Tracker</h3>"
                "<p>Tracks channel point redemptions and bit cheers in real time using Twitch EventSub. "
                "Add the <b>Redemption Queue</b> panel to your stage view to see and complete items without "
                "leaving the stream control surface.</p>"
                "<h4>Setup</h4>"
                "<p>The plugin reuses the Twitch OAuth token configured in Stream Stats. "
                "Connect Stream Stats first, then this plugin will connect automatically.</p>"
                "<h4>Auto-fulfil</h4>"
                "<p>When enabled, marking a channel point redemption as complete also calls the Twitch API "
                "to fulfil it, clearing it from the OBS channel points queue.</p>"
            ),
        )

        app_context.register_stage_widget(
            panel_id="redemption_tracker.queue",
            title="Redemption Queue",
            icon="🎁",
            factory=self._make_panel,
        )

        # Auto-connect once stream_stats has a token
        app_context.event_bus.subscribe("twitch.connected", self._on_twitch_connected)

        # Try immediate connect in case stream_stats is already up
        QTimer.singleShot(1500, self._try_auto_connect)

        app_context.set_status("Redemption Tracker loaded.", timeout_ms=3000)
        logger.info("Redemption Tracker registered")

    def unregister(self, app_context: AppContext) -> None:
        app_context.event_bus.unsubscribe("twitch.connected", self._on_twitch_connected)
        if self._client:
            self._client.disconnect()
        self._app_context = None
        self._store    = None
        self._client   = None
        self._mappings = None
        self._page     = None

    # ── Connection ────────────────────────────────────────────────────────────

    def _try_auto_connect(self) -> None:
        if self._connected or not self._app_context:
            return
        token     = self._app_context.get_setting("stream_stats", "oauth_token", "") or ""
        client_id = self._app_context.get_setting("stream_stats", "client_id", "") or ""
        if token and client_id and self._client:
            self._client.connect(token, client_id)
            self._connected = True
            if self._page:
                self._page.set_status("Connected to Twitch EventSub", connected=True)
            logger.info("Redemption Tracker: connected via stream_stats credentials")

    def _on_twitch_connected(self, payload: dict) -> None:
        QTimer.singleShot(500, self._try_auto_connect)

    # ── Incoming item ─────────────────────────────────────────────────────────

    def _on_item(self, item: QueueItem) -> None:
        if self._store:
            self._store.add(item)

        # Fire event bus so macros can react
        if self._app_context:
            self._app_context.event_bus.emit("redemption.received", {
                "kind":        item.kind.value,
                "reward_name": item.reward_name,
                "viewer_name": item.viewer_name,
                "user_input":  item.user_input,
                "amount":      item.amount,
            })

        # Execute any mapped action for this reward name
        if self._mappings and self._app_context:
            action_id = self._mappings.get_action(item.reward_name)
            if action_id:
                try:
                    self._app_context.action_registry.execute(action_id)
                    logger.info(
                        "Redemption Tracker: fired action %r for reward %r from %s",
                        action_id, item.reward_name, item.viewer_name,
                    )
                except Exception as exc:
                    logger.warning(
                        "Redemption Tracker: action %r failed for reward %r: %s",
                        action_id, item.reward_name, exc,
                    )

        logger.info(
            "Redemption Tracker: new %s from %s — %s",
            item.kind.value, item.viewer_name, item.reward_name,
        )

    # ── Stage panel factory ───────────────────────────────────────────────────

    def _make_panel(self):
        from stream_controller.plugins.redemption_tracker.ui.redemption_panel import RedemptionPanel
        return RedemptionPanel(self._store, self._client, fulfil_on_complete=True)
