from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULTS: dict = {
    "mic_device_index": None,
    "mic_threshold": 0.02,
    "talk_hold_frames": 8,
    "blink_enabled": True,
    "chroma_color": "00ff00",
    "canvas_width": 800,
    "canvas_height": 800,
    "expressions": {
        "default": {
            "idle": "",
            "talking": "",
            "idle_blink": "",
            "talking_blink": "",
        }
    },
    "active_expression": "default",
    "auto_start": False,
    "sets": {},
    "active_set": "",
}

_SET_KEYS = ("expressions", "active_expression", "chroma_color", "canvas_width", "canvas_height", "blink_enabled")


class PngTuberRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not load pngtuber settings: %s", exc)
        else:
            self._data = {}

    def get(self, key: str):
        val = self._data.get(key)
        if val is None:
            return _DEFAULTS.get(key)
        return val

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save pngtuber settings: %s", exc)

    def get_expression(self, name: str) -> dict:
        expressions = self.get("expressions") or {}
        return expressions.get(name, {"idle": "", "talking": "", "idle_blink": "", "talking_blink": ""})

    def set_expression(self, name: str, layers: dict) -> None:
        expressions = dict(self.get("expressions") or {})
        expressions[name] = layers
        self.set("expressions", expressions)

    def delete_expression(self, name: str) -> None:
        expressions = dict(self.get("expressions") or {})
        expressions.pop(name, None)
        if not expressions:
            expressions = {"default": {"idle": "", "talking": "", "idle_blink": "", "talking_blink": ""}}
        self.set("expressions", expressions)
        if self.get("active_expression") == name:
            self.set("active_expression", next(iter(expressions)))

    def list_expressions(self) -> list[str]:
        return list((self.get("expressions") or {}).keys())

    # ── Sets ──────────────────────────────────────────────────────────────────

    def list_sets(self) -> list[str]:
        return list((self._data.get("sets") or {}).keys())

    def save_set(self, name: str) -> None:
        sets = dict(self._data.get("sets") or {})
        sets[name] = {k: self.get(k) for k in _SET_KEYS}
        self._data["sets"] = sets
        self._data["active_set"] = name
        self._save()

    def load_set(self, name: str) -> bool:
        sets = self._data.get("sets") or {}
        if name not in sets:
            return False
        snapshot = sets[name]
        for k, v in snapshot.items():
            if k in _SET_KEYS:
                self._data[k] = v
        self._data["active_set"] = name
        self._save()
        return True

    def delete_set(self, name: str) -> None:
        sets = dict(self._data.get("sets") or {})
        sets.pop(name, None)
        self._data["sets"] = sets
        if self._data.get("active_set") == name:
            self._data["active_set"] = next(iter(sets), "")
        self._save()

    def duplicate_set(self, source: str, dest: str) -> None:
        sets = dict(self._data.get("sets") or {})
        if source not in sets or not dest:
            return
        import copy
        sets[dest] = copy.deepcopy(sets[source])
        self._data["sets"] = sets
        self._save()

    def rename_set(self, old: str, new: str) -> None:
        sets = dict(self._data.get("sets") or {})
        if old not in sets or not new:
            return
        sets[new] = sets.pop(old)
        self._data["sets"] = sets
        if self._data.get("active_set") == old:
            self._data["active_set"] = new
        self._save()
