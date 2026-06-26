from __future__ import annotations

import json
import logging
from pathlib import Path

from stream_controller.core.keyring_helper import (
    load as _kr_load,
    store as _kr_store,
    delete as _kr_delete,
)

logger = logging.getLogger(__name__)

_NS = "social_manager"
_SENSITIVE = {"bluesky_app_password"}

_DEFAULTS: dict = {
    "bluesky_handle": "",
    "bluesky_enabled": False,
    "templates": [
        {
            "id": "going_live",
            "name": "Going Live",
            "text": "🔴 Going live now on Twitch!\n\n{title}\n\nCome hang out → {url}",
            "include_image": False,
            "image_path": "",
        },
        {
            "id": "break",
            "name": "Short Break",
            "text": "Taking a quick break — back in a few minutes! 🎮",
            "include_image": False,
            "image_path": "",
        },
    ],
    "social_handles": {
        "bluesky": "",
        "instagram": "",
        "twitter": "",
    },
    "bot_commands": [
        {"command": "bluesky", "response": "Follow me on Bluesky: {bluesky_url}"},
        {"command": "instagram", "response": "Everything I build & paint → {instagram_handle}"},
    ],
}


class SocialRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    # ── generic get/set ───────────────────────────────────────────────────────

    def get(self, key: str):
        val = self._data.get(key)
        return val if val is not None else _DEFAULTS.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    # ── sensitive credentials ─────────────────────────────────────────────────

    def get_secret(self, field: str) -> str:
        return _kr_load(_NS, field)

    def set_secret(self, field: str, value: str) -> None:
        _kr_store(_NS, field, value)

    def delete_secret(self, field: str) -> None:
        _kr_delete(_NS, field)

    # ── templates ─────────────────────────────────────────────────────────────

    def list_templates(self) -> list[dict]:
        return list(self._data.get("templates") or _DEFAULTS["templates"])

    def save_template(self, template: dict) -> None:
        templates = list(self._data.get("templates") or [])
        for i, t in enumerate(templates):
            if t.get("id") == template["id"]:
                templates[i] = template
                self._data["templates"] = templates
                self._save()
                return
        templates.append(template)
        self._data["templates"] = templates
        self._save()

    def delete_template(self, template_id: str) -> None:
        templates = [t for t in self.list_templates() if t.get("id") != template_id]
        self._data["templates"] = templates
        self._save()

    def get_template(self, template_id: str) -> dict | None:
        for t in self.list_templates():
            if t.get("id") == template_id:
                return t
        return None

    # ── bot commands ─────────────────────────────────────────────────────────

    def list_bot_commands(self) -> list[dict]:
        return list(self._data.get("bot_commands") or _DEFAULTS["bot_commands"])

    def save_bot_commands(self, commands: list[dict]) -> None:
        self._data["bot_commands"] = commands
        self._save()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                # Strip any accidentally-persisted secrets
                for key in _SENSITIVE:
                    raw.pop(key, None)
                self._data = raw
            except Exception as exc:
                logger.warning("Could not load social settings: %s", exc)
        else:
            self._data = {}

    def _save(self) -> None:
        safe = {k: v for k, v in self._data.items() if k not in _SENSITIVE}
        try:
            self._path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save social settings: %s", exc)
