from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.poll_manager.poll_client import PollClient
from stream_controller.plugins.poll_manager.poll_engine import PollEngine
from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus, Poll
from stream_controller.plugins.poll_manager.poll_repository import PollRepository


class _Bridge(QObject):
    """Ferries background-thread callbacks onto the GUI thread via signals."""
    status_received = Signal(object, str, str)   # (ConnectionStatus, error_msg, broadcaster_id)
    polls_received  = Signal(object, list)        # (active Poll | None, recent list[Poll])

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "poll_manager"


class PollManagerPlugin:
    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo:    PollRepository | None = None
        self._engine:  PollEngine     | None = None
        self._client:  PollClient     | None = None
        self._poll_timer: QTimer      | None = None
        self._page = None
        self._bridge = _Bridge()
        self._bridge.status_received.connect(self._apply_status)
        self._bridge.polls_received.connect(self._apply_poll_update)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo   = PollRepository(_DATA_DIR)
        self._engine = PollEngine()
        self._client = PollClient(on_status=self._on_client_status)

        # Create timer on the GUI thread (register() always runs there)
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._refresh_polls)

        # Inherit client_id from chat_manager when not set
        if not self._repo.get("client_id"):
            try:
                chat_path = Path.home() / ".streamshift" / "chat_manager" / "chat_settings.json"
                if chat_path.exists():
                    data = json.loads(chat_path.read_text(encoding="utf-8"))
                    if data.get("client_id"):
                        self._repo.set("client_id", data["client_id"])
            except Exception:
                pass

        self._register_page(app_context)

        if self._repo.get("auto_connect") and self._repo.get("oauth_token"):
            QTimer.singleShot(700, self._auto_connect)

        app_context.set_status("Poll Manager loaded.", timeout_ms=3000)

    def unregister(self, app_context: AppContext) -> None:
        self._stop_poll_timer()
        self._poll_timer = None
        if self._client:
            self._client.disconnect()
            self._client = None
        self._engine = None
        self._repo   = None
        self._app_context = None

    # ── Public API (Quick Connect + Stage Tile) ───────────────────────────────

    def connect(self) -> None:
        if not self._client or not self._repo:
            return
        token     = self._repo.get("oauth_token") or ""
        client_id = self._repo.get("client_id") or ""
        if not token:
            if self._engine:
                self._engine.set_status(ConnectionStatus.ERROR,
                                        "No OAuth token — authorize in Poll Manager settings.")
            return
        if not client_id:
            if self._engine:
                self._engine.set_status(ConnectionStatus.ERROR,
                                        "No Client ID — enter one in Poll Manager settings.")
            return
        if self._engine:
            self._engine.set_status(ConnectionStatus.CONNECTING)
        self._client.connect(token, client_id)
        # If validation never calls back, force ERROR after 15 s
        QTimer.singleShot(15_000, self._check_connecting_timeout)

    def disconnect(self) -> None:
        self._stop_poll_timer()
        if self._client:
            self._client.disconnect()
        if self._engine:
            self._engine.set_status(ConnectionStatus.DISCONNECTED)
            self._engine.set_active_poll(None)

    def create_poll(self, title: str, choices: list[str], duration: int) -> None:
        if not self._client or not self._client.is_connected:
            return
        import threading
        threading.Thread(
            target=self._do_create_poll, args=(title, choices, duration),
            daemon=True, name="poll-create",
        ).start()

    # ── Template API ──────────────────────────────────────────────────────────

    def get_templates(self) -> list[dict]:
        return self._repo.get_templates() if self._repo else []

    def save_template(self, name: str, title: str, choices: list[str],
                      duration: int, template_id: str | None = None) -> None:
        if not self._repo:
            return
        import uuid
        self._repo.save_template({
            "id":       template_id or uuid.uuid4().hex[:8],
            "name":     name,
            "title":    title,
            "choices":  choices,
            "duration": duration,
        })

    def delete_template(self, template_id: str) -> None:
        if self._repo:
            self._repo.delete_template(template_id)

    def request_refresh(self) -> None:
        """Fire an immediate poll refresh (called by the tile when countdown hits 0)."""
        self._refresh_polls()

    def end_poll(self, poll_id: str, archive: bool = False) -> None:
        if not self._client or not self._client.is_connected:
            return
        import threading
        threading.Thread(
            target=self._do_end_poll, args=(poll_id, archive),
            daemon=True, name="poll-end",
        ).start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_connecting_timeout(self) -> None:
        if self._engine and self._engine.state.connection_status == ConnectionStatus.CONNECTING:
            logger.warning("Poll Manager: connection timed out — setting ERROR")
            self._engine.set_status(ConnectionStatus.ERROR,
                                    "Connection timed out — re-authorize in Poll Manager settings.")

    def _auto_connect(self) -> None:
        if self._client is None:
            return
        self.connect()

    def _on_client_status(self, status: ConnectionStatus, error: str) -> None:
        # Called from a background thread — emit signal to marshal onto the GUI thread.
        broadcaster_id = self._client.broadcaster_id if status == ConnectionStatus.CONNECTED else ""
        self._bridge.status_received.emit(status, error, broadcaster_id)

    def _apply_status(self, status: ConnectionStatus, error: str, broadcaster_id: str) -> None:
        if self._engine:
            self._engine.set_status(status, error)
        if status == ConnectionStatus.CONNECTED:
            if self._repo and broadcaster_id:
                self._repo.set("broadcaster_id", broadcaster_id)
            self._start_poll_timer()
            self._refresh_polls()

    def _start_poll_timer(self) -> None:
        if self._poll_timer:
            self._poll_timer.start()

    def _stop_poll_timer(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()

    def _refresh_polls(self) -> None:
        if not self._client or not self._client.is_connected:
            return
        import threading
        threading.Thread(target=self._fetch_polls, daemon=True, name="poll-refresh").start()

    def _fetch_polls(self) -> None:
        # Runs on background thread — fetch data, then marshal results to GUI thread.
        try:
            data = self._client.get_polls(status="ACTIVE", first=1)
            raw  = data.get("data", [])
            active = Poll.from_api(raw[0]) if raw else None

            recent_data = self._client.get_polls(first=10)
            recent = [Poll.from_api(p) for p in recent_data.get("data", [])]
        except Exception as e:
            logger.warning("Poll refresh failed: %s", e)
            return

        self._bridge.polls_received.emit(active, recent)

    def _apply_poll_update(self, active: "Poll | None", recent: "list[Poll]") -> None:
        if self._engine:
            self._engine.set_active_poll(active)
            self._engine.set_recent_polls(recent)

    def _do_create_poll(self, title: str, choices: list[str], duration: int) -> None:
        try:
            self._client.create_poll(title, choices, duration)
        except Exception as e:
            logger.warning("Create poll failed: %s", e)
        self._fetch_polls()

    def _do_end_poll(self, poll_id: str, archive: bool) -> None:
        try:
            self._client.end_poll(poll_id, archive)
        except Exception as e:
            logger.warning("End poll failed: %s", e)
        # Always refresh — even on failure, the tile must reflect the true server state.
        self._fetch_polls()

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.poll_manager.ui.poll_page import PollPage
        from stream_controller.plugins.poll_manager.ui.poll_tile import PollTile

        self._page = PollPage(engine=self._engine, repo=self._repo, plugin=self)

        app_context.register_plugin_page(
            page_id="poll_manager",
            title="Poll Manager",
            subtitle="Create and manage live Twitch polls without leaving StreamShift.",
            widget=self._page,
            help_text=(
                "<h3>Poll Manager</h3>"
                "<p>Create and manage Twitch polls directly from StreamShift.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Your Twitch Client ID is shared from Chat Manager automatically.</li>"
                "<li>Click <b>Authorize</b> — StreamShift opens Twitch in your browser "
                "and catches the token automatically.</li>"
                "<li>Enable <b>Auto Connect</b> to reconnect on next launch.</li>"
                "</ol>"
                "<h4>Required scopes</h4>"
                "<p>Poll Manager needs <code>channel:manage:polls</code> and "
                "<code>channel:read:polls</code>. These are separate from your Chat Manager "
                "token — you need to authorize once in Poll Manager settings.</p>"
            ),
        )

        app_context.register_stage_widget(
            panel_id="poll_manager.tile",
            title="Poll Manager",
            icon="🗳️",
            factory=lambda: PollTile(self._engine, self),
        )
