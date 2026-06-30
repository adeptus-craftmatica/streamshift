from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.stream_stats.stats_engine import StatsEngine
from stream_controller.plugins.stream_stats.stats_repository import StatsRepository
from stream_controller.plugins.stream_stats.stats_client import StatsClient
from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus
from stream_controller.plugins.stream_stats.overlay_server import StatsOverlayServer

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "stream_stats"


class StreamStatsPlugin:
    """Live Twitch stream stats with EventSub, overlays, and session history."""

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo:    StatsRepository | None = None
        self._engine:  StatsEngine     | None = None
        self._client:  StatsClient     | None = None
        self._overlay: StatsOverlayServer | None = None
        self._page = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo   = StatsRepository(_DATA_DIR)
        self._engine = StatsEngine()
        self._engine.set_repo(self._repo)

        self._client = StatsClient(
            on_status          = self._on_client_status,
            on_follower        = self._engine.add_follower,
            on_bits            = self._engine.add_bits,
            on_sub             = self._engine.add_sub,
            on_gifted_subs     = self._engine.add_gifted_subs,
            on_total_followers = self._engine.set_total_followers,
        )

        self._overlay = StatsOverlayServer(self._engine)
        self._overlay.start()

        # When Stream Info plugin fires go-live / end-stream, auto-manage our session
        app_context.event_bus.subscribe("stream.started", self._on_stream_started)
        app_context.event_bus.subscribe("stream.ended",   self._on_stream_ended)

        self._register_page(app_context)

        # Share client_id from chat manager if stats doesn't have its own
        if not self._repo.get("client_id"):
            try:
                chat_repo_path = Path.home() / ".streamshift" / "chat_manager" / "chat_settings.json"
                if chat_repo_path.exists():
                    import json
                    chat_data = json.loads(chat_repo_path.read_text(encoding="utf-8"))
                    if chat_data.get("client_id"):
                        self._repo.set("client_id", chat_data["client_id"])
            except Exception:
                pass

        if self._repo.get("auto_connect") and self._repo.get("oauth_token"):
            QTimer.singleShot(500, self._auto_connect)

        app_context.set_status("Stream Stats loaded.", timeout_ms=3000)

    def unregister(self, app_context: AppContext) -> None:
        app_context.event_bus.unsubscribe("stream.started", self._on_stream_started)
        app_context.event_bus.unsubscribe("stream.ended",   self._on_stream_ended)
        if self._engine and self._engine.live.session_active:
            self._engine.end_session()
        if self._client:
            self._client.disconnect()
        if self._overlay:
            self._overlay.stop()
        self._app_context = None

    # ── connection ────────────────────────────────────────────────────────────

    def do_connect(self) -> None:
        token     = self._repo.get("oauth_token") or ""
        client_id = self._repo.get("client_id") or ""
        if not token:
            self._engine.set_status(ConnectionStatus.ERROR, "No OAuth token — authorize in Settings.")
            return
        if not client_id:
            self._engine.set_status(ConnectionStatus.ERROR, "No Client ID — enter one in Settings.")
            return
        self._client.connect(token, client_id)

    def do_disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
        self._engine.set_status(ConnectionStatus.DISCONNECTED)

    def _auto_connect(self) -> None:
        self.do_connect()

    def _on_client_status(self, status: ConnectionStatus, error: str) -> None:
        self._engine.set_status(status, error)
        if status == ConnectionStatus.CONNECTED:
            # Immediately fetch follower count
            import threading
            threading.Thread(
                target=self._client._fetch_followers,
                daemon=True, name="stats-init-poll"
            ).start()

    # ── EventBus handlers ─────────────────────────────────────────────────────

    def _on_stream_started(self, payload: dict) -> None:
        """Auto-start a stats session when Stream Info goes live."""
        if not self._engine.live.session_active:
            self._engine.start_session()

    def _on_stream_ended(self, payload: dict) -> None:
        """Auto-end and save stats session when Stream Info ends the stream."""
        title = (payload or {}).get("title", "") if isinstance(payload, dict) else ""
        if self._engine.live.session_active:
            self._engine.end_session(stream_title=title)

    # ── page ──────────────────────────────────────────────────────────────────

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.stream_stats.ui.stats_page import StatsPage
        from stream_controller.plugins.stream_stats.ui.stats_tile import StatsTile
        from stream_controller.plugins.stream_stats.ui.live_stats_card import LiveStatsCard

        self._page = StatsPage(
            engine=self._engine,
            repo=self._repo,
            overlay_base_url=self._overlay.base_url,
        )
        self._page.set_plugin_ref(self)

        app_context.register_plugin_page(
            page_id="stream_stats",
            title="Stream Stats",
            subtitle="Live Twitch follower, sub, and bits tracking with session history and overlays.",
            widget=self._page,
            help_text=(
                "<h3>Stream Stats</h3>"
                "<p>Stream Stats tracks followers, subscriptions, and bits in real time using Twitch EventSub, "
                "and keeps a session history so you can review what happened during a stream.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Stream Info must be connected first — Stream Stats uses the same Twitch OAuth token.</li>"
                "<li>Sessions start and stop automatically when you go live and end your stream via Stream Info.</li>"
                "</ol>"
                "<h4>Overlays</h4>"
                "<p>Stream Stats provides browser-source overlay URLs you can add to OBS to display "
                "live follower/sub/bits counts on screen. Copy the URL from the Stats page and paste it "
                "into an OBS browser source.</p>"
                "<h4>Session history</h4>"
                "<p>Each stream session is saved so you can look back at totals from previous streams "
                "without losing data when the app restarts.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="",
            description="",
            widget=StatsTile(self._engine),
        )
        app_context.register_stage_widget(
            panel_id="stats.main",
            title="Stream Stats",
            icon="📊",
            factory=lambda: StatsTile(self._engine),
        )
        app_context.register_stage_widget(
            panel_id="stats.live",
            title="Live Stats",
            icon="📡",
            factory=lambda: LiveStatsCard(self._engine),
        )
