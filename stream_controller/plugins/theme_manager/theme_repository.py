from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from stream_controller.plugins.theme_manager.theme_models import (
    BUILTIN_THEME_MAP, AppTheme,
)

logger = logging.getLogger(__name__)

_ACTIVE_KEY = "active_theme_id"


class ThemeRepository:
    """
    Persists custom themes and the active theme selection.
    Built-in themes are never stored on disk — they live in theme_models.py.
    """

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir
        self._custom_file = data_dir / "custom_themes.json"
        self._prefs_file = data_dir / "prefs.json"
        self._custom: dict[str, AppTheme] = {}
        self._prefs: dict = {}
        self._load()

    # ── active theme ──────────────────────────────────────────────────────────

    def get_active_theme_id(self) -> str:
        return self._prefs.get(_ACTIVE_KEY, "midnight")

    def set_active_theme_id(self, theme_id: str) -> None:
        self._prefs[_ACTIVE_KEY] = theme_id
        self._save_prefs()

    def get_active_theme(self) -> AppTheme:
        tid = self.get_active_theme_id()
        return (
            BUILTIN_THEME_MAP.get(tid)
            or self._custom.get(tid)
            or BUILTIN_THEME_MAP["midnight"]
        )

    # ── custom themes ─────────────────────────────────────────────────────────

    def list_custom(self) -> list[AppTheme]:
        return list(self._custom.values())

    def save_custom(self, theme: AppTheme) -> None:
        theme.builtin = False
        self._custom[theme.theme_id] = theme
        self._flush_custom()

    def delete_custom(self, theme_id: str) -> None:
        self._custom.pop(theme_id, None)
        self._flush_custom()

    def get(self, theme_id: str) -> AppTheme | None:
        return BUILTIN_THEME_MAP.get(theme_id) or self._custom.get(theme_id)

    # ── panel overrides for active theme ─────────────────────────────────────

    def save_panel_override_to_active(self, panel_id: str, panel_theme) -> None:
        """
        Panel overrides are stored alongside the theme they belong to.
        For built-in themes, overrides are stored in prefs so the built-in is unchanged.
        """
        active = self.get_active_theme()
        if active.builtin:
            # Store overrides in prefs file keyed by theme_id
            key = f"panel_overrides_{active.theme_id}"
            overrides = self._prefs.get(key, {})
            overrides[panel_id] = panel_theme.to_dict()
            self._prefs[key] = overrides
            self._save_prefs()
        else:
            active.panel_overrides[panel_id] = panel_theme
            self.save_custom(active)

    def get_panel_overrides_for_active(self) -> dict:
        active = self.get_active_theme()
        if active.builtin:
            key = f"panel_overrides_{active.theme_id}"
            return self._prefs.get(key, {})
        return {k: v.to_dict() for k, v in active.panel_overrides.items()}

    # ── internal ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._custom_file.exists():
            try:
                raw = json.loads(self._custom_file.read_text(encoding="utf-8"))
                self._custom = {
                    d["theme_id"]: AppTheme.from_dict(d)
                    for d in raw
                    if isinstance(d, dict) and "theme_id" in d
                }
            except Exception as exc:
                logger.warning("Could not load custom themes: %s", exc)

        if self._prefs_file.exists():
            try:
                self._prefs = json.loads(self._prefs_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not load theme prefs: %s", exc)

    def _flush_custom(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._custom_file.write_text(
                json.dumps([t.to_dict() for t in self._custom.values()], indent=2),
                encoding="utf-8",
            )
            os.chmod(self._custom_file, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.error("Could not save custom themes: %s", exc)

    def _save_prefs(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._prefs_file.write_text(
                json.dumps(self._prefs, indent=2), encoding="utf-8"
            )
            os.chmod(self._prefs_file, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.error("Could not save theme prefs: %s", exc)
