from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable

from stream_controller.plugins.redemption_tracker.redemption_models import (
    ItemStatus, QueueItem,
)

logger = logging.getLogger(__name__)

_MAX_COMPLETED = 100  # keep the last N completed items


class RedemptionStore:
    """Thread-safe in-memory store with JSON persistence."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._items: list[QueueItem] = []
        self._listeners: list[Callable[[], None]] = []
        self._load()

    # ── listeners ─────────────────────────────────────────────────────────────

    def add_listener(self, cb: Callable[[], None]) -> None:
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[], None]) -> None:
        with self._lock:
            self._listeners = [l for l in self._listeners if l is not cb]

    # ── mutations ─────────────────────────────────────────────────────────────

    def add(self, item: QueueItem) -> None:
        with self._lock:
            self._items.insert(0, item)
        self._save()
        self._notify()

    def complete(self, item_id: str) -> QueueItem | None:
        with self._lock:
            item = self._find(item_id)
            if item:
                item.status = ItemStatus.COMPLETED
        if item:
            self._prune_completed()
            self._save()
            self._notify()
        return item

    def cancel(self, item_id: str) -> QueueItem | None:
        with self._lock:
            item = self._find(item_id)
            if item:
                item.status = ItemStatus.CANCELLED
        if item:
            self._prune_completed()
            self._save()
            self._notify()
        return item

    def clear_completed(self) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.status == ItemStatus.PENDING]
        self._save()
        self._notify()

    # ── queries ───────────────────────────────────────────────────────────────

    def pending(self) -> list[QueueItem]:
        with self._lock:
            return [i for i in self._items if i.status == ItemStatus.PENDING]

    def all_items(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items)

    # ── private ───────────────────────────────────────────────────────────────

    def _find(self, item_id: str) -> QueueItem | None:
        for item in self._items:
            if item.item_id == item_id:
                return item
        return None

    def _prune_completed(self) -> None:
        with self._lock:
            pending = [i for i in self._items if i.status == ItemStatus.PENDING]
            done = [i for i in self._items if i.status != ItemStatus.PENDING]
            self._items = pending + done[:_MAX_COMPLETED]

    def _notify(self) -> None:
        with self._lock:
            cbs = list(self._listeners)
        for cb in cbs:
            try:
                cb()
            except Exception:
                pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = [i.to_dict() for i in self._items]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("RedemptionStore: save failed")

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._items = [QueueItem.from_dict(d) for d in data]
        except Exception:
            logger.exception("RedemptionStore: load failed")
