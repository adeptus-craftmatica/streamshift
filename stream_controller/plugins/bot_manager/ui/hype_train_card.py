from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_HELIX_USERS = "https://api.twitch.tv/helix/users"
_HELIX_HYPE_TRAIN = "https://api.twitch.tv/helix/hypetrain/events"
_POLL_INTERVAL_MS = 15_000


class HypeTrainCard(QWidget):
    """Stage panel: polls Helix for hype train status every 15 seconds."""

    _data_ready = Signal(object)  # emits dict | None on background thread → UI

    def __init__(self, app_context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_context = app_context
        self._fetching = False
        self._broadcaster_id: str = ""
        self._last_ended_ts: float = 0.0

        self._data_ready.connect(self._apply_data)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        # ── Header ──
        header_lbl = QLabel("🚂 Hype Train")
        header_lbl.setObjectName("CardTitle")
        header_lbl.setStyleSheet("font-size:13px; font-weight:700;")
        root.addWidget(header_lbl)

        # ── No-credentials message ──
        self._no_creds_lbl = QLabel("No Twitch connection — connect Bot Manager to enable hype train tracking")
        self._no_creds_lbl.setObjectName("CardDescription")
        self._no_creds_lbl.setAlignment(Qt.AlignCenter)
        self._no_creds_lbl.setWordWrap(True)
        self._no_creds_lbl.setStyleSheet("color:#475569; font-size:11px; padding:16px;")
        root.addWidget(self._no_creds_lbl)

        # ── Inactive view ──
        self._inactive_widget = QWidget()
        inactive_layout = QVBoxLayout(self._inactive_widget)
        inactive_layout.setContentsMargins(0, 0, 0, 0)
        inactive_layout.setSpacing(4)

        self._no_train_lbl = QLabel("No active hype train")
        self._no_train_lbl.setAlignment(Qt.AlignCenter)
        self._no_train_lbl.setStyleSheet("color:#64748b; font-size:12px; padding:8px;")
        inactive_layout.addWidget(self._no_train_lbl)

        self._last_ended_lbl = QLabel("")
        self._last_ended_lbl.setAlignment(Qt.AlignCenter)
        self._last_ended_lbl.setStyleSheet("color:#475569; font-size:10px;")
        self._last_ended_lbl.hide()
        inactive_layout.addWidget(self._last_ended_lbl)

        root.addWidget(self._inactive_widget)

        # ── Active view ──
        self._active_widget = QWidget()
        active_layout = QVBoxLayout(self._active_widget)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(10)

        # Level
        self._level_lbl = QLabel("LEVEL 1")
        self._level_lbl.setAlignment(Qt.AlignCenter)
        self._level_lbl.setStyleSheet(
            "font-size:28px; font-weight:800; color:#a78bfa; letter-spacing:2px;"
        )
        active_layout.addWidget(self._level_lbl)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%p% to next level")
        self._progress.setMinimumHeight(22)
        self._progress.setStyleSheet(
            "QProgressBar { border-radius:4px; background:#1e293b; text-align:center;"
            "  font-size:10px; color:#94a3b8; }"
            "QProgressBar::chunk { background:#7c3aed; border-radius:4px; }"
        )
        active_layout.addWidget(self._progress)

        # Time remaining
        self._time_lbl = QLabel("")
        self._time_lbl.setAlignment(Qt.AlignCenter)
        self._time_lbl.setStyleSheet("color:#f59e0b; font-size:11px; font-weight:600;")
        active_layout.addWidget(self._time_lbl)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1e293b;")
        active_layout.addWidget(sep)

        # Top contributors
        contrib_lbl = QLabel("Top Contributors")
        contrib_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#64748b;")
        active_layout.addWidget(contrib_lbl)

        self._contrib_labels: list[QLabel] = []
        for _ in range(3):
            lbl = QLabel("")
            lbl.setStyleSheet("font-size:11px; color:#94a3b8;")
            lbl.hide()
            active_layout.addWidget(lbl)
            self._contrib_labels.append(lbl)

        root.addWidget(self._active_widget)
        root.addStretch(1)

        # Initial state: hide active/inactive, show based on data
        self._active_widget.hide()
        self._inactive_widget.hide()

        # ── Poll timer ──
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._trigger_poll)
        self._timer.start()

        # Countdown timer to update "time remaining" display every second
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._expires_at: float = 0.0

        self._trigger_poll()

    # ── Credentials helper ────────────────────────────────────────────────────

    def _get_twitch_creds(self) -> tuple[str, str]:
        """Return (client_id, bearer_token) from first connected bot engine, or ('', '')."""
        try:
            pm = self._app_context.plugin_manager
            lp = pm._loaded_plugins.get("bot_manager")
            if lp is None:
                return "", ""
            bot_plugin = lp.instance
            engines = getattr(bot_plugin, "_engines", {}) or {}
            for engine in engines.values():
                cfg = getattr(engine, "_config", None)
                if cfg is None:
                    continue
                client_id = getattr(cfg, "twitch_client_id", "") or ""
                # Prefer broadcaster token for hype train (requires broadcaster scope)
                token = getattr(cfg, "twitch_broadcaster_token", "") or ""
                if not token:
                    token = getattr(cfg, "twitch_oauth_token", "") or ""
                if client_id and token:
                    bearer = token.replace("oauth:", "")
                    return client_id, bearer
        except Exception as exc:
            logger.debug("HypeTrainCard: could not get Twitch creds: %s", exc)
        return "", ""

    def _get_channel_name(self) -> str:
        try:
            pm = self._app_context.plugin_manager
            lp = pm._loaded_plugins.get("bot_manager")
            if lp is None:
                return ""
            engines = getattr(lp.instance, "_engines", {}) or {}
            for engine in engines.values():
                cfg = getattr(engine, "_config", None)
                if cfg:
                    ch = getattr(cfg, "twitch_channel", "") or ""
                    if ch:
                        return ch.lstrip("#")
        except Exception:
            pass
        return ""

    # ── Polling ───────────────────────────────────────────────────────────────

    def _trigger_poll(self) -> None:
        if self._fetching:
            return
        self._fetching = True
        threading.Thread(
            target=self._fetch_bg,
            daemon=True,
            name="hype-train-poll",
        ).start()

    def _fetch_bg(self) -> None:
        try:
            result = self._do_fetch()
        except Exception as exc:
            logger.debug("HypeTrainCard fetch error: %s", exc)
            result = None
        finally:
            self._fetching = False
        self._data_ready.emit(result)

    def _do_fetch(self) -> dict | None:
        client_id, bearer = self._get_twitch_creds()
        if not client_id or not bearer:
            return {"no_creds": True}

        headers = {
            "Authorization": f"Bearer {bearer}",
            "Client-Id": client_id,
        }

        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_ctx = ssl.create_default_context()

        # Resolve broadcaster_id if not cached
        if not self._broadcaster_id:
            channel = self._get_channel_name()
            if not channel:
                return {"no_creds": True}
            url = f"{_HELIX_USERS}?login={channel}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            users = body.get("data", [])
            if not users:
                return {"no_creds": True}
            self._broadcaster_id = users[0]["id"]

        url = f"{_HELIX_HYPE_TRAIN}?broadcaster_id={self._broadcaster_id}&first=1"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        events = body.get("data", [])
        if not events:
            return {"active": False}

        event = events[0]
        event_data = event.get("event_data", {})

        # Check if active: expires_at in the future
        expires_at_str = event_data.get("expires_at", "")
        now_utc = datetime.now(timezone.utc)
        expires_at = None
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            except Exception:
                pass

        is_active = expires_at is not None and expires_at > now_utc

        if not is_active:
            # Parse ended_at for "last ended X min ago"
            ended_at_str = event_data.get("ended_at") or event_data.get("expires_at", "")
            ended_ts = 0.0
            if ended_at_str:
                try:
                    ended_dt = datetime.fromisoformat(ended_at_str.replace("Z", "+00:00"))
                    ended_ts = ended_dt.timestamp()
                except Exception:
                    pass
            return {"active": False, "ended_ts": ended_ts}

        level = event_data.get("level", 1)
        progress = event_data.get("progress", 0)
        goal = event_data.get("goal", 1)
        pct = int((progress / goal) * 100) if goal > 0 else 0

        top_contributors = event_data.get("top_contributions", [])[:3]
        contribs = []
        for c in top_contributors:
            user = c.get("user_login") or c.get("user_name", "?")
            total = c.get("total", 0)
            ctype = c.get("type", "")
            icon = "⭐" if ctype == "SUBSCRIPTION" else "🎉"
            contribs.append(f"{icon} {user} — {total:,}")

        expires_ts = expires_at.timestamp() if expires_at else 0.0

        return {
            "active": True,
            "level": level,
            "progress_pct": pct,
            "expires_ts": expires_ts,
            "contributors": contribs,
        }

    # ── UI update (main thread via Signal) ────────────────────────────────────

    def _apply_data(self, data: dict | None) -> None:
        if data is None or data.get("no_creds"):
            self._no_creds_lbl.show()
            self._active_widget.hide()
            self._inactive_widget.hide()
            self._countdown_timer.stop()
            return

        self._no_creds_lbl.hide()

        if not data.get("active", False):
            self._active_widget.hide()
            self._inactive_widget.show()
            self._countdown_timer.stop()

            ended_ts = data.get("ended_ts", 0.0)
            if ended_ts > 0:
                minutes_ago = int((time.time() - ended_ts) / 60)
                if minutes_ago < 60:
                    self._last_ended_lbl.setText(f"Last ended: {minutes_ago} min ago")
                    self._last_ended_lbl.show()
                else:
                    self._last_ended_lbl.hide()
            else:
                self._last_ended_lbl.hide()
            return

        # Active hype train
        self._inactive_widget.hide()
        self._active_widget.show()

        level = data.get("level", 1)
        self._level_lbl.setText(f"LEVEL {level}")

        pct = min(100, max(0, data.get("progress_pct", 0)))
        self._progress.setValue(pct)

        self._expires_at = data.get("expires_ts", 0.0)
        self._tick_countdown()
        if not self._countdown_timer.isActive():
            self._countdown_timer.start()

        contributors = data.get("contributors", [])
        for i, lbl in enumerate(self._contrib_labels):
            if i < len(contributors):
                lbl.setText(contributors[i])
                lbl.show()
            else:
                lbl.hide()

    def _tick_countdown(self) -> None:
        if self._expires_at <= 0:
            self._time_lbl.setText("")
            return
        secs_left = max(0, int(self._expires_at - time.time()))
        if secs_left == 0:
            self._time_lbl.setText("Ending…")
            self._countdown_timer.stop()
        else:
            mins, secs = divmod(secs_left, 60)
            self._time_lbl.setText(f"⏱ {mins}:{secs:02d} remaining")
