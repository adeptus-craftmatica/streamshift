from __future__ import annotations

import json
import logging
from pathlib import Path

from stream_controller.core.keyring_helper import load as _kr_load, store as _kr_store

logger = logging.getLogger(__name__)

_NAMESPACE = "poll_manager"
_SENSITIVE = {"oauth_token"}

_DEFAULTS: dict = {
    "client_id":    "",
    "oauth_token":  "",
    "broadcaster_id": "",
    "auto_connect": False,
}


class PollRepository:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "poll_settings.json"
        self._settings: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._settings = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load poll settings: %s", e)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save poll settings: %s", e)

    def get(self, key: str):
        if key in _SENSITIVE:
            return _kr_load(_NAMESPACE, key)
        return self._settings.get(key, _DEFAULTS.get(key))

    # ── Templates ─────────────────────────────────────────────────────────────

    def get_templates(self) -> list[dict]:
        return list(self._settings.get("templates", []))

    def save_template(self, template: dict) -> None:
        templates = self.get_templates()
        for i, t in enumerate(templates):
            if t.get("id") == template.get("id"):
                templates[i] = template
                break
        else:
            templates.append(template)
        self._settings["templates"] = templates
        self._save()

    def delete_template(self, template_id: str) -> None:
        self._settings["templates"] = [
            t for t in self.get_templates() if t.get("id") != template_id
        ]
        self._save()

    def set(self, key: str, value) -> None:
        if key in _SENSITIVE:
            _kr_store(_NAMESPACE, key, str(value) if value else "")
        else:
            self._settings[key] = value
            self._save()
