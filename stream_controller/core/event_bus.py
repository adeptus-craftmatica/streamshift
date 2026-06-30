from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, DefaultDict

EventCallback = Callable[[Any], None]

logger = logging.getLogger(__name__)


class EventBus:
    """Simple publish-subscribe event bus for app and plugin communication."""

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, list[EventCallback]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: EventCallback) -> None:
        subscribers = self._subscribers[event_name]
        if callback not in subscribers:
            subscribers.append(callback)

    def emit(self, event_name: str, payload: Any = None) -> None:
        for callback in list(self._subscribers.get(event_name, [])):
            try:
                callback(payload)
            except Exception:
                logger.exception("Event handler failed for '%s'.", event_name)

    def unsubscribe(self, event_name: str, callback: EventCallback) -> None:
        subscribers = self._subscribers.get(event_name)
        if not subscribers:
            return

        if callback in subscribers:
            subscribers.remove(callback)

        if not subscribers:
            self._subscribers.pop(event_name, None)
