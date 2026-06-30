from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".streamshift" / "redemption_tracker" / "reward_actions.json"


class RewardActionMapping:
    """
    Persists a mapping of {reward_name_lower: action_id}.
    Reward name matching is case-insensitive and strips whitespace.
    """

    def __init__(self, path: Path = _CONFIG_PATH) -> None:
        self._path = path
        self._mappings: dict[str, str] = {}
        self._load()

    def _key(self, reward_name: str) -> str:
        return reward_name.strip().lower()

    def set(self, reward_name: str, action_id: str) -> None:
        self._mappings[self._key(reward_name)] = action_id
        self._save()

    def remove(self, reward_name: str) -> None:
        self._mappings.pop(self._key(reward_name), None)
        self._save()

    def get_action(self, reward_name: str) -> str | None:
        return self._mappings.get(self._key(reward_name))

    def all_mappings(self) -> list[tuple[str, str]]:
        """Returns list of (reward_name, action_id) in insertion order."""
        return list(self._mappings.items())

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._mappings, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("RewardActionMapping: save failed")

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._mappings = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("RewardActionMapping: load failed")
