from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.chat_manager.chat_models import ChatState, ChatMessage
    from stream_controller.plugins.chat_manager.chat_state import ChatStateManager


class ChatTile(QFrame):
    """Compact control-deck tile showing connection status, last few messages, and quick send."""

    def __init__(self, chat_state: "ChatStateManager") -> None:
        super().__init__()
        self._state = chat_state
        self.setObjectName("ChatTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setObjectName("ChatStatusDot")
        self._dot.setFixedWidth(14)
        self._channel_label = QLabel("Chat")
        self._channel_label.setObjectName("CardTitle")
        header.addWidget(self._dot)
        header.addWidget(self._channel_label, 1)
        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("SecondaryButton")
        connect_btn.setFixedWidth(80)
        connect_btn.clicked.connect(self._state.connect)
        header.addWidget(connect_btn)
        root.addLayout(header)

        # Recent messages (last 5)
        self._msg_labels: list[QLabel] = []
        for _ in range(5):
            lbl = QLabel("")
            lbl.setObjectName("ChatTileMessage")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._msg_labels.append(lbl)
            root.addWidget(lbl)

        # Send row
        send_row = QHBoxLayout()
        send_row.setSpacing(6)
        self._send_input = QLineEdit()
        self._send_input.setObjectName("ChatSendInput")
        self._send_input.setPlaceholderText("Quick send…")
        self._send_input.setEnabled(False)
        self._send_input.returnPressed.connect(self._send)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("PrimaryButton")
        self._send_btn.setMinimumWidth(64)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._send)
        send_row.addWidget(self._send_input, 1)
        send_row.addWidget(self._send_btn)
        root.addLayout(send_row)

        self.destroyed.connect(self._on_destroyed)
        self._state.subscribe(self._on_updated)

    def _on_updated(self, messages: list, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus
        dot_colors = {
            ConnectionStatus.CONNECTED: "#22c55e",
            ConnectionStatus.CONNECTING: "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR: "#ef4444",
        }
        self._dot.setStyleSheet(f"color: {dot_colors.get(state.status, '#64748b')};")
        ch = state.channel or "Chat"
        self._channel_label.setText(f"#{ch}" if ch != "Chat" else "Chat")

        recent = [m for m in messages if not m.deleted][-5:]
        for i, lbl in enumerate(self._msg_labels):
            if i < len(recent):
                msg = recent[i]
                text = f"{msg.display_name}: {msg.text}"
                lbl.setText(text[:80] + ("…" if len(text) > 80 else ""))
            else:
                lbl.setText("")

        can_write = self._state.client.can_write
        self._send_input.setEnabled(can_write)
        self._send_btn.setEnabled(can_write)

    def _send(self) -> None:
        text = self._send_input.text().strip()
        if text:
            self._state.send_message(text)
            self._send_input.clear()

    def _on_destroyed(self) -> None:
        self._state.unsubscribe(self._on_updated)


class ChatDashboardCard(QFrame):
    """
    Full dashboard panel showing live chat with auto-scroll and a send box.
    Taller than the deck tile — shows up to 50 messages with colour coding.
    """

    _MAX_MESSAGES = 50

    def __init__(self, chat_state: "ChatStateManager") -> None:
        super().__init__()
        self._state = chat_state
        self.setObjectName("ChatTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setObjectName("ChatStatusDot")
        self._dot.setFixedWidth(14)
        self._channel_label = QLabel("Live Chat")
        self._channel_label.setObjectName("CardTitle")
        header.addWidget(self._dot)
        header.addWidget(self._channel_label, 1)

        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("SecondaryButton")
        connect_btn.setMinimumWidth(80)
        connect_btn.clicked.connect(self._state.connect)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setMinimumWidth(90)
        self._disconnect_btn.clicked.connect(self._state.disconnect)
        self._disconnect_btn.hide()

        header.addWidget(connect_btn)
        header.addWidget(self._disconnect_btn)
        root.addLayout(header)

        # ── message list ──────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setObjectName("ChatMessageList")
        self._list.setSpacing(2)
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setMinimumHeight(240)
        root.addWidget(self._list, 1)

        # ── send row ──────────────────────────────────────────────────────────
        send_row = QHBoxLayout()
        send_row.setSpacing(6)
        self._send_input = QLineEdit()
        self._send_input.setObjectName("ChatSendInput")
        self._send_input.setPlaceholderText("Send a message…")
        self._send_input.setEnabled(False)
        self._send_input.returnPressed.connect(self._send)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("PrimaryButton")
        self._send_btn.setMinimumWidth(64)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._send)
        send_row.addWidget(self._send_input, 1)
        send_row.addWidget(self._send_btn)
        root.addLayout(send_row)
        root.addSpacing(4)

        self.destroyed.connect(self._on_destroyed)
        self._state.subscribe(self._on_updated)

    def _on_updated(self, messages: list, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus, MsgType

        dot_colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color: {dot_colors.get(state.status, '#64748b')};")
        ch = state.channel or "Chat"
        self._channel_label.setText(f"Live Chat — #{ch}" if ch != "Chat" else "Live Chat")

        connected = state.status == ConnectionStatus.CONNECTED
        self._disconnect_btn.setVisible(connected)

        # Rebuild list
        at_bottom = (
            self._list.verticalScrollBar().value()
            >= self._list.verticalScrollBar().maximum() - 20
        )
        self._list.clear()
        visible = [m for m in messages if not m.deleted][-self._MAX_MESSAGES:]
        for msg in visible:
            if msg.is_event:
                text = f"{msg.event_icon} {msg.text}"
                color = "#a78bfa"
            elif msg.msg_type == MsgType.BITS:
                text = f"💎 {msg.display_name} cheered {msg.bits} bits! — {msg.text}" if msg.text else f"💎 {msg.display_name} cheered {msg.bits} bits!"
                color = "#fbbf24"
            elif msg.msg_type == MsgType.CHANNEL_POINTS:
                text = f"⭐ {msg.display_name} redeemed — {msg.text}"
                color = "#2dd4bf"
            else:
                text = f"{msg.display_name}: {msg.text}"
                color = msg.safe_color or "#c8cfe8"

            item = QListWidgetItem(text)
            item.setForeground(__import__('PySide6.QtGui', fromlist=['QColor']).QColor(color))
            self._list.addItem(item)

        if at_bottom:
            self._list.scrollToBottom()

        can_write = self._state.client.can_write
        self._send_input.setEnabled(can_write)
        self._send_btn.setEnabled(can_write)

    def _send(self) -> None:
        text = self._send_input.text().strip()
        if text:
            self._state.send_message(text)
            self._send_input.clear()

    def _on_destroyed(self) -> None:
        self._state.unsubscribe(self._on_updated)
