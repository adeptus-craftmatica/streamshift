from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from stream_controller.plugins.scene_designer.designer_models import DesignerScene

logger = logging.getLogger(__name__)


class DesignerRepository:
    """Persists designer scenes as a JSON list on disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._scenes: dict[str, DesignerScene] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def list_scenes(self) -> list[DesignerScene]:
        return list(self._scenes.values())

    def get(self, scene_id: str) -> DesignerScene | None:
        return self._scenes.get(scene_id)

    def save_scene(self, scene: DesignerScene) -> None:
        self._scenes[scene.scene_id] = scene
        self._flush()

    def delete_scene(self, scene_id: str) -> None:
        self._scenes.pop(scene_id, None)
        self._flush()

    def rename_scene(self, scene_id: str, name: str) -> None:
        scene = self._scenes.get(scene_id)
        if scene:
            scene.name = name.strip() or scene.name
            self._flush()

    # ── internal ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            self._scenes = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._scenes = {
                d["scene_id"]: DesignerScene.from_dict(d)
                for d in raw
                if isinstance(d, dict) and "scene_id" in d
            }
        except Exception as exc:
            logger.warning("Could not load scenes.json: %s", exc)
            self._scenes = {}

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([s.to_dict() for s in self._scenes.values()], indent=2),
                encoding="utf-8",
            )
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.error("Could not save scenes.json: %s", exc)
