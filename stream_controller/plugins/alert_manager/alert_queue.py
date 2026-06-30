from __future__ import annotations

import threading
from collections import deque
from typing import Callable

from .alert_models import AlertConfig, AlertEvent, AlertType


class AlertQueue:
    """Sequential alert playback queue. Processes one alert at a time,
    waiting for each alert's duration before playing the next."""

    def __init__(
        self,
        get_config: Callable[[AlertType], AlertConfig],
        on_alert: Callable[[AlertEvent], None],
    ) -> None:
        self._get_config = get_config
        self._on_alert = on_alert
        self._queue: deque[AlertEvent] = deque()
        self._lock = threading.Lock()
        self._has_items = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def enqueue(self, event: AlertEvent) -> None:
        config = self._get_config(event.alert_type)
        if not config.enabled:
            return
        with self._lock:
            self._queue.append(event)
        self._has_items.set()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="AlertQueue"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._has_items.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._has_items.wait(timeout=1.0)
            self._has_items.clear()
            while not self._stop_event.is_set():
                with self._lock:
                    if not self._queue:
                        break
                    event = self._queue.popleft()
                config = self._get_config(event.alert_type)
                if not config.enabled:
                    continue
                self._on_alert(event)
                # Wait duration + small buffer before next alert
                duration_s = config.duration_ms / 1000.0
                self._stop_event.wait(timeout=duration_s + 0.5)
