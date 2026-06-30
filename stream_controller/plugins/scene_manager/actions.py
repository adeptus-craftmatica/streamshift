from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.scene_manager.scene_client import SceneClient


ACTION_DEFINITIONS = [
    {
        "action_id": "scene.scene_tile",
        "title":     "Scene Tile",
        "description": "Compact scene-switcher card showing all scenes.",
        "icon": "SC",
        "page": "Scene Manager",
        "group": "Scene Manager",
    },
    {
        "action_id": "scene.open_panel",
        "title":     "Open Scene Manager",
        "description": "Open the Scene Manager workspace.",
        "icon": "SC",
        "page": "Scene Manager",
        "group": "Scene Manager",
        "default_shortcut": "Ctrl+Alt+S",
    },
    {
        "action_id": "scene.refresh",
        "title":     "Refresh Scenes",
        "description": "Re-fetch the scene list from OBS.",
        "icon": "RF",
        "page": "Scene Manager",
        "group": "Scene Manager",
    },
]
