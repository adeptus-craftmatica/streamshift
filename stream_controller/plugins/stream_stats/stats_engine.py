from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from PySide6.QtCore import QObject, Signal

from stream_controller.plugins.stream_stats.stats_models import (
    ConnectionStatus, LiveStats, SessionRecord
)

logger = logging.getLogger(__name__)


class _Signals(QObject):
    stats_changed = Signal()


class StatsEngine:
    """
    Owns the live session stats and history.
    All public mutators are thread-safe (called from EventSub background thread).
    Notifies UI subscribers on the Qt main thread via queued signals.
    """

    def __init__(self) -> None:
        self._signals  = _Signals()
        self._signals.stats_changed.connect(self._notify)
        self._live     = LiveStats()
        self._repo     = None   # injected by plugin after construction
        self._subscribers: list[Callable[[LiveStats], None]] = []

    def set_repo(self, repo) -> None:
        self._repo = repo

    # ── public (thread-safe) ──────────────────────────────────────────────────

    @property
    def live(self) -> LiveStats:
        return self._live

    def subscribe(self, cb: Callable[[LiveStats], None]) -> None:
        if cb not in self._subscribers:
            self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    def set_status(self, status: ConnectionStatus, error: str = "") -> None:
        self._live.status = status
        self._live.error  = error
        self._signals.stats_changed.emit()

    def start_session(self) -> None:
        self._live.followers_gained = 0
        self._live.bits_donated     = 0
        self._live.new_subs         = 0
        self._live.gifted_subs      = 0
        self._live.latest_follower  = ""
        self._live.session_active   = True
        self._session_id   = str(uuid.uuid4())
        self._session_start = datetime.now(timezone.utc).isoformat()
        self._signals.stats_changed.emit()
        logger.info("Stream Stats session started: %s", self._session_id)

    def end_session(self, stream_title: str = "") -> SessionRecord | None:
        if not self._live.session_active:
            return None
        self._live.session_active = False
        ended = datetime.now(timezone.utc).isoformat()
        record = SessionRecord(
            session_id       = self._session_id,
            started_at       = self._session_start,
            ended_at         = ended,
            stream_title     = stream_title,
            followers_gained = self._live.followers_gained,
            total_followers  = self._live.total_followers,
            bits_donated     = self._live.bits_donated,
            new_subs         = self._live.new_subs,
            gifted_subs      = self._live.gifted_subs,
            latest_follower  = self._live.latest_follower,
        )
        if self._repo:
            self._repo.add_session(record)
        self._signals.stats_changed.emit()
        logger.info("Stream Stats session saved: %s", self._session_id)
        return record

    def set_total_followers(self, count: int) -> None:
        self._live.total_followers = count
        self._signals.stats_changed.emit()

    def add_follower(self, username: str) -> None:
        if self._live.session_active:
            self._live.followers_gained += 1
        self._live.latest_follower = username
        self._signals.stats_changed.emit()

    def add_bits(self, amount: int) -> None:
        if self._live.session_active:
            self._live.bits_donated += amount
        self._signals.stats_changed.emit()

    def add_sub(self) -> None:
        if self._live.session_active:
            self._live.new_subs += 1
        self._signals.stats_changed.emit()

    def add_gifted_subs(self, count: int) -> None:
        if self._live.session_active:
            self._live.gifted_subs += count
        self._signals.stats_changed.emit()

    # ── internal ──────────────────────────────────────────────────────────────

    def _notify(self) -> None:
        stats = self._live
        for cb in list(self._subscribers):
            try:
                cb(stats)
            except RuntimeError:
                self._subscribers = [s for s in self._subscribers if s is not cb]
