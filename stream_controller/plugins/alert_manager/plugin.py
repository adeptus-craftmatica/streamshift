from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".streamshift" / "alert_manager" / "config.json"


class AlertManagerPlugin:
    """Alert Manager — animated follower, sub, bits, raid, and donation overlays."""

    def __init__(self) -> None:
        self._app_context = None
        self._configs: dict = {}
        self._queue = None
        self._overlay_server = None
        self._page_widget = None
        self._subscriptions: list[tuple[str, Any]] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def register(self, app_context) -> None:
        self._app_context = app_context

        # Load / initialise configs
        self._configs = self._load_all_configs()

        # Start queue
        from stream_controller.plugins.alert_manager.alert_queue import AlertQueue
        self._queue = AlertQueue(
            get_config=self._get_config,
            on_alert=self._on_alert,
        )
        self._queue.start()

        # Start overlay server
        from stream_controller.plugins.alert_manager.overlay_server import AlertOverlayServer
        from stream_controller.plugins.alert_manager.alert_models import AlertConfig as _AC, AlertType as _AT
        self._overlay_server = AlertOverlayServer(
            get_style=lambda t: (
                self._configs.get(t) or _AC(_AT(t))
            ).overlay_style
        )
        self._overlay_server.start()

        # Subscribe to Twitch events from event_bus
        self._subscribe_events(app_context)

        # Register UI page
        self._register_page(app_context)

        app_context.set_status("Alert Manager loaded.", timeout_ms=3000)
        logger.info("Alert Manager plugin registered")

    def unregister(self, app_context) -> None:
        # Unsubscribe events
        event_bus = getattr(app_context, "event_bus", None)
        if event_bus is not None:
            for event_name, handler in self._subscriptions:
                try:
                    event_bus.unsubscribe(event_name, handler)
                except Exception:
                    pass
        self._subscriptions.clear()

        if self._queue is not None:
            self._queue.stop()
            self._queue = None

        if self._overlay_server is not None:
            self._overlay_server.stop()
            self._overlay_server = None

        self._app_context = None
        self._page_widget = None
        logger.info("Alert Manager plugin unregistered")

    # ── Event handling ────────────────────────────────────────────────────────

    def _subscribe_events(self, app_context) -> None:
        event_bus = getattr(app_context, "event_bus", None)
        if event_bus is None:
            logger.warning("Alert Manager: no event_bus on app_context, events won't be received")
            return

        handlers = {
            "twitch.follow":    self._handle_follow,
            "twitch.subscribe": self._handle_subscribe,
            "twitch.gift_sub":  self._handle_gift_sub,
            "twitch.bits":      self._handle_bits,
            "twitch.raid":      self._handle_raid,
        }
        for event_name, handler in handlers.items():
            try:
                event_bus.subscribe(event_name, handler)
                self._subscriptions.append((event_name, handler))
            except Exception:
                logger.exception("Failed to subscribe to %s", event_name)

    def _handle_follow(self, payload: dict) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        event = AlertEvent(
            alert_type=AlertType.FOLLOWER,
            name=payload.get("user_name", "Someone"),
        )
        if self._queue:
            self._queue.enqueue(event)

    def _handle_subscribe(self, payload: dict) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        event = AlertEvent(
            alert_type=AlertType.SUBSCRIBER,
            name=payload.get("user_name", "Someone"),
            tier=payload.get("tier", "Tier 1"),
        )
        if self._queue:
            self._queue.enqueue(event)

    def _handle_gift_sub(self, payload: dict) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        event = AlertEvent(
            alert_type=AlertType.GIFT_SUB,
            name=payload.get("user_name", "Someone"),
            count=payload.get("count", 1),
        )
        if self._queue:
            self._queue.enqueue(event)

    def _handle_bits(self, payload: dict) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        event = AlertEvent(
            alert_type=AlertType.BITS,
            name=payload.get("user_name", "Someone"),
            amount=float(payload.get("amount", 0)),
        )
        if self._queue:
            self._queue.enqueue(event)

    def _handle_raid(self, payload: dict) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        event = AlertEvent(
            alert_type=AlertType.RAID,
            name=payload.get("user_name", "Someone"),
            count=payload.get("count", 0),
        )
        if self._queue:
            self._queue.enqueue(event)

    def _on_alert(self, event) -> None:
        """Called by AlertQueue when an alert is ready to display."""
        if self._overlay_server is None:
            return
        config = self._get_config(event.alert_type)
        template = config.resolved_template()
        try:
            message = template.format(
                name=event.name,
                tier=event.tier,
                count=event.count,
                amount=f"{event.amount:.2f}",
            )
        except (KeyError, ValueError):
            message = template

        data = {
            "type": event.alert_type.value,
            "name": event.name,
            "message": message,
            "duration": config.duration_ms,
        }
        self._overlay_server.push_alert(event.alert_type.value, data)

    # ── Config helpers ────────────────────────────────────────────────────────

    def _get_config(self, alert_type):
        from stream_controller.plugins.alert_manager.alert_models import AlertType
        key = alert_type.value if hasattr(alert_type, "value") else str(alert_type)
        return self._configs[key]

    def _load_all_configs(self) -> dict:
        from stream_controller.plugins.alert_manager.alert_models import AlertConfig, AlertType
        saved: dict = {}
        try:
            if _CONFIG_PATH.exists():
                saved = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load alert configs")

        configs = {}
        for alert_type in AlertType:
            key = alert_type.value
            raw = saved.get(key, {})
            configs[key] = AlertConfig(
                alert_type=alert_type,
                enabled=raw.get("enabled", True),
                message_template=raw.get("message_template", ""),
                duration_ms=raw.get("duration_ms", 5000),
                sound_file=raw.get("sound_file", ""),
                overlay_style=raw.get("overlay_style", "card"),
            )
        return configs

    # ── Page registration ─────────────────────────────────────────────────────

    def _register_page(self, app_context) -> None:
        from stream_controller.plugins.alert_manager.ui.alert_manager_page import AlertManagerPage
        overlay_url = self._overlay_server.base_url if self._overlay_server else ""
        self._page_widget = AlertManagerPage(
            queue=self._queue,
            get_config=self._get_config,
            configs=self._configs,
            overlay_url=overlay_url,
            on_style_change=self._overlay_server.push_style_change if self._overlay_server else None,
        )
        app_context.register_plugin_page(
            page_id="alert_manager",
            title="Alert Manager",
            subtitle="Animated follower, subscriber, bits, raid, and donation alerts.",
            widget=self._page_widget,
            help_text=(
                "<h3>Alert Manager</h3>"
                "<p>Alert Manager shows animated overlay alerts for Twitch events such as follows, "
                "subscriptions, bits, raids, and donations.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Copy the Browser Source URL from the Alert Manager page.</li>"
                "<li>In OBS, add a Browser source and paste the URL.</li>"
                "<li>Set the source to 1920×1080 and enable scene-refresh options.</li>"
                "</ol>"
                "<h4>Customisation</h4>"
                "<p>Use the Alert Settings tab to enable/disable alert types, edit message templates, "
                "and adjust display duration. Click Test to preview any alert live.</p>"
            ),
        )
