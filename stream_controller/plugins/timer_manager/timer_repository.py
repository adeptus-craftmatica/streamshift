from __future__ import annotations

import json
import logging
from pathlib import Path

from stream_controller.plugins.timer_manager.timer_models import (
    Timer, TimerMode, TimerStatus
)

logger = logging.getLogger(__name__)


class TimerRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._settings_path = path.parent / "settings.json"
        self._timers: dict[str, Timer] = {}
        self._settings: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    t = Timer(
                        timer_id=d["timer_id"],
                        label=d["label"],
                        mode=TimerMode(d["mode"]),
                        duration=float(d["duration"]),
                        elapsed=0.0,                    # always reset on load
                        status=TimerStatus.IDLE,
                        color=d.get("color", "7c3aed"),
                        end_message=d.get("end_message", "Time's up!"),
                        loop=bool(d.get("loop", False)),
                    )
                    self._timers[t.timer_id] = t
            except Exception as exc:
                logger.warning("Could not load timers: %s", exc)

        if self._settings_path.exists():
            try:
                self._settings = json.loads(self._settings_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def save_timers(self, timers: list[Timer]) -> None:
        try:
            data = [
                {
                    "timer_id":    t.timer_id,
                    "label":       t.label,
                    "mode":        t.mode.value,
                    "duration":    t.duration,
                    "color":       t.color,
                    "end_message": t.end_message,
                    "loop":        t.loop,
                }
                for t in timers
            ]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save timers: %s", exc)

    @property
    def timers(self) -> dict[str, Timer]:
        return self._timers

    def get_setting(self, key: str, default=None):
        return self._settings.get(key, default)

    def set_setting(self, key: str, value) -> None:
        self._settings[key] = value
        try:
            self._settings_path.write_text(
                json.dumps(self._settings, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
