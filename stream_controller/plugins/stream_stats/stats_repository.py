from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from stream_controller.core.keyring_helper import (
    load as _kr_load, store as _kr_store, migrate_from_dict,
)
from stream_controller.plugins.stream_stats.stats_models import SessionRecord

logger = logging.getLogger(__name__)

_NAMESPACE = "stream_stats"
_SENSITIVE = {"oauth_token"}

_DEFAULTS: dict = {
    "client_id":       "",
    "oauth_token":     "",
    "broadcaster_id":  "",
    "channel":         "",
    "auto_connect":    False,
}


class StatsRepository:
    def __init__(self, data_dir: Path) -> None:
        self._settings_path = data_dir / "settings.json"
        self._history_path  = data_dir / "history.json"
        self._settings: dict = {}
        self._history: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._settings_path.exists():
            try:
                data = json.loads(self._settings_path.read_text(encoding="utf-8"))
                # One-time migration: move sensitive values from JSON → keychain
                migrated = migrate_from_dict(data, _NAMESPACE, _SENSITIVE)
                if migrated != data:
                    self._settings = migrated
                    self._save_settings()
                else:
                    self._settings = data
            except Exception as exc:
                logger.warning("Could not load stats settings: %s", exc)
        if self._history_path.exists():
            try:
                self._history = json.loads(self._history_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not load stats history: %s", exc)

    def get(self, key: str):
        if key in _SENSITIVE:
            return _kr_load(_NAMESPACE, key)
        return self._settings.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if key in _SENSITIVE:
            _kr_store(_NAMESPACE, key, str(value) if value else "")
        else:
            self._settings[key] = value
            self._save_settings()

    def _save_settings(self) -> None:
        # Strip any sensitive keys that may have crept in before writing
        safe = {k: v for k, v in self._settings.items() if k not in _SENSITIVE}
        try:
            self._settings_path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
            os.chmod(self._settings_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.warning("Could not save stats settings: %s", exc)

    # ── history ───────────────────────────────────────────────────────────────

    def add_session(self, record: SessionRecord) -> None:
        self._history.insert(0, record.to_dict())
        self._save_history()

    def sessions(self) -> list[SessionRecord]:
        return [SessionRecord.from_dict(d) for d in self._history]

    def _save_history(self) -> None:
        try:
            self._history_path.write_text(
                json.dumps(self._history, indent=2), encoding="utf-8"
            )
            os.chmod(self._history_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.warning("Could not save stats history: %s", exc)
