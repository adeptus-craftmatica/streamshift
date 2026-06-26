from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from stream_controller.core.keyring_helper import (
    load as _kr_load, store as _kr_store, migrate_from_dict,
)

logger = logging.getLogger(__name__)

_NAMESPACE = "chat_manager"
_SENSITIVE = {"oauth_token"}

_DEFAULTS = {
    "channel": "",
    "oauth_token": "",
    "username": "",
    "client_id": "",
    "max_messages": 500,
    "overlay_accent": "7c3aed",
    "overlay_bg": "0d0d0f",
    "overlay_opacity": 90,
    "overlay_text": "f0f0ff",
    "overlay_font_size": 14,
    "auto_connect": False,
    "show_badges": True,
    "show_timestamps": False,
    "highlight_mentions": True,
}


class ChatRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                migrated = migrate_from_dict(data, _NAMESPACE, _SENSITIVE)
                if migrated != data:
                    self._data = migrated
                    self._save()
                else:
                    self._data = data
            except Exception as exc:
                logger.warning("Could not load chat settings: %s", exc)
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        safe = {k: v for k, v in self._data.items() if k not in _SENSITIVE}
        try:
            self._path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.warning("Could not save chat settings: %s", exc)

    def get(self, key: str):
        if key in _SENSITIVE:
            return _kr_load(_NAMESPACE, key)
        return self._data.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if key in _SENSITIVE:
            _kr_store(_NAMESPACE, key, str(value) if value else "")
        else:
            self._data[key] = value
            self._save()

    def get_all(self) -> dict:
        result = dict(_DEFAULTS)
        result.update(self._data)
        # Merge live keychain values so callers see the full picture
        for k in _SENSITIVE:
            result[k] = _kr_load(_NAMESPACE, k)
        return result
