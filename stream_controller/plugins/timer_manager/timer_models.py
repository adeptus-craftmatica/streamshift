from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TimerMode(Enum):
    COUNTDOWN = "countdown"
    COUNTUP   = "countup"


class TimerStatus(Enum):
    IDLE     = "idle"
    RUNNING  = "running"
    PAUSED   = "paused"
    FINISHED = "finished"


@dataclass
class Timer:
    timer_id:    str
    label:       str
    mode:        TimerMode
    duration:    float          # seconds; 0 means open-ended countup
    elapsed:     float = 0.0
    status:      TimerStatus = TimerStatus.IDLE
    color:       str = "7c3aed"   # hex without #
    end_message: str = "Time's up!"
    loop:        bool = False

    # ── computed ──────────────────────────────────────────────────────────

    @property
    def remaining(self) -> float:
        if self.mode == TimerMode.COUNTDOWN:
            return max(0.0, self.duration - self.elapsed)
        return self.elapsed   # count-up: remaining == elapsed (displayed time)

    @property
    def progress(self) -> float:
        """0.0 → 1.0. For countup with no duration, always 0."""
        if self.mode == TimerMode.COUNTDOWN and self.duration > 0:
            return min(1.0, self.elapsed / self.duration)
        if self.mode == TimerMode.COUNTUP and self.duration > 0:
            return min(1.0, self.elapsed / self.duration)
        return 0.0

    @property
    def display_time(self) -> str:
        secs = self.remaining if self.mode == TimerMode.COUNTDOWN else self.elapsed
        return _fmt(secs)

    @property
    def is_finished(self) -> bool:
        return self.status == TimerStatus.FINISHED

    def to_dict(self) -> dict:
        return {
            "id":          self.timer_id,
            "label":       self.label,
            "mode":        self.mode.value,
            "status":      self.status.value,
            "duration":    self.duration,
            "elapsed":     self.elapsed,
            "remaining":   self.remaining,
            "progress":    self.progress,
            "display":     self.display_time,
            "color":       self.color,
            "end_message": self.end_message,
            "loop":        self.loop,
        }


def _fmt(secs: float) -> str:
    secs = max(0.0, secs)
    h = int(secs) // 3600
    m = (int(secs) % 3600) // 60
    s = int(secs) % 60
    ms = int((secs % 1) * 10)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def make_timer(label: str, mode: TimerMode, duration: float, **kwargs) -> Timer:
    return Timer(
        timer_id=uuid.uuid4().hex[:12],
        label=label,
        mode=mode,
        duration=duration,
        **kwargs,
    )
