from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SettingsManager:
    """Persists lightweight app and plugin settings to a local JSON file."""

    PLUGIN_SETTINGS_KEY = "plugin_settings"
    HOTKEY_BINDINGS_KEY = "hotkeys.bindings"
    DECK_STATE_KEY = "deck.state"

    def __init__(self, settings_path: Path | None = None) -> None:
        default_path = Path.home() / ".stream_controller" / "settings.json"
        self._settings_path = settings_path or default_path
        self._settings: dict[str, Any] = {}
        self.reload()

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        self._settings[key] = value
        if save:
            self.save()

    def all(self) -> dict[str, Any]:
        return dict(self._settings)

    def save(self) -> None:
        import os, stat as _stat
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._settings_path.write_text(
                json.dumps(self._settings, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.chmod(self._settings_path, _stat.S_IRUSR | _stat.S_IWUSR)
        except Exception as exc:
            logger.error("Failed to save settings to %s: %s", self._settings_path, exc)
            raise

    def get_plugin_settings(self, plugin_id: str) -> dict[str, Any]:
        plugin_settings = self._settings.get(self.PLUGIN_SETTINGS_KEY, {})
        if not isinstance(plugin_settings, dict):
            return {}

        values = plugin_settings.get(plugin_id, {})
        return dict(values) if isinstance(values, dict) else {}

    def get_plugin_setting(self, plugin_id: str, setting_key: str, default: Any = None) -> Any:
        return self.get_plugin_settings(plugin_id).get(setting_key, default)

    def set_plugin_settings(self, plugin_id: str, values: dict[str, Any], save: bool = True) -> None:
        plugin_settings = self._settings.setdefault(self.PLUGIN_SETTINGS_KEY, {})
        if not isinstance(plugin_settings, dict):
            plugin_settings = {}
            self._settings[self.PLUGIN_SETTINGS_KEY] = plugin_settings

        plugin_settings[plugin_id] = dict(values)
        if save:
            self.save()

    def set_plugin_setting(
        self,
        plugin_id: str,
        setting_key: str,
        value: Any,
        save: bool = True,
    ) -> None:
        values = self.get_plugin_settings(plugin_id)
        values[setting_key] = value
        self.set_plugin_settings(plugin_id, values, save=save)

    def reset_plugin_settings(self, plugin_id: str, save: bool = True) -> None:
        plugin_settings = self._settings.get(self.PLUGIN_SETTINGS_KEY)
        if isinstance(plugin_settings, dict):
            plugin_settings.pop(plugin_id, None)
            if not plugin_settings:
                self._settings.pop(self.PLUGIN_SETTINGS_KEY, None)

        if save:
            self.save()

    def get_hotkey_bindings(self) -> dict[str, str | None]:
        raw_bindings = self._settings.get(self.HOTKEY_BINDINGS_KEY, {})
        if not isinstance(raw_bindings, dict):
            return {}

        bindings: dict[str, str | None] = {}
        for action_id, shortcut in raw_bindings.items():
            normalized_action_id = str(action_id)
            bindings[normalized_action_id] = None if shortcut is None else str(shortcut)
        return bindings

    def set_hotkey_bindings(self, bindings: dict[str, str | None], save: bool = True) -> None:
        normalized_bindings = {
            str(action_id): None if shortcut is None else str(shortcut)
            for action_id, shortcut in bindings.items()
        }

        if normalized_bindings:
            self._settings[self.HOTKEY_BINDINGS_KEY] = normalized_bindings
        else:
            self._settings.pop(self.HOTKEY_BINDINGS_KEY, None)

        if save:
            self.save()

    def reset_hotkey_bindings(
        self,
        action_ids: list[str] | tuple[str, ...] | None = None,
        save: bool = True,
    ) -> None:
        if action_ids is None:
            self._settings.pop(self.HOTKEY_BINDINGS_KEY, None)
        else:
            bindings = self.get_hotkey_bindings()
            for action_id in action_ids:
                bindings.pop(str(action_id), None)
            self.set_hotkey_bindings(bindings, save=False)

        if save:
            self.save()

    def get_deck_state(self) -> dict[str, Any]:
        raw_state = self._settings.get(self.DECK_STATE_KEY, {})
        return dict(raw_state) if isinstance(raw_state, dict) else {}

    def set_deck_state(self, state: dict[str, Any], save: bool = True) -> None:
        self._settings[self.DECK_STATE_KEY] = dict(state)
        if save:
            self.save()

    def reload(self) -> None:
        if not self._settings_path.exists():
            self._settings = {}
            return

        try:
            self._settings = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Settings file at %s could not be read. Starting with empty settings.",
                self._settings_path,
            )
            self._settings = {}
