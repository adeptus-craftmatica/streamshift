from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.stream_info.info_client import InfoClient
from stream_controller.plugins.stream_info.info_models import (
    ConnectionStatus, InfoState, StreamInfo, StreamStatus
)
from stream_controller.plugins.stream_info.info_repository import InfoRepository

logger = logging.getLogger(__name__)

_DATA_DIR        = Path.home() / ".streamshift" / "stream_info"
_SCENE_SETTINGS  = Path.home() / ".streamshift" / "scene_manager" / "settings.json"


class _Signals(QObject):
    state_changed = Signal()


class StreamInfoPlugin:
    """Update Twitch stream info on the fly, go live/end stream via OBS."""

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo:   InfoRepository | None  = None
        self._client: InfoClient     | None  = None
        self._state   = InfoState()
        self._signals = _Signals()
        self._signals.state_changed.connect(self._notify)
        self._subscribers: list[Callable[[InfoState], None]] = []
        self._page = None

    # ── plugin lifecycle ──────────────────────────────────────────────────────

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo = InfoRepository(_DATA_DIR / "settings.json")

        # Inherit client_id from Chat Manager if not set
        if not self._repo.get("client_id"):
            try:
                cm = Path.home() / ".streamshift" / "chat_manager" / "chat_settings.json"
                if cm.exists():
                    data = json.loads(cm.read_text(encoding="utf-8"))
                    if data.get("client_id"):
                        self._repo.set("client_id", data["client_id"])
            except Exception:
                pass

        self._client = InfoClient(
            on_status        = self._on_client_status,
            on_info_updated  = self._on_info_updated,
            on_stream_status = self._on_stream_status,
        )
        self._apply_obs_config()

        self._register_page(app_context)

        # Subscribe to stream.started / stream.ended events from stream_info itself
        # (other plugins like stream_stats listen on the bus)
        if self._repo.get("auto_connect") and self._repo.get("oauth_token"):
            QTimer.singleShot(500, self.do_connect)

        app_context.set_status("Stream Info loaded.", timeout_ms=3000)

    def unregister(self, app_context: AppContext) -> None:
        if self._client:
            self._client.disconnect()
        self._app_context = None

    # ── public API (called by UI + tiles) ─────────────────────────────────────

    @property
    def state(self) -> InfoState:
        return self._state

    @property
    def repo(self) -> InfoRepository:
        return self._repo

    def subscribe(self, cb: Callable[[InfoState], None]) -> None:
        if cb not in self._subscribers:
            self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    def do_connect(self) -> None:
        token    = self._repo.get("oauth_token") or ""
        cid      = self._repo.get("client_id")   or ""
        if not token:
            self._state.twitch_status = ConnectionStatus.ERROR
            self._state.error = "No OAuth token — authorize in Settings."
            self._signals.state_changed.emit()
            return
        self._apply_obs_config()
        self._client.connect(token, cid)

    def do_disconnect(self) -> None:
        if self._client:
            self._client.disconnect()

    def update_info(self, title: str, category_id: str, tags: list | None = None, language: str = "") -> None:
        if self._client:
            self._client.update_info(title, category_id, tags, language)

    def search_categories(self, query: str, callback: Callable[[list[dict]], None]) -> None:
        if self._client:
            self._client.search_categories(query, callback)

    def go_live(self, notification: str = "") -> None:
        import threading as _threading
        adapter = self._get_obs_adapter()
        if adapter is not None:
            logger.info("go_live: using connected OBS plugin (%s)", type(adapter).__name__)
            _threading.Thread(target=self._safe_start_stream, args=(adapter,),
                              daemon=True, name="go-live").start()
        elif self._client:
            logger.info("go_live: using stream_info OBS credentials")
            self._client.go_live()
        else:
            logger.warning("go_live: no OBS connection available")
        self._on_stream_status(StreamStatus.LIVE)
        if self._app_context:
            self._app_context.event_bus.emit("stream.started", {
                "title": self._state.info.title,
                "notification": notification or self._repo.get("go_live_notification") or "",
            })

    def end_stream(self, title: str = "") -> None:
        import threading as _threading
        adapter = self._get_obs_adapter()
        if adapter is not None:
            _threading.Thread(target=self._safe_stop_stream, args=(adapter,),
                              daemon=True, name="end-stream").start()
        elif self._client:
            self._client.end_stream()
        self._on_stream_status(StreamStatus.OFFLINE)
        if self._app_context:
            self._app_context.event_bus.emit("stream.ended", {
                "title": title or self._state.info.title,
            })

    def _safe_start_stream(self, adapter) -> None:
        try:
            adapter.start_stream()
            logger.info("OBS stream started via %s", type(adapter).__name__)
        except Exception as exc:
            logger.warning("start_stream failed: %s", exc)

    def _safe_stop_stream(self, adapter) -> None:
        try:
            adapter.stop_stream()
            logger.info("OBS stream stopped via %s", type(adapter).__name__)
        except Exception as exc:
            logger.warning("stop_stream failed: %s", exc)

    def _get_obs_adapter(self):
        """Return an object with start_stream/stop_stream from whichever OBS plugin is connected.
        Prefers obs_studio (used by Quick Connect), falls back to scene_manager."""
        if self._app_context is None:
            return None
        pm = self._app_context.plugin_manager

        # Try obs_studio first — this is what Quick Connect uses
        try:
            lp = pm._loaded_plugins.get("obs_studio")
            if lp is not None:
                svc = getattr(lp.instance, "_service", None)
                if svc is not None and getattr(svc, "is_connected", False):
                    return svc  # has start_stream / stop_stream
        except Exception:
            pass

        # Fallback: scene_manager's ReqClient
        try:
            lp = pm._loaded_plugins.get("scene_manager")
            if lp is not None:
                client = getattr(lp.instance, "_client", None)
                if client is not None:
                    from stream_controller.plugins.scene_manager.scene_models import ConnectionStatus as ScCS
                    if client.state.status == ScCS.CONNECTED:
                        return client
        except Exception:
            pass

        return None

    # ── internal ──────────────────────────────────────────────────────────────

    def _apply_obs_config(self) -> None:
        """Use saved OBS credentials, falling back to scene_manager settings."""
        host     = self._repo.get("obs_host")     or ""
        port_raw = self._repo.get("obs_port")     or ""
        password = self._repo.get("obs_password") or ""

        if not host:
            try:
                if _SCENE_SETTINGS.exists():
                    sc = json.loads(_SCENE_SETTINGS.read_text(encoding="utf-8"))
                    host     = sc.get("host",     "localhost")
                    port_raw = sc.get("port",     4455)
                    password = sc.get("password", "")
            except Exception:
                pass

        port = int(port_raw) if str(port_raw).isdigit() else 4455
        if self._client:
            self._client.set_obs_config(host or "localhost", port, password)

    def _on_client_status(self, status: ConnectionStatus, error: str) -> None:
        self._state.twitch_status = status
        self._state.error         = error
        self._signals.state_changed.emit()

    def _on_info_updated(self, info: StreamInfo, broadcaster_id: str, username: str) -> None:
        self._state.info           = info
        self._state.broadcaster_id = broadcaster_id
        self._state.username       = username
        self._signals.state_changed.emit()

    def _on_stream_status(self, status: StreamStatus) -> None:
        self._state.stream_status = status
        self._signals.state_changed.emit()

    def _notify(self) -> None:
        state = self._state
        for cb in list(self._subscribers):
            try:
                cb(state)
            except RuntimeError:
                self._subscribers = [s for s in self._subscribers if s is not cb]

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.stream_info.ui.info_page import InfoPage
        from stream_controller.plugins.stream_info.ui.info_tile import InfoTile

        self._page = InfoPage(self)
        app_context.register_plugin_page(
            page_id="stream_info",
            title="Stream Info",
            subtitle="Update stream title and category, go live, and end your stream.",
            widget=self._page,
            help_text=(
                "<h3>Stream Info</h3>"
                "<p>Stream Info connects to Twitch to let you update your stream title and category, "
                "and go live or end your stream — all without leaving StreamShift.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Go to <b>Settings → Stream Info</b> and click <b>Authorise with Twitch</b> to get your OAuth token.</li>"
                "<li>Once authorised, click <b>Connect</b> to pull in your current channel info.</li>"
                "<li>Optionally enter your OBS host/port/password here if you want Stream Info to control OBS directly.</li>"
                "</ol>"
                "<h4>Going live</h4>"
                "<p>Set your <b>Title</b> and <b>Category</b>, type an optional chat announcement, "
                "then press <b>Go Live</b>. This updates Twitch and starts OBS streaming in one step.</p>"
                "<h4>Using in macros</h4>"
                "<p>Add an <b>Update Stream Info</b> step to a macro to automatically set your title and "
                "category as part of a go-live workflow.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="",
            description="",
            widget=InfoTile(self),
        )
        app_context.register_stage_widget(
            panel_id="info.main",
            title="Stream Info",
            icon="📡",
            factory=lambda: InfoTile(self),
        )
