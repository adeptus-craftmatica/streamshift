from __future__ import annotations

import logging
import time
from typing import Callable

from stream_controller.plugins.timer_manager.timer_models import (
    Timer, TimerMode, TimerStatus, make_timer
)
from stream_controller.plugins.timer_manager.timer_repository import TimerRepository

logger = logging.getLogger(__name__)


class TimerEngine:
    """
    Manages a collection of timers. Call tick() from a 100ms QTimer.
    Thread-safe for reads; only mutated from the Qt main thread.
    """

    def __init__(self, repo: TimerRepository) -> None:
        self._repo = repo
        self._timers: dict[str, Timer] = dict(repo.timers)
        self._listeners: list[Callable[[list[Timer]], None]] = []
        self._last_tick: float = 0.0
        self._active_id: str | None = None  # for deck actions

    # ── timers ────────────────────────────────────────────────────────────────

    @property
    def timers(self) -> list[Timer]:
        return list(self._timers.values())

    @property
    def active_timer(self) -> Timer | None:
        if self._active_id and self._active_id in self._timers:
            return self._timers[self._active_id]
        running = [t for t in self._timers.values() if t.status == TimerStatus.RUNNING]
        return running[0] if running else (self.timers[0] if self._timers else None)

    def get(self, timer_id: str) -> Timer | None:
        return self._timers.get(timer_id)

    def add_timer(self, label: str, mode: TimerMode, duration: float,
                  color: str = "7c3aed", end_message: str = "Time's up!",
                  loop: bool = False) -> Timer:
        t = make_timer(label, mode, duration,
                       color=color, end_message=end_message, loop=loop)
        self._timers[t.timer_id] = t
        self._save()
        self._notify()
        return t

    def update_timer(self, timer_id: str, **kwargs) -> None:
        t = self._timers.get(timer_id)
        if not t:
            return
        for k, v in kwargs.items():
            if hasattr(t, k):
                setattr(t, k, v)
        self._save()
        self._notify()

    def remove_timer(self, timer_id: str) -> None:
        self._timers.pop(timer_id, None)
        if self._active_id == timer_id:
            self._active_id = None
        self._save()
        self._notify()

    # ── transport ─────────────────────────────────────────────────────────────

    def start(self, timer_id: str) -> None:
        t = self._timers.get(timer_id)
        if not t:
            return
        if t.status == TimerStatus.FINISHED:
            t.elapsed = 0.0
        t.status = TimerStatus.RUNNING
        self._active_id = timer_id
        self._last_tick = time.monotonic()
        self._notify()

    def pause(self, timer_id: str) -> None:
        t = self._timers.get(timer_id)
        if t and t.status == TimerStatus.RUNNING:
            t.status = TimerStatus.PAUSED
            self._notify()

    def stop(self, timer_id: str) -> None:
        t = self._timers.get(timer_id)
        if t:
            t.status = TimerStatus.IDLE
            t.elapsed = 0.0
            self._notify()

    def reset(self, timer_id: str) -> None:
        t = self._timers.get(timer_id)
        if t:
            was_running = t.status == TimerStatus.RUNNING
            t.elapsed = 0.0
            t.status = TimerStatus.RUNNING if was_running else TimerStatus.IDLE
            self._notify()

    def toggle(self, timer_id: str) -> None:
        t = self._timers.get(timer_id)
        if not t:
            return
        if t.status == TimerStatus.RUNNING:
            self.pause(timer_id)
        else:
            self.start(timer_id)

    # Active-timer shortcuts for deck actions
    def start_active(self) -> None:
        t = self.active_timer
        if t:
            self.start(t.timer_id)

    def pause_active(self) -> None:
        t = self.active_timer
        if t:
            self.pause(t.timer_id)

    def stop_active(self) -> None:
        t = self.active_timer
        if t:
            self.stop(t.timer_id)

    def reset_active(self) -> None:
        t = self.active_timer
        if t:
            self.reset(t.timer_id)

    def toggle_active(self) -> None:
        t = self.active_timer
        if t:
            self.toggle(t.timer_id)

    # ── tick ──────────────────────────────────────────────────────────────────

    def tick(self) -> None:
        now = time.monotonic()
        if self._last_tick == 0.0:
            self._last_tick = now
            return

        dt = now - self._last_tick
        self._last_tick = now

        changed = False
        for t in self._timers.values():
            if t.status != TimerStatus.RUNNING:
                continue
            t.elapsed += dt
            if t.mode == TimerMode.COUNTDOWN and t.duration > 0:
                if t.elapsed >= t.duration:
                    if t.loop:
                        t.elapsed = 0.0
                    else:
                        t.elapsed = t.duration
                        t.status = TimerStatus.FINISHED
            changed = True

        if changed:
            self._notify()

    # ── subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, cb: Callable[[list[Timer]], None]) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._listeners = [l for l in self._listeners if l is not cb]

    def _notify(self) -> None:
        from PySide6.QtCore import QTimer, QThread, QCoreApplication
        app = QCoreApplication.instance()
        if app and QThread.currentThread() is not app.thread():
            snapshot = list(self._timers.values())
            QTimer.singleShot(0, lambda: self._notify_main(snapshot))
            return
        self._notify_main(list(self._timers.values()))

    def _notify_main(self, snapshot: list) -> None:
        for cb in list(self._listeners):  # copy so removal during iteration is safe
            try:
                cb(snapshot)
            except RuntimeError:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass
            except Exception:
                pass

    def _save(self) -> None:
        self._repo.save_timers(list(self._timers.values()))
