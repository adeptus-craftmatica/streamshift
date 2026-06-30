from __future__ import annotations

import json
import logging
import ssl
import threading
import urllib.request
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_HELIX_STREAMS = "https://api.twitch.tv/helix/streams"
_REFRESH_INTERVAL_MS = 60_000   # re-check stream status every 60 s
_FAST_POLL_INTERVAL_MS = 5_000  # fast poll while waiting for first connection
_FAST_POLL_DURATION_MS = 90_000 # stop fast-polling after 90 s
_STATUS_LIVE    = "live"
_STATUS_OFFLINE = "offline"
_STATUS_UNKNOWN = "unknown"


class RaidCard(QWidget):
    """Stage panel: pick a raid target from the raid list, see who's live, fire the raid."""

    _statuses_ready = Signal(object)   # emits dict[str, str] on background thread → UI

    def __init__(self, app_context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_context = app_context
        self._statuses: dict[str, str] = {}   # username → live | offline | unknown
        self._fetching = False

        self._statuses_ready.connect(self._apply_statuses)

        # ── Layout ────────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # Header row
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        header_lbl = QLabel("Raid Target")
        header_lbl.setObjectName("SettingLabel")
        header_row.addWidget(header_lbl, 1)

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.setFixedSize(32, 28)
        self._refresh_btn.setToolTip("Refresh online status")
        self._refresh_btn.clicked.connect(self._trigger_status_refresh)
        header_row.addWidget(self._refresh_btn)

        root.addLayout(header_row)

        # Dropdown
        self._combo = QComboBox()
        self._combo.setObjectName("RaidCombo")
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.setMinimumHeight(36)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        root.addWidget(self._combo)

        # Status line for the selected target
        self._status_label = QLabel("")
        self._status_label.setObjectName("RaidStatusLabel")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("RaidSep")
        root.addWidget(sep)

        # Raid button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        self._raid_btn = QPushButton("⚔  Raid")
        self._raid_btn.setObjectName("RaidButton")
        self._raid_btn.setMinimumHeight(38)
        self._raid_btn.setMinimumWidth(120)
        self._raid_btn.clicked.connect(self._on_raid_clicked)
        btn_row.addWidget(self._raid_btn)

        root.addLayout(btn_row)

        # Footer: last-checked timestamp
        self._checked_label = QLabel("")
        self._checked_label.setObjectName("MetaText")
        self._checked_label.setAlignment(Qt.AlignRight)
        root.addWidget(self._checked_label)

        root.addStretch(1)

        # ── Auto-refresh timer ────────────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._trigger_status_refresh)
        self._timer.start()

        # Fast-poll timer: polls every 5 s until we get real creds or 90 s elapse.
        # This ensures the card updates quickly after Connect All fires.
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(_FAST_POLL_INTERVAL_MS)
        self._fast_timer.timeout.connect(self._fast_poll_tick)
        self._fast_timer.start()
        QTimer.singleShot(_FAST_POLL_DURATION_MS, self._fast_timer.stop)

        # ── Initial load ──────────────────────────────────────────────────────
        self._reload_combo()
        self._trigger_status_refresh()

    # ── Combo management ──────────────────────────────────────────────────────

    def _reload_combo(self) -> None:
        from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore
        targets = RaidTargetStore.load()

        prev = self._combo.currentData()
        self._combo.blockSignals(True)
        self._combo.clear()

        if not targets:
            self._combo.addItem("— no raid targets configured —", "")
            self._combo.setEnabled(False)
            self._raid_btn.setEnabled(False)
            self._combo.blockSignals(False)
            self._status_label.setText("Add targets in Settings → Raid List.")
            return

        self._combo.setEnabled(True)
        self._raid_btn.setEnabled(True)

        for username in targets:
            label = self._item_label(username)
            self._combo.addItem(label, username)

        # Restore previous selection if still in list
        idx = self._combo.findData(prev) if prev else -1
        self._combo.setCurrentIndex(max(idx, 0))
        self._combo.blockSignals(False)
        self._on_selection_changed()

    def _item_label(self, username: str) -> str:
        status = self._statuses.get(username, _STATUS_UNKNOWN)
        if status == _STATUS_LIVE:
            return f"🟢  {username}  (Live)"
        if status == _STATUS_OFFLINE:
            return f"⚫  {username}"
        return f"◌  {username}"

    def _on_selection_changed(self) -> None:
        username = self._combo.currentData() or ""
        if not username:
            self._status_label.setText("")
            self._raid_btn.setEnabled(False)
            return

        self._raid_btn.setEnabled(True)
        status = self._statuses.get(username, _STATUS_UNKNOWN)
        if status == _STATUS_LIVE:
            self._status_label.setStyleSheet("color: #4ade80;")
            self._status_label.setText(f"🟢  {username} is live right now")
        elif status == _STATUS_OFFLINE:
            self._status_label.setStyleSheet("color: #94a3b8;")
            self._status_label.setText(f"⚫  {username} is currently offline")
        else:
            self._status_label.setStyleSheet("color: #64748b;")
            self._status_label.setText(f"◌  Status unavailable")

    # ── Status refresh ────────────────────────────────────────────────────────

    def _fast_poll_tick(self) -> None:
        """Rapid poll used right after startup to catch Bot Manager connecting."""
        client_id, _ = self._get_twitch_creds()
        if client_id:
            # Creds now available — trigger a real refresh and stop fast-polling.
            self._fast_timer.stop()
            self._trigger_status_refresh()

    def _trigger_status_refresh(self) -> None:
        if self._fetching:
            return
        from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore
        targets = RaidTargetStore.load()
        if not targets:
            return

        self._fetching = True
        self._refresh_btn.setEnabled(False)
        self._checked_label.setText("Checking…")

        threading.Thread(
            target=self._fetch_statuses_bg,
            args=(list(targets),),
            daemon=True,
            name="raid-status-check",
        ).start()

    def _fetch_statuses_bg(self, targets: list[str]) -> None:
        client_id, bearer = self._get_twitch_creds()
        if not client_id or not bearer:
            result = {t: _STATUS_UNKNOWN for t in targets}
            self._statuses_ready.emit(result)
            return

        # Helix allows up to 100 user_login params in one request
        params = "&".join(f"user_login={t}" for t in targets[:100])
        url = f"{_HELIX_STREAMS}?{params}"
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Client-Id": client_id,
        }

        try:
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ssl_ctx = ssl.create_default_context()

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            live_logins = {s["user_login"].lower() for s in body.get("data", [])}
            result = {
                t: (_STATUS_LIVE if t.lower() in live_logins else _STATUS_OFFLINE)
                for t in targets
            }
        except Exception as exc:
            logger.debug("Raid status fetch failed: %s", exc)
            result = {t: _STATUS_UNKNOWN for t in targets}

        self._statuses_ready.emit(result)

    def _apply_statuses(self, statuses: dict) -> None:
        self._statuses = statuses
        self._fetching = False
        self._refresh_btn.setEnabled(True)

        # Rebuild combo labels in-place to preserve selection
        self._combo.blockSignals(True)
        for i in range(self._combo.count()):
            username = self._combo.itemData(i)
            if username:
                self._combo.setItemText(i, self._item_label(username))
        self._combo.blockSignals(False)
        self._on_selection_changed()

        from datetime import datetime
        all_unknown = statuses and all(v == _STATUS_UNKNOWN for v in statuses.values())
        if all_unknown:
            self._checked_label.setStyleSheet("color: #f87171;")
            self._checked_label.setText("No Twitch connection — connect Bot Manager")
        else:
            self._checked_label.setStyleSheet("")
            self._checked_label.setText(f"Updated {datetime.now().strftime('%H:%M:%S')}")

    # ── Twitch credentials helper ─────────────────────────────────────────────

    def _get_twitch_creds(self) -> tuple[str, str]:
        """Return (client_id, bearer_token) from the first connected bot engine, or ('', '')."""
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
                token = getattr(cfg, "twitch_oauth_token", "") or ""
                if client_id and token:
                    # Strip "oauth:" prefix → raw bearer token
                    bearer = token.replace("oauth:", "")
                    return client_id, bearer
        except Exception as exc:
            logger.debug("Could not get Twitch creds for raid status: %s", exc)
        return "", ""

    # ── Raid execution ────────────────────────────────────────────────────────

    def _on_raid_clicked(self) -> None:
        target = self._combo.currentData() or ""
        if not target:
            return

        status = self._statuses.get(target, _STATUS_UNKNOWN)
        status_hint = ""
        if status == _STATUS_OFFLINE:
            status_hint = f"\n\n⚫ {target} appears to be offline — are you sure?"
        elif status == _STATUS_UNKNOWN:
            status_hint = f"\n\n⚪ Could not verify {target}'s live status."

        reply = QMessageBox.question(
            self,
            "Confirm Raid",
            f"Raid {target}?{status_hint}",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._execute_raid(target)

    def _execute_raid(self, target: str) -> None:
        sent = False
        try:
            pm = self._app_context.plugin_manager
            lp = pm._loaded_plugins.get("bot_manager")
            bot_plugin = lp.instance if lp else None
            if bot_plugin and hasattr(bot_plugin, "_engines"):
                for engine in (bot_plugin._engines or {}).values():
                    try:
                        engine.send_chat_message(f"/raid {target}")
                        sent = True
                    except Exception as exc:
                        logger.warning("Raid send failed for bot: %s", exc)
        except Exception as exc:
            logger.warning("Raid execution error: %s", exc)

        if sent:
            self._status_label.setStyleSheet("color: #a78bfa;")
            self._status_label.setText(f"✓ Raid sent to {target}!")
            # Re-check status after a moment
            QTimer.singleShot(3000, self._trigger_status_refresh)
        else:
            QMessageBox.warning(
                self,
                "Raid Failed",
                "No connected Twitch bots found.\n\nMake sure the Bot Manager is connected to Twitch.",
            )
