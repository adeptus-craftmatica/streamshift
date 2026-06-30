from __future__ import annotations

import logging

from stream_controller.plugins.stream_health.health_poller import HealthPoller

logger = logging.getLogger(__name__)


class StreamHealthPlugin:
    def __init__(self) -> None:
        self._app_context = None
        self._poller: HealthPoller | None = None
        self._page = None

    def register(self, app_context) -> None:
        self._app_context = app_context

        self._poller = HealthPoller(
            on_stats=self._on_stats,
            get_obs_config=self._get_obs_config,
        )
        self._poller.start()

        from stream_controller.plugins.stream_health.ui.health_page import HealthPage
        self._page = HealthPage()

        app_context.register_plugin_page(
            page_id="stream_health",
            title="Stream Health",
            subtitle="Real-time OBS performance monitoring — FPS, CPU, dropped frames, and stream uptime.",
            widget=self._page,
            help_text=(
                "<h3>Stream Health Monitor</h3>"
                "<p>Displays real-time OBS performance statistics updated every 1.5 seconds. "
                "Requires the OBS Studio plugin to be configured with your OBS WebSocket connection details.</p>"
                "<h4>Stats explained</h4>"
                "<ul>"
                "<li><b>FPS</b> — Active render frame rate. Green ≥59, yellow ≥55, red below.</li>"
                "<li><b>CPU Usage</b> — OBS process CPU load. Green &lt;50%, yellow &lt;75%, red higher.</li>"
                "<li><b>Dropped Frames</b> — Frames skipped during encoding or network output.</li>"
                "<li><b>Render Time</b> — Average time to render a frame. Green &lt;8ms, yellow &lt;16ms.</li>"
                "<li><b>Bitrate</b> — Estimated output bitrate calculated from bytes sent and stream duration.</li>"
                "</ul>"
            ),
        )
        app_context.register_stage_widget(
            panel_id="stream_health.main",
            title="Stream Health",
            icon="🖥️",
            factory=lambda: __import__(
                "stream_controller.plugins.stream_health.ui.health_tile",
                fromlist=["HealthTile"],
            ).HealthTile(self._poller),
        )
        app_context.set_status("Stream Health Monitor loaded.", timeout_ms=3000)

    def unregister(self, app_context) -> None:
        if self._poller:
            self._poller.stop()
        self._app_context = None
        self._poller = None
        self._page = None

    def _get_obs_config(self) -> tuple[str, int, str]:
        if not self._app_context:
            return ("localhost", 4455, "")
        host = self._app_context.get_setting("obs_studio", "host", "localhost") or "localhost"
        port = self._app_context.get_setting("obs_studio", "port", 4455)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 4455
        password = self._app_context.get_setting("obs_studio", "password", "") or ""
        return (host, port, password)

    def _on_stats(self, stats: dict) -> None:
        from PySide6.QtCore import QTimer
        if self._page is not None:
            page = self._page
            QTimer.singleShot(0, lambda: page.update_stats(stats))
