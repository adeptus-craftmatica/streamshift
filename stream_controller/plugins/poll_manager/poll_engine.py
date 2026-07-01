from __future__ import annotations

import threading
from typing import Callable

from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus, Poll, PollState


class PollEngine:
    def __init__(self) -> None:
        self._state = PollState()
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[PollState], None]] = []

    def subscribe(self, cb: Callable[[PollState], None]) -> None:
        self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable[[PollState], None]) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    @property
    def state(self) -> PollState:
        return self._state

    def set_status(self, status: ConnectionStatus, error: str = "") -> None:
        with self._lock:
            self._state.connection_status = status
            self._state.connection_error = error
        self._notify()

    def set_active_poll(self, poll: "Poll | None") -> None:
        with self._lock:
            self._state.active_poll = poll
        self._notify()

    def set_recent_polls(self, polls: "list[Poll]") -> None:
        with self._lock:
            self._state.recent_polls = polls
        self._notify()

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            try:
                cb(self._state)
            except Exception:
                pass
