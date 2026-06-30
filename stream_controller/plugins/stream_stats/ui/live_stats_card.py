from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.plugins.stream_stats.stats_engine import StatsEngine
    from stream_controller.plugins.stream_stats.stats_models import LiveStats

logger = logging.getLogger(__name__)

_HELIX_BASE = "https://api.twitch.tv/helix"
_VIEWER_POLL_MS = 60_000   # re-poll viewer count every 60 s
_UPTIME_TICK_MS = 1_000    # uptime counter ticks every 1 s


class LiveStatsCard(QFrame):
    """Stage panel card: LIVE/OFFLINE badge, uptime, and live viewer count."""

    _viewer_data_ready = Signal(object)   # emits dict | None on bg thread → UI

    def __init__(self, engine: "StatsEngine") -> None:
        super().__init__()
        self._engine = engine
        self._stream_started_at: datetime | None = None
        self._peak_viewers: int = 0
        self._fetching = False

        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Live Stats")
        title.setObjectName("CardTitle")
        header.addWidget(title, 1)
        root.addLayout(header)

        # ── Status badge ──────────────────────────────────────────────────────
        self._badge = QLabel("⚫  OFFLINE")
        self._badge.setObjectName("LiveBadge")
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            "font-size:18px;font-weight:700;color:#64748b;"
            "padding:6px 12px;border-radius:8px;"
            "background:rgba(100,116,139,0.12);"
        )
        root.addWidget(self._badge)

        # ── Uptime ────────────────────────────────────────────────────────────
        uptime_row = QHBoxLayout()
        uptime_name = QLabel("Uptime")
        uptime_name.setObjectName("MetaText")
        self._uptime_val = QLabel("—")
        self._uptime_val.setObjectName("MetricValue")
        self._uptime_val.setStyleSheet("color:#38bdf8;font-size:15px;font-weight:700;")
        self._uptime_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        uptime_row.addWidget(uptime_name, 1)
        uptime_row.addWidget(self._uptime_val)
        root.addLayout(uptime_row)

        # ── Viewers ───────────────────────────────────────────────────────────
        viewer_row = QHBoxLayout()
        viewer_name = QLabel("👁  Viewers")
        viewer_name.setObjectName("MetaText")
        self._viewer_val = QLabel("—")
        self._viewer_val.setObjectName("MetricValue")
        self._viewer_val.setStyleSheet("color:#22c55e;font-size:15px;font-weight:700;")
        self._viewer_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        viewer_row.addWidget(viewer_name, 1)
        viewer_row.addWidget(self._viewer_val)
        root.addLayout(viewer_row)

        # ── Peak viewers ──────────────────────────────────────────────────────
        peak_row = QHBoxLayout()
        peak_name = QLabel("Peak viewers")
        peak_name.setObjectName("MetaText")
        self._peak_val = QLabel("—")
        self._peak_val.setObjectName("MetricValue")
        self._peak_val.setStyleSheet("color:#f59e0b;font-size:13px;font-weight:600;")
        self._peak_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        peak_row.addWidget(peak_name, 1)
        peak_row.addWidget(self._peak_val)
        root.addLayout(peak_row)

        root.addStretch(1)

        # ── Last-checked label ────────────────────────────────────────────────
        self._checked_lbl = QLabel("")
        self._checked_lbl.setObjectName("MetaText")
        self._checked_lbl.setAlignment(Qt.AlignRight)
        root.addWidget(self._checked_lbl)

        # ── Timers ────────────────────────────────────────────────────────────
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(_UPTIME_TICK_MS)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self._viewer_timer = QTimer(self)
        self._viewer_timer.setInterval(_VIEWER_POLL_MS)
        self._viewer_timer.timeout.connect(self._trigger_viewer_poll)

        # ── Signals ───────────────────────────────────────────────────────────
        self._viewer_data_ready.connect(self._apply_viewer_data)

        # ── Engine subscription ───────────────────────────────────────────────
        self._state_cb = self._on_stats
        engine.subscribe(self._state_cb)
        self._on_stats(engine.live)
        self.destroyed.connect(self._on_destroyed)

    # ── Engine callback ───────────────────────────────────────────────────────

    def _on_stats(self, stats: "LiveStats") -> None:
        live = stats.session_active
        if live:
            self._badge.setText("🔴  LIVE")
            self._badge.setStyleSheet(
                "font-size:18px;font-weight:700;color:#ffffff;"
                "padding:6px 12px;border-radius:8px;"
                "background:rgba(34,197,94,0.25);"
            )
            if not self._uptime_timer.isActive():
                # Start uptime from now if we don't have a Helix started_at yet
                if self._stream_started_at is None:
                    self._stream_started_at = datetime.now(timezone.utc)
                self._uptime_timer.start()
                self._trigger_viewer_poll()
                self._viewer_timer.start()
        else:
            self._badge.setText("⚫  OFFLINE")
            self._badge.setStyleSheet(
                "font-size:18px;font-weight:700;color:#64748b;"
                "padding:6px 12px;border-radius:8px;"
                "background:rgba(100,116,139,0.12);"
            )
            self._uptime_timer.stop()
            self._viewer_timer.stop()
            self._uptime_val.setText("—")
            self._viewer_val.setText("—")
            self._stream_started_at = None
            self._peak_viewers = 0
            self._peak_val.setText("—")
            self._checked_lbl.setText("")

    # ── Uptime tick ───────────────────────────────────────────────────────────

    def _tick_uptime(self) -> None:
        if self._stream_started_at is None:
            return
        delta = datetime.now(timezone.utc) - self._stream_started_at
        total = int(delta.total_seconds())
        if total < 0:
            total = 0
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h:
            self._uptime_val.setText(f"{h}h {m:02d}m {s:02d}s")
        else:
            self._uptime_val.setText(f"{m}m {s:02d}s")

    # ── Viewer count poll ─────────────────────────────────────────────────────

    def _trigger_viewer_poll(self) -> None:
        if self._fetching:
            return
        token = self._engine._repo.get("oauth_token") if self._engine._repo else ""
        client_id = self._engine._repo.get("client_id") if self._engine._repo else ""
        channel = self._engine._repo.get("channel") if self._engine._repo else ""
        if not token or not client_id or not channel:
            return
        self._fetching = True
        threading.Thread(
            target=self._fetch_stream_bg,
            args=(token, client_id, channel),
            daemon=True,
            name="live-stats-viewer-poll",
        ).start()

    def _fetch_stream_bg(self, token: str, client_id: str, channel: str) -> None:
        try:
            from stream_controller.core.ssl_helper import make_ssl_context
            ssl_ctx = make_ssl_context()
        except Exception:
            import ssl
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ssl_ctx = ssl.create_default_context()

        url = f"{_HELIX_BASE}/streams?user_login={channel}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id,
        })
        try:
            with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            streams = body.get("data", [])
            if streams:
                self._viewer_data_ready.emit(streams[0])
            else:
                self._viewer_data_ready.emit(None)
        except Exception as exc:
            logger.debug("Live stats viewer poll failed: %s", exc)
            self._viewer_data_ready.emit(None)

    def _apply_viewer_data(self, stream_data: dict | None) -> None:
        self._fetching = False
        now_str = datetime.now().strftime("%H:%M:%S")

        if stream_data is None:
            self._checked_lbl.setText(f"Updated {now_str}")
            return

        viewer_count = int(stream_data.get("viewer_count", 0))
        self._viewer_val.setText(f"{viewer_count:,}")

        if viewer_count > self._peak_viewers:
            self._peak_viewers = viewer_count
        self._peak_val.setText(f"{self._peak_viewers:,}")

        # Update stream start time from Helix (more accurate than session start)
        started_at_str = stream_data.get("started_at", "")
        if started_at_str:
            try:
                self._stream_started_at = datetime.fromisoformat(
                    started_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        self._checked_lbl.setText(f"Updated {now_str}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_destroyed(self) -> None:
        if self._engine and self._state_cb:
            self._engine.unsubscribe(self._state_cb)
        self._uptime_timer.stop()
        self._viewer_timer.stop()
