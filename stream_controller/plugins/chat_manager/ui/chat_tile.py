from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
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
    Full chat monitor panel — live messages, room-mode pills, right-click
    moderation actions, and an optional filter bar.
    """

    _MAX_MESSAGES = 100

    def __init__(self, chat_state: "ChatStateManager") -> None:
        super().__init__()
        self._state = chat_state
        self._filter_text = ""
        # store (msg, display_text, color) so we can map list row → ChatMessage
        self._visible_msgs: list = []

        self.setObjectName("ChatTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget()
        tabs.setObjectName("PluginTabWidget")
        root.addWidget(tabs)

        # ── Tab 1: Chat ───────────────────────────────────────────────────────
        chat_tab = QWidget()
        chat_root = QVBoxLayout(chat_tab)
        chat_root.setContentsMargins(12, 10, 12, 10)
        chat_root.setSpacing(8)
        tabs.addTab(chat_tab, "💬 Chat")

        # reassign root so the rest of __init__ builds into chat_tab
        root = chat_root

        # ── header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setObjectName("ChatStatusDot")
        self._dot.setFixedWidth(14)
        self._channel_label = QLabel("Live Chat")
        self._channel_label.setObjectName("CardTitle")
        header.addWidget(self._dot)
        header.addWidget(self._channel_label, 1)

        self._filter_btn = QPushButton("🔍")
        self._filter_btn.setObjectName("SecondaryButton")
        self._filter_btn.setFixedWidth(32)
        self._filter_btn.setToolTip("Toggle filter bar")
        self._filter_btn.clicked.connect(self._toggle_filter)

        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("SecondaryButton")
        connect_btn.setMinimumWidth(74)
        connect_btn.clicked.connect(self._state.connect)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setMinimumWidth(84)
        self._disconnect_btn.clicked.connect(self._state.disconnect)
        self._disconnect_btn.hide()

        header.addWidget(self._filter_btn)
        header.addWidget(connect_btn)
        header.addWidget(self._disconnect_btn)
        root.addLayout(header)

        # ── room-mode pills ───────────────────────────────────────────────────
        self._mode_bar = QWidget()
        mode_lay = QHBoxLayout(self._mode_bar)
        mode_lay.setContentsMargins(0, 0, 0, 0)
        mode_lay.setSpacing(4)

        self._slow_pill   = self._make_mode_pill("🐢 Slow",    self._toggle_slow)
        self._sub_pill    = self._make_mode_pill("★ Sub Only", self._toggle_sub)
        self._emote_pill  = self._make_mode_pill("😀 Emote",   self._toggle_emote)
        self._clear_btn   = QPushButton("🗑 Clear")
        self._clear_btn.setObjectName("SecondaryButton")
        self._clear_btn.clicked.connect(self._state.clear_chat)

        for w in (self._slow_pill, self._sub_pill, self._emote_pill):
            mode_lay.addWidget(w)
        mode_lay.addStretch(1)
        mode_lay.addWidget(self._clear_btn)
        root.addWidget(self._mode_bar)

        # ── filter bar (hidden by default) ────────────────────────────────────
        self._filter_bar = QWidget()
        filter_lay = QHBoxLayout(self._filter_bar)
        filter_lay.setContentsMargins(0, 0, 0, 0)
        filter_lay.setSpacing(4)
        self._filter_input = QLineEdit()
        self._filter_input.setObjectName("ChatSendInput")
        self._filter_input.setPlaceholderText("Filter by username or keyword…")
        self._filter_input.textChanged.connect(self._on_filter_changed)
        filter_clear = QPushButton("✕")
        filter_clear.setObjectName("SecondaryButton")
        filter_clear.setFixedWidth(28)
        filter_clear.clicked.connect(self._clear_filter)
        filter_lay.addWidget(self._filter_input, 1)
        filter_lay.addWidget(filter_clear)
        self._filter_bar.hide()
        root.addWidget(self._filter_bar)

        # ── pinned message banner (hidden until something is pinned) ──────────
        self._pinned_msg = None
        self._pin_banner = QFrame()
        self._pin_banner.setObjectName("PinBanner")
        self._pin_banner.setStyleSheet(
            "#PinBanner { background: rgba(124,58,237,0.12); border: 1px solid rgba(124,58,237,0.4);"
            " border-radius: 7px; }"
        )
        pin_ban_lay = QHBoxLayout(self._pin_banner)
        pin_ban_lay.setContentsMargins(10, 5, 8, 5)
        pin_ban_lay.setSpacing(6)
        pin_icon = QLabel("📌")
        pin_icon.setFixedWidth(18)
        self._pin_text = QLabel("")
        self._pin_text.setObjectName("MetaText")
        self._pin_text.setWordWrap(False)
        self._pin_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        unpin_btn = QPushButton("✕")
        unpin_btn.setObjectName("SecondaryButton")
        unpin_btn.setFixedWidth(26)
        unpin_btn.setToolTip("Unpin message")
        unpin_btn.clicked.connect(self._unpin)
        pin_ban_lay.addWidget(pin_icon)
        pin_ban_lay.addWidget(self._pin_text, 1)
        pin_ban_lay.addWidget(unpin_btn)
        self._pin_banner.hide()
        root.addWidget(self._pin_banner)

        # ── message list ──────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setObjectName("ChatMessageList")
        self._list.setSpacing(2)
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setMinimumHeight(200)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        root.addWidget(self._list, 1)

        # ── quick-action bar (operates on the selected message) ───────────────
        self._action_bar = QWidget()
        act_lay = QHBoxLayout(self._action_bar)
        act_lay.setContentsMargins(0, 2, 0, 2)
        act_lay.setSpacing(4)

        self._pin_btn = QPushButton("📌 Pin")
        self._pin_btn.setObjectName("SecondaryButton")
        self._pin_btn.setToolTip("Pin this message to the top of the panel")
        self._pin_btn.clicked.connect(self._pin_selected)

        self._del_btn = QPushButton("🗑 Delete")
        self._del_btn.setObjectName("SecondaryButton")
        self._del_btn.setToolTip("Delete this message from Twitch chat")
        self._del_btn.clicked.connect(self._delete_selected)

        self._t1_btn = QPushButton("⏱ 1 min")
        self._t1_btn.setObjectName("SecondaryButton")
        self._t1_btn.setToolTip("Timeout 1 minute")
        self._t1_btn.clicked.connect(lambda: self._timeout_selected(60))

        self._t10_btn = QPushButton("⏱ 10 min")
        self._t10_btn.setObjectName("SecondaryButton")
        self._t10_btn.setToolTip("Timeout 10 minutes")
        self._t10_btn.clicked.connect(lambda: self._timeout_selected(600))

        self._ban_btn = QPushButton("🚫 Ban")
        self._ban_btn.setObjectName("SecondaryButton")
        self._ban_btn.setToolTip("Permanently ban this user")
        self._ban_btn.clicked.connect(self._ban_selected)

        for btn in (self._pin_btn, self._del_btn, self._t1_btn, self._t10_btn, self._ban_btn):
            btn.setEnabled(False)
            act_lay.addWidget(btn)
        act_lay.addStretch(1)
        root.addWidget(self._action_bar)

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

        # ── error banner (hidden until a mod action fails) ────────────────────
        self._error_lbl = QLabel()
        self._error_lbl.setObjectName("MetaText")
        self._error_lbl.setStyleSheet("color:#ef4444;")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.hide()
        root.addWidget(self._error_lbl)

        # ── Tab 2: Banned users ───────────────────────────────────────────────
        banned_tab = QWidget()
        banned_root = QVBoxLayout(banned_tab)
        banned_root.setContentsMargins(12, 10, 12, 10)
        banned_root.setSpacing(8)
        tabs.addTab(banned_tab, "🚫 Banned")

        banned_header = QHBoxLayout()
        banned_lbl = QLabel("Banned Users")
        banned_lbl.setObjectName("CardTitle")
        self._refresh_banned_btn = QPushButton("↻ Refresh")
        self._refresh_banned_btn.setObjectName("SecondaryButton")
        self._refresh_banned_btn.clicked.connect(self._load_banned)
        banned_header.addWidget(banned_lbl, 1)
        banned_header.addWidget(self._refresh_banned_btn)
        banned_root.addLayout(banned_header)

        self._unban_input = QLineEdit()
        self._unban_input.setObjectName("ChatSendInput")
        self._unban_input.setPlaceholderText("Username to unban…")
        unban_btn = QPushButton("Unban")
        unban_btn.setObjectName("PrimaryButton")
        unban_btn.clicked.connect(self._do_unban)
        self._unban_input.returnPressed.connect(self._do_unban)
        unban_row = QHBoxLayout()
        unban_row.addWidget(self._unban_input, 1)
        unban_row.addWidget(unban_btn)
        banned_root.addLayout(unban_row)

        self._banned_list = QListWidget()
        self._banned_list.setObjectName("ChatMessageList")
        self._banned_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._banned_list.customContextMenuRequested.connect(self._show_banned_menu)
        banned_root.addWidget(self._banned_list, 1)

        self._banned_status = QLabel("Click Refresh to load banned users.")
        self._banned_status.setObjectName("MetaText")
        self._banned_status.setWordWrap(True)
        banned_root.addWidget(self._banned_status)

        tabs.currentChanged.connect(lambda i: self._load_banned() if i == 1 else None)

        self.destroyed.connect(self._on_destroyed)
        self._state.subscribe(self._on_updated)
        self._state.mod_error.connect(self._show_error)

    # ── mode pills ────────────────────────────────────────────────────────────

    def _make_mode_pill(self, label: str, slot) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setObjectName("ModePill")
        btn.clicked.connect(slot)
        return btn

    def _toggle_slow(self, checked: bool) -> None:
        self._state.set_slow_mode(30 if checked else 0)

    def _toggle_sub(self, checked: bool) -> None:
        self._state.set_sub_only(checked)

    def _toggle_emote(self, checked: bool) -> None:
        self._state.set_emote_only(checked)

    # ── filter ────────────────────────────────────────────────────────────────

    def _toggle_filter(self) -> None:
        visible = not self._filter_bar.isVisible()
        self._filter_bar.setVisible(visible)
        if visible:
            self._filter_input.setFocus()
        else:
            self._clear_filter()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.lower().strip()
        self._rebuild_list(self._state.messages, self._state.state)

    def _clear_filter(self) -> None:
        self._filter_input.clear()
        self._filter_text = ""
        self._rebuild_list(self._state.messages, self._state.state)

    # ── quick actions ─────────────────────────────────────────────────────────

    def _on_selection_changed(self, row: int) -> None:
        has_msg = 0 <= row < len(self._visible_msgs)
        msg = self._visible_msgs[row] if has_msg else None
        is_mod_target = has_msg and not getattr(msg, 'is_event', False) and not getattr(msg, 'is_broadcaster', False)

        self._pin_btn.setEnabled(has_msg and not getattr(msg, 'is_event', False))
        self._del_btn.setEnabled(has_msg and not getattr(msg, 'is_event', False))
        self._t1_btn.setEnabled(is_mod_target)
        self._t10_btn.setEnabled(is_mod_target)
        self._ban_btn.setEnabled(is_mod_target)

    def _selected_msg(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._visible_msgs):
            return self._visible_msgs[row]
        return None

    def _pin_selected(self) -> None:
        msg = self._selected_msg()
        if not msg:
            return
        self._pinned_msg = msg
        preview = f"{msg.display_name}: {msg.text}"
        if len(preview) > 90:
            preview = preview[:90] + "…"
        self._pin_text.setText(preview)
        self._pin_banner.show()

    def _unpin(self) -> None:
        self._pinned_msg = None
        self._pin_banner.hide()

    def _delete_selected(self) -> None:
        msg = self._selected_msg()
        if msg:
            self._state.delete_message(msg.msg_id)

    def _timeout_selected(self, seconds: int) -> None:
        msg = self._selected_msg()
        if msg:
            self._state.timeout_user(msg.username, seconds)

    def _ban_selected(self) -> None:
        msg = self._selected_msg()
        if msg:
            self._state.ban_user(msg.username)

    # ── context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        from stream_controller.plugins.chat_manager.chat_models import MsgType

        row = self._list.currentRow()
        if row < 0 or row >= len(self._visible_msgs):
            return

        msg = self._visible_msgs[row]
        if msg.is_event:
            return  # no mod actions on system events

        menu = QMenu(self)
        menu.setObjectName("ContextMenu")

        copy_act = QAction("Copy message", self)
        copy_act.triggered.connect(lambda: __import__('PySide6.QtWidgets', fromlist=['QApplication']).QApplication.clipboard().setText(msg.text))
        menu.addAction(copy_act)

        menu.addSeparator()
        del_act = QAction("Delete message", self)
        del_act.triggered.connect(lambda: self._state.delete_message(msg.msg_id))
        menu.addAction(del_act)

        if not msg.is_broadcaster:
            t60_act = QAction(f"Timeout {msg.display_name} — 1 min", self)
            t60_act.triggered.connect(lambda: self._state.timeout_user(msg.username, 60))
            menu.addAction(t60_act)

            t600_act = QAction(f"Timeout {msg.display_name} — 10 min", self)
            t600_act.triggered.connect(lambda: self._state.timeout_user(msg.username, 600))
            menu.addAction(t600_act)

            ban_act = QAction(f"Ban {msg.display_name}", self)
            ban_act.triggered.connect(lambda: self._state.ban_user(msg.username))
            menu.addAction(ban_act)

        menu.exec(self._list.viewport().mapToGlobal(pos))

    # ── list rebuild ──────────────────────────────────────────────────────────

    def _rebuild_list(self, messages: list, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import MsgType
        from PySide6.QtGui import QColor

        at_bottom = (
            self._list.verticalScrollBar().value()
            >= self._list.verticalScrollBar().maximum() - 20
        )

        ft = self._filter_text
        visible = [m for m in messages if not m.deleted][-self._MAX_MESSAGES:]
        if ft:
            visible = [
                m for m in visible
                if ft in m.username.lower() or ft in m.display_name.lower() or ft in m.text.lower()
            ]

        self._visible_msgs = visible
        self._list.blockSignals(True)
        self._list.clear()

        for msg in visible:
            badges = "".join(msg.badge_labels)
            prefix = f"{badges} " if badges else ""

            if msg.is_event:
                text = f"{msg.event_icon} {msg.text}"
                color = "#a78bfa"
            elif msg.msg_type == MsgType.BITS:
                text = f"{prefix}💎 {msg.display_name} cheered {msg.bits} bits!" + (f" — {msg.text}" if msg.text else "")
                color = "#fbbf24"
            elif msg.msg_type == MsgType.CHANNEL_POINTS:
                text = f"{prefix}⭐ {msg.display_name} redeemed — {msg.text}"
                color = "#2dd4bf"
            else:
                text = f"{prefix}{msg.display_name}: {msg.text}"
                color = msg.safe_color or "#c8cfe8"

            item = QListWidgetItem(text)
            item.setForeground(QColor(color))
            self._list.addItem(item)

        self._list.blockSignals(False)
        # disable action buttons when list rebuilds (selection is gone)
        self._on_selection_changed(self._list.currentRow())

        if at_bottom:
            self._list.scrollToBottom()

    # ── state updates ─────────────────────────────────────────────────────────

    def _on_updated(self, messages: list, state: "ChatState") -> None:
        from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus

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

        # Sync room-mode pills (block signals to avoid feedback loop)
        for pill, active in (
            (self._slow_pill,  state.slow_mode > 0),
            (self._sub_pill,   state.sub_only),
            (self._emote_pill, state.emote_only),
        ):
            pill.blockSignals(True)
            pill.setChecked(active)
            pill.blockSignals(False)

        self._rebuild_list(messages, state)

        can_write = self._state.client.can_write
        self._send_input.setEnabled(can_write)
        self._send_btn.setEnabled(can_write)

    def _send(self) -> None:
        text = self._send_input.text().strip()
        if text:
            self._state.send_message(text)
            self._send_input.clear()

    # ── banned tab ────────────────────────────────────────────────────────────

    def _load_banned(self) -> None:
        import threading
        self._banned_status.setText("Loading…")
        self._refresh_banned_btn.setEnabled(False)
        self._banned_list.clear()

        def _worker():
            users = self._state.get_banned_users()
            from PySide6.QtCore import QMetaObject, Q_ARG
            import json
            QMetaObject.invokeMethod(
                self, "_apply_banned",
                Qt.QueuedConnection,
                Q_ARG(str, json.dumps(users)),
            )

        threading.Thread(target=_worker, daemon=True).start()

    from PySide6.QtCore import Slot

    @Slot(str)
    def _apply_banned(self, payload: str) -> None:
        import json
        users = json.loads(payload)
        self._banned_list.clear()
        self._refresh_banned_btn.setEnabled(True)
        if not users:
            self._banned_status.setText("No banned users found.")
            return
        for u in users:
            login = u.get("user_login", "")
            name  = u.get("user_name", login)
            reason = u.get("reason", "")
            expires = u.get("expires_at", "")
            if expires:
                label = f"{name}  —  expires {expires[:10]}"
            elif reason:
                label = f"{name}  —  {reason}"
            else:
                label = name
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, login)
            self._banned_list.addItem(item)
        self._banned_status.setText(f"{len(users)} banned user(s). Right-click to unban.")

    def _show_banned_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._banned_list.itemAt(pos)
        if not item:
            return
        login = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction(f"Unban {login}", lambda: self._unban_from_list(login))
        menu.exec(self._banned_list.viewport().mapToGlobal(pos))

    def _unban_from_list(self, login: str) -> None:
        self._state.unban_user(login)
        QTimer.singleShot(1500, self._load_banned)

    def _do_unban(self) -> None:
        username = self._unban_input.text().strip().lstrip("@").lower()
        if not username:
            return
        self._unban_input.clear()
        self._state.unban_user(username)
        QTimer.singleShot(1500, self._load_banned)

    # ── error banner ──────────────────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        self._error_lbl.setText(message)
        self._error_lbl.show()
        QTimer.singleShot(8000, self._error_lbl.hide)

    def _on_destroyed(self) -> None:
        self._state.unsubscribe(self._on_updated)
