from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PATH = Path.home() / ".streamshift" / "macro_manager" / "raid_targets.json"


class RaidTargetStore:
    """Persists the raid-target favourites list across sessions."""

    @staticmethod
    def load() -> list[str]:
        try:
            return json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    @staticmethod
    def save(targets: list[str]) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(targets), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save raid targets: %s", exc)

    @staticmethod
    def add(username: str) -> None:
        username = username.lower().strip().lstrip("@")
        if not username:
            return
        targets = RaidTargetStore.load()
        if username not in targets:
            targets.append(username)
            RaidTargetStore.save(targets)

    @staticmethod
    def remove(username: str) -> None:
        username = username.lower().strip()
        targets = [t for t in RaidTargetStore.load() if t != username]
        RaidTargetStore.save(targets)
