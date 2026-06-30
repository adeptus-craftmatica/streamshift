from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from stream_controller.plugins.chat_manager.chat_models import (
    ChatState, ChatMessage, ConnectionStatus, MsgType, MSG_TYPE_META,
)

if TYPE_CHECKING:
    from stream_controller.plugins.chat_manager.chat_state import ChatStateManager

# Event types shown in this tile (everything except plain chat)
_ALERT_TYPES = {
    MsgType.BITS,
    MsgType.CHANNEL_POINTS,
    MsgType.SUB,
    MsgType.RESUB,
    MsgType.SUBGIFT,
    MsgType.SUBMYSTERYGIFT,
    MsgType.RAID,
    MsgType.RITUAL,
    MsgType.ANNOUNCEMENT,
}

# Colour accents per event type
_TYPE_COLOR: dict[MsgType, str] = {
    MsgType.SUB:            "#a855f7",
    MsgType.RESUB:          "#8b5cf6",
    MsgType.SUBGIFT:        "#ec4899",
    MsgType.SUBMYSTERYGIFT: "#f43f5e",
    MsgType.RAID:           "#f97316",
    MsgType.BITS:           "#eab308",
    MsgType.CHANNEL_POINTS: "#22c55e",
    MsgType.RITUAL:         "#38bdf8",
    MsgType.ANNOUNCEMENT:   "#60a5fa",
}

_MAX_ROWS = 50


def _fmt_time(msg: ChatMessage) -> str:
    return msg.ts.strftime("%H:%M")


class _AlertRow(QFrame):
    def __init__(self, msg: ChatMessage) -> None:
        super().__init__()
        self.setObjectName("AlertRow")
        accent = _TYPE_COLOR.get(msg.msg_type, "#64748b")
        self.setStyleSheet(
            f"QFrame#AlertRow {{ border-left: 3px solid {accent};"
            " background: #131820; border-radius: 4px;"
            " margin-bottom: 4px; padding: 6px 10px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        meta, icon = MSG_TYPE_META.get(msg.msg_type, ("Event", "⚡"))
        header = QHBoxLayout()
        header.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color:{accent}; font-size:14px;")
        type_lbl = QLabel(meta.upper())
        type_lbl.setStyleSheet(
            f"color:{accent}; font-size:10px; font-weight:700; letter-spacing:1px;"
        )
        name_lbl = QLabel(msg.display_name or msg.username)
        name_lbl.setStyleSheet("color:#e2e8f0; font-weight:600; font-size:12px;")
        time_lbl = QLabel(_fmt_time(msg))
        time_lbl.setStyleSheet("color:#475569; font-size:10px;")
        time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header.addWidget(icon_lbl)
        header.addWidget(type_lbl)
        header.addWidget(name_lbl, 1)
        header.addWidget(time_lbl)
        root.addLayout(header)

        if msg.text:
            body = QLabel(msg.text)
            body.setWordWrap(True)
            body.setStyleSheet("color:#94a3b8; font-size:11px;")
            root.addWidget(body)


class AlertsTile(QFrame):
    """
    Stage-view panel showing live stream alerts (subs, raids, bits, etc.)
    from the shared ChatStateManager. Requires Chat Manager to be connected.
    """

    def __init__(self, chat_state: "ChatStateManager") -> None:
        super().__init__()
        self._chat_state = chat_state
        self._alerts: deque[ChatMessage] = deque(maxlen=_MAX_ROWS)
        self.setObjectName("AlertsTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("🔔  Alerts")
        title.setObjectName("CardTitle")
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color:#64748b;")
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("StageToolbarBtn")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear)
        header.addWidget(title, 1)
        header.addWidget(self._status_dot)
        header.addWidget(clear_btn)
        root.addLayout(header)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent;")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, 1)

        self._empty_lbl = QLabel("No alerts yet.")
        self._empty_lbl.setObjectName("CardDescription")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        root.addWidget(self._empty_lbl)

        self.destroyed.connect(self._on_destroyed)
        self._cb = self._on_state_update
        chat_state.subscribe(self._cb)

        # Populate from existing message buffer (events that arrived before this tile opened)
        msgs, state = chat_state.messages, chat_state.state
        self._on_state_update(msgs, state)

    # ── private ──────────────────────────────────────────────────────────────

    def _on_state_update(self, messages: list[ChatMessage], state: ChatState) -> None:
        colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._status_dot.setStyleSheet(f"color:{colors.get(state.status, '#64748b')};")

        if state.status == ConnectionStatus.CONNECTED:
            self._empty_lbl.setText("No alerts yet — waiting for subs, raids, bits…")
        elif state.status == ConnectionStatus.CONNECTING:
            self._empty_lbl.setText("Connecting to Twitch Chat…")
        else:
            self._empty_lbl.setText("Not connected — use Quick Connect or Chat Manager to connect.")

        # Find new alert messages not yet tracked
        known_ids = {m.msg_id for m in self._alerts}
        new_alerts = [
            m for m in messages
            if m.msg_type in _ALERT_TYPES and m.msg_id not in known_ids
        ]
        for msg in new_alerts:
            self._alerts.append(msg)
            self._prepend_row(msg)

        has_alerts = len(self._alerts) > 0
        self._empty_lbl.setVisible(not has_alerts)
        self._scroll.setVisible(has_alerts)

    def _prepend_row(self, msg: ChatMessage) -> None:
        row = _AlertRow(msg)
        # Insert before the stretch at position 0
        self._list_layout.insertWidget(0, row)

        # Prune excess rows from the bottom
        while self._list_layout.count() > _MAX_ROWS + 1:  # +1 for stretch
            item = self._list_layout.takeAt(self._list_layout.count() - 2)
            if item and item.widget():
                item.widget().deleteLater()

        # Scroll to top so newest alert is visible
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(0))

    def _clear(self) -> None:
        self._alerts.clear()
        while self._list_layout.count() > 1:  # keep the stretch
            item = self._list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._empty_lbl.setVisible(True)
        self._scroll.setVisible(False)

    def _on_destroyed(self) -> None:
        try:
            self._chat_state.unsubscribe(self._cb)
        except Exception:
            pass
