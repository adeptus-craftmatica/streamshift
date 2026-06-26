from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".streamshift" / "stage_layout.json"


class StageLayout:
    """Persists panel positions and sizes to JSON."""

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._panels: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._panels = data.get("panels", [])
            except Exception as exc:
                logger.warning("Could not load stage layout: %s", exc)

    def save(self, panels: list[dict]) -> None:
        self._panels = panels
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"panels": panels}, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not save stage layout: %s", exc)

    @property
    def panels(self) -> list[dict]:
        return list(self._panels)
