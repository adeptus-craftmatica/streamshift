from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stream_controller.plugins.bot_manager.bot_models import BotActivity, BotRunState

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 50

# Maps BotEngine activity kind + text patterns to display icons
_EVENT_ICONS = {
    "follow": "👤",
    "sub": "⭐",
    "resub": "⭐",
    "subgift": "💜",
    "bits": "🎉",
    "cheer": "🎉",
    "raid": "⚔️",
    "channel_points": "🔮",
    "command": "⌨️",
    "timed": "⏰",
    "system": "⚙️",
    "event": "📡",
}


def _icon_for_activity(activity: BotActivity) -> str:
    text_lower = activity.text.lower()
    # Check text content for event type clues first
    for key, icon in _EVENT_ICONS.items():
        if key in text_lower:
            return icon
    return _EVENT_ICONS.get(activity.kind, "📣")


class _EntryRow(QWidget):
    def __init__(self, activity: BotActivity, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        ts = datetime.fromtimestamp(activity.ts).strftime("%H:%M")
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet("font-family:monospace; font-size:10px; color:#475569;")
        ts_lbl.setFixedWidth(36)
        layout.addWidget(ts_lbl)

        icon = _icon_for_activity(activity)
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:13px;")
        icon_lbl.setFixedWidth(20)
        layout.addWidget(icon_lbl)

        text_lbl = QLabel(activity.text)
        text_lbl.setStyleSheet("font-size:11px; color:#cbd5e1;")
        text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_lbl.setTextFormat(Qt.PlainText)
        text_lbl.setWordWrap(True)
        layout.addWidget(text_lbl)


class NotificationLogCard(QWidget):
    """Stage panel: scrolling feed of stream events from bot engine activity logs."""

    def __init__(self, app_context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_context = app_context
        self._seen_ts: set[float] = set()
        self._entries: list[BotActivity] = []
        self._callbacks: dict[str, object] = {}  # bot_id → callback ref

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("🔔 Recent Events")
        title.setObjectName("CardTitle")
        title.setStyleSheet("font-size:13px; font-weight:700;")
        header.addWidget(title, 1)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._clear_log)
        header.addWidget(clear_btn)

        root.addLayout(header)

        # ── Scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "background: #0d1117; border-radius:4px;"
        )

        self._feed_widget = QWidget()
        self._feed_layout = QVBoxLayout(self._feed_widget)
        self._feed_layout.setContentsMargins(6, 6, 6, 6)
        self._feed_layout.setSpacing(2)
        self._feed_layout.addStretch()

        self._scroll.setWidget(self._feed_widget)
        root.addWidget(self._scroll, 1)

        # ── Empty state ──
        self._empty_label = QLabel("No events yet — events appear here when your stream is live")
        self._empty_label.setObjectName("CardDescription")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("color:#475569; font-size:11px; padding:16px;")
        root.addWidget(self._empty_label)

        self._update_empty_state()
        self._subscribe_engines()
        self.destroyed.connect(self._unsubscribe_all)

    # ── Engine subscription ──────────────────────────────────────────────────

    def _get_engines(self) -> dict:
        try:
            pm = self._app_context.plugin_manager
            lp = pm._loaded_plugins.get("bot_manager")
            if lp is None:
                return {}
            return getattr(lp.instance, "_engines", {}) or {}
        except Exception as exc:
            logger.debug("NotificationLogCard: could not get engines: %s", exc)
            return {}

    def _subscribe_engines(self) -> None:
        engines = self._get_engines()
        for bot_id, engine in engines.items():
            if bot_id not in self._callbacks:
                cb = self._make_callback(bot_id)
                self._callbacks[bot_id] = cb
                engine.subscribe(cb)

    def _make_callback(self, bot_id: str):
        def _cb(state: BotRunState) -> None:
            self._on_engine_update(bot_id, state)
        return _cb

    def _on_engine_update(self, bot_id: str, state: BotRunState) -> None:
        new_entries = [a for a in state.activity if a.ts not in self._seen_ts]
        if not new_entries:
            return

        for activity in new_entries:
            self._seen_ts.add(activity.ts)
            # Insert newest at top (index 0, before the stretch at the end)
            entry = _EntryRow(activity)
            self._feed_layout.insertWidget(0, entry)
            self._entries.insert(0, activity)

        # Trim to max 50
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.pop()
            # Last real widget is at index count-2 (stretch is last)
            last_idx = self._feed_layout.count() - 2
            if last_idx >= 0:
                item = self._feed_layout.takeAt(last_idx)
                if item.widget():
                    item.widget().deleteLater()

        self._update_empty_state()

        # Scroll to top to show newest
        sb = self._scroll.verticalScrollBar()
        sb.setValue(0)

    def _unsubscribe_all(self) -> None:
        engines = self._get_engines()
        for bot_id, cb in self._callbacks.items():
            engine = engines.get(bot_id)
            if engine:
                try:
                    engine.unsubscribe(cb)
                except Exception:
                    pass
        self._callbacks.clear()

    # ── Clear ──────────────────────────────────────────────────────────────

    def _clear_log(self) -> None:
        self._entries.clear()
        self._seen_ts.clear()
        # Remove all entry widgets (leave the stretch)
        while self._feed_layout.count() > 1:
            item = self._feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._update_empty_state()

    # ── Empty state ────────────────────────────────────────────────────────

    def _update_empty_state(self) -> None:
        has_entries = bool(self._entries)
        self._empty_label.setVisible(not has_entries)
        self._scroll.setVisible(has_entries)
