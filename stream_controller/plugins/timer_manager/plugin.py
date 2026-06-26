from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.timer_manager.actions import ACTION_DEFINITIONS, make_action_handlers
from stream_controller.plugins.timer_manager.timer_engine import TimerEngine
from stream_controller.plugins.timer_manager.timer_repository import TimerRepository
from stream_controller.plugins.timer_manager.overlay_server import TimerOverlayServer

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "timer_manager"


class TimerManagerPlugin:
    """Countdown / count-up timers with browser-source overlays."""

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo: TimerRepository | None = None
        self._engine: TimerEngine | None = None
        self._overlay_server: TimerOverlayServer | None = None
        self._tick_timer: QTimer | None = None
        self._page_widget = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo = TimerRepository(_DATA_DIR / "timers.json")
        self._engine = TimerEngine(self._repo)

        self._overlay_server = TimerOverlayServer(self._engine)
        self._overlay_server.start()

        self._register_actions(app_context)
        self._register_page(app_context)

        self._tick_timer = QTimer()
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._engine.tick)
        self._tick_timer.start()

        app_context.set_status("Timer Manager loaded.", timeout_ms=3000)
        logger.info("Timer Manager plugin registered")

    def unregister(self, app_context: AppContext) -> None:
        if self._tick_timer:
            self._tick_timer.stop()
            self._tick_timer = None
        if self._overlay_server:
            self._overlay_server.stop()
        self._app_context = None
        self._repo = None
        self._engine = None
        self._overlay_server = None
        self._page_widget = None
        logger.info("Timer Manager plugin unregistered")

    def _register_actions(self, app_context: AppContext) -> None:
        handlers = make_action_handlers(self._engine)
        handlers["timer.open_panel"] = self._open_panel
        for defn in ACTION_DEFINITIONS:
            aid = defn["action_id"]
            factory = self._make_timer_tile if aid == "timer.timer_tile" else None
            app_context.register_action(
                action_id=aid,
                title=defn["title"],
                description=defn["description"],
                execute=handlers.get(aid, lambda: None),
                icon=defn.get("icon", "TM"),
                page=defn.get("page", "Timer"),
                group=defn.get("group", "Timer Manager"),
                default_shortcut=defn.get("default_shortcut"),
                widget_factory=factory,
            )

    def _make_timer_tile(self):
        from stream_controller.plugins.timer_manager.ui.timer_tile import TimerTile
        return TimerTile(self._engine)

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.timer_manager.ui.timer_page import TimerPage
        overlay_url = self._overlay_server.base_url if self._overlay_server else ""
        self._page_widget = TimerPage(engine=self._engine, overlay_base_url=overlay_url)
        app_context.register_plugin_page(
            page_id="timer_manager",
            title="Timer Manager",
            subtitle="Countdown and count-up timers with customisable browser-source overlays.",
            widget=self._page_widget,
            help_text=(
                "<h3>Timer Manager</h3>"
                "<p>Timer Manager creates countdown and count-up timers that display as browser-source "
                "overlays in OBS — perfect for starting-soon countdowns, intermission timers, and more.</p>"
                "<h4>Creating a timer</h4>"
                "<ol>"
                "<li>Click <b>Add Timer</b>, give it a name, choose <b>Countdown</b> or <b>Count Up</b>, "
                "and set the duration.</li>"
                "<li>Customise the colour and end message.</li>"
                "<li>Press <b>Start</b> to begin the timer.</li>"
                "</ol>"
                "<h4>OBS browser source</h4>"
                "<p>Each timer style has its own URL (e.g. <code>http://localhost:47894/circle</code>). "
                "Add <code>?id=YOUR_TIMER_ID</code> to pin the source to a specific timer. "
                "Add <code>&amp;hide_after=6</code> to hide the overlay 6 seconds after the timer finishes.</p>"
                "<h4>Using in macros</h4>"
                "<p>Add a <b>Create Timer</b> step to set up and start a timer automatically. "
                "Set <b>Duration From: Music Tracks</b> to match the timer to your chosen music length. "
                "Enable <b>Wait for completion</b> to pause the macro until the timer finishes.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="Timer Manager",
            description="Manage countdown and count-up timers.",
            widget=self._build_dashboard_panel(),
        )
        app_context.register_stage_widget(
            panel_id="timer.main",
            title="Timer Manager",
            icon="⏱",
            factory=lambda: __import__(
                'stream_controller.plugins.timer_manager.ui.timer_tile',
                fromlist=['TimerTile']
            ).TimerTile(self._engine),
        )

    def _build_dashboard_panel(self):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Timer Manager active — use the sidebar to manage timers.")
        lbl.setObjectName("CardDescription")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        return panel

    def _open_panel(self) -> None:
        if self._app_context:
            self._app_context.show_page("timer_manager")
