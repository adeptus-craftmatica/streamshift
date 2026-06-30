from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.plugins.scene_designer.designer_repository import DesignerRepository

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "scene_designer"
_SCENE_MANAGER_SETTINGS = Path.home() / ".streamshift" / "scene_manager" / "settings.json"


class SceneDesignerPlugin:
    """Visual scene editor — build, design, and sync scenes to OBS."""

    def __init__(self) -> None:
        self._repo: DesignerRepository | None = None
        self._page_widget = None

    def register(self, app_context) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._repo = DesignerRepository(_DATA_DIR / "scenes.json")
        self._register_page(app_context)
        app_context.set_status("Scene Designer loaded.", timeout_ms=3000)
        logger.info("Scene Designer plugin registered")

    def unregister(self, app_context) -> None:
        self._repo = None
        self._page_widget = None
        logger.info("Scene Designer plugin unregistered")

    def _register_page(self, app_context) -> None:
        from stream_controller.plugins.scene_designer.ui.scene_designer_page import SceneDesignerPage

        obs_settings = _SCENE_MANAGER_SETTINGS if _SCENE_MANAGER_SETTINGS.exists() else None

        self._page_widget = SceneDesignerPage(
            repo=self._repo,
            obs_settings_path=obs_settings,
        )
        app_context.register_plugin_page(
            page_id="scene_designer",
            title="Scene Designer",
            subtitle="Build scenes visually — images, browser sources, text, video, and more. Sync directly to OBS.",
            widget=self._page_widget,
            help_text=(
                "<h3>Scene Designer</h3>"
                "<p>Scene Designer is a visual editor for building OBS scenes. Arrange images, browser sources, "
                "text, and video inside StreamShift, then push the result directly to OBS.</p>"
                "<h4>Creating a scene</h4>"
                "<ol>"
                "<li>Click <b>New Scene</b> and give it a name.</li>"
                "<li>Use the <b>Add Element</b> button to add images, browser sources, text, or video files.</li>"
                "<li>Drag elements around the canvas to position them, and resize using the corner handles.</li>"
                "<li>Click <b>Sync to OBS</b> to push the scene layout to OBS as a new or updated scene.</li>"
                "</ol>"
                "<h4>Element types</h4>"
                "<ul>"
                "<li><b>Image</b> — static PNG, JPG, or GIF file.</li>"
                "<li><b>Browser Source</b> — any URL, including StreamShift overlays.</li>"
                "<li><b>Text</b> — styled text with font and colour options.</li>"
                "<li><b>Video</b> — local video file as a media source.</li>"
                "</ul>"
                "<h4>Tips</h4>"
                "<p>Scene Manager must be connected to OBS before you can sync. "
                "Syncing creates or replaces the OBS scene with the same name — existing sources in OBS "
                "with the same name will be updated.</p>"
            ),
        )
