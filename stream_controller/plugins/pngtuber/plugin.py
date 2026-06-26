from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "pngtuber"


class PngTuberPlugin:
    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo = None
        self._engine = None
        self._server = None
        self._level: float = 0.0

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        from stream_controller.plugins.pngtuber.pngtuber_repository import PngTuberRepository
        from stream_controller.plugins.pngtuber.avatar_engine import AvatarEngine
        from stream_controller.plugins.pngtuber.pngtuber_server import PngTuberServer

        self._repo = PngTuberRepository(_DATA_DIR / "settings.json")

        self._engine = AvatarEngine(
            on_state_change=self._on_state_change,
            on_level_change=self._on_level_change,
        )
        self._engine.mic_device_index = self._repo.get("mic_device_index")
        self._engine.mic_threshold = self._repo.get("mic_threshold")
        self._engine.talk_hold_frames = self._repo.get("talk_hold_frames")
        self._engine.blink_enabled = self._repo.get("blink_enabled")

        self._server = PngTuberServer(self._repo, self._engine)
        self._server.start()

        self._register_page(app_context)
        self._register_actions(app_context)

        if self._repo.get("auto_start"):
            self.start()

        app_context.set_status("PNGtuber loaded.", timeout_ms=3000)

    def unregister(self, app_context: AppContext) -> None:
        self.stop()
        if self._server:
            self._server.stop()
        self._app_context = None

    def start(self) -> None:
        if self._engine:
            self._engine.mic_device_index = self._repo.get("mic_device_index")
            self._engine.mic_threshold = self._repo.get("mic_threshold")
            self._engine.talk_hold_frames = self._repo.get("talk_hold_frames")
            self._engine.blink_enabled = self._repo.get("blink_enabled")
            self._engine.start()

    def stop(self) -> None:
        if self._engine:
            self._engine.stop()

    def set_expression(self, name: str) -> None:
        if self._repo and name in self._repo.list_expressions():
            self._repo.set("active_expression", name)

    def get_state(self) -> dict:
        return {
            "state": self._engine.state if self._engine else "idle",
            "expression": self._repo.get("active_expression") if self._repo else "default",
            "level": self._level,
            "running": self._engine.running if self._engine else False,
        }

    def _on_state_change(self, state: str) -> None:
        if self._server:
            self._server.push_state(state, self._level)

    def _on_level_change(self, level: float) -> None:
        self._level = level

    def _register_actions(self, app_context: AppContext) -> None:
        app_context.register_action(
            action_id="pngtuber.start",
            title="Start PNGtuber",
            description="Start mic detection and avatar engine.",
            execute=self.start,
            icon="🎤",
            page="PNGtuber",
            group="PNGtuber",
        )
        app_context.register_action(
            action_id="pngtuber.stop",
            title="Stop PNGtuber",
            description="Stop mic detection.",
            execute=self.stop,
            icon="⏹",
            page="PNGtuber",
            group="PNGtuber",
        )

    def _make_tile(self):
        from stream_controller.plugins.pngtuber.ui.pngtuber_tile import PngTuberTile
        return PngTuberTile(plugin=self)

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.pngtuber.ui.pngtuber_page import PngTuberPage

        page = PngTuberPage(plugin=self, repo=self._repo, engine=self._engine)
        app_context.register_plugin_page(
            page_id="pngtuber",
            title="PNGtuber",
            subtitle="Mic-reactive PNG avatar for OBS browser source.",
            widget=page,
            help_text=(
                "<h3>PNGtuber</h3>"
                "<p>PNGtuber displays a mic-reactive PNG avatar in OBS that switches between idle and "
                "talking poses based on your microphone input.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Click <b>Edit Avatar</b> and assign PNG images to each layer: "
                "<b>Idle</b>, <b>Talking</b>, <b>Idle Blink</b>, and <b>Talking Blink</b>.</li>"
                "<li>Select your microphone from the <b>Mic Input</b> dropdown.</li>"
                "<li>Adjust the <b>Threshold</b> slider — lower values make the avatar more sensitive.</li>"
                "<li>Click <b>Start</b> to begin mic detection.</li>"
                "</ol>"
                "<h4>OBS browser source</h4>"
                "<p>Add <code>http://localhost:47897/avatar</code> as a browser source in OBS. "
                "Set the width and height to match your canvas size (default 800×800).</p>"
                "<p>The background colour is set to your chosen chroma colour (default green <code>#00ff00</code>). "
                "Apply a <b>Chroma Key</b> filter in OBS to make the background transparent.</p>"
                "<h4>Expressions</h4>"
                "<p>Create multiple expressions (e.g. Happy, Surprised) and switch between them "
                "during your stream from the PNGtuber tile on the Stage View.</p>"
            ),
        )
        app_context.register_stage_widget(
            panel_id="pngtuber.main",
            title="PNGtuber",
            icon="🎭",
            factory=self._make_tile,
        )
        app_context.register_dashboard_panel(
            title="PNGtuber",
            description="Mic-reactive avatar status.",
            widget=self._make_tile(),
        )
