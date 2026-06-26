from __future__ import annotations

import logging
from collections import deque
from typing import Callable

from PySide6.QtCore import QObject, Signal

from stream_controller.plugins.chat_manager.chat_client import TwitchChatClient
from stream_controller.plugins.chat_manager.chat_models import (
    ChatMessage,
    ChatState,
    ConnectionStatus,
)
from stream_controller.plugins.chat_manager.chat_repository import ChatRepository

logger = logging.getLogger(__name__)


class _ChatSignals(QObject):
    messages_changed = Signal()
    state_changed = Signal()


class ChatStateManager:
    """
    Owns the message buffer and connection state.
    Thread-safe: the IRC client runs on a background thread; callbacks
    are posted back to Qt's main thread via queued signals.
    """

    def __init__(self, repo: ChatRepository) -> None:
        self._repo = repo
        self._max_messages: int = int(repo.get("max_messages") or 500)
        self._messages: deque[ChatMessage] = deque(maxlen=self._max_messages)
        self._state = ChatState()
        self._signals = _ChatSignals()
        self._listeners: list[Callable[[list[ChatMessage], ChatState], None]] = []
        self._next_id = 0

        self._client = TwitchChatClient(
            on_message=self._on_message,
            on_status=self._on_status,
            on_room_state=self._on_room_state,
            on_clear_chat=self._on_clear_chat,
            on_delete_message=self._on_delete_message,
        )

        self._signals.messages_changed.connect(self._notify)
        self._signals.state_changed.connect(self._notify)

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    @property
    def state(self) -> ChatState:
        return self._state

    @property
    def client(self) -> TwitchChatClient:
        return self._client

    def subscribe(self, cb: Callable[[list[ChatMessage], ChatState], None]) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._listeners = [l for l in self._listeners if l is not cb]

    def connect(self) -> None:
        channel = self._repo.get("channel") or ""
        token = self._repo.get("oauth_token") or ""
        username = self._repo.get("username") or ""
        if not channel:
            self._state.error_message = "No channel configured."
            self._state.status = ConnectionStatus.ERROR
            self._notify()
            return
        self._state.channel = channel
        self._client.connect(channel, token=token, username=username)

    def disconnect(self) -> None:
        self._client.disconnect()
        self._state.status = ConnectionStatus.DISCONNECTED
        self._notify()

    def send_message(self, text: str) -> None:
        self._client.send_message(text)
        # Inject immediately into local buffer — Twitch echoes it back via IRC
        # but that round-trip can be slow; this gives instant UI feedback.
        username = self._repo.get("username") or self._client._username or "me"
        import uuid
        from datetime import datetime
        from stream_controller.plugins.chat_manager.chat_models import MsgType
        msg = ChatMessage(
            msg_id=f"local-{uuid.uuid4().hex[:8]}",
            ts=datetime.now(),
            username=username,
            display_name=username,
            color="",
            badges=[],
            text=text,
            channel=self._state.channel,
            msg_type=MsgType.CHAT,
        )
        self._messages.append(msg)
        self._signals.messages_changed.emit()

    def send_command(self, text: str) -> None:
        self._client.send_command(text)

    def ban_user(self, username: str, reason: str = "") -> None:
        cmd = f"/ban {username}"
        if reason:
            cmd += f" {reason}"
        self.send_command(cmd)

    def timeout_user(self, username: str, seconds: int = 600, reason: str = "") -> None:
        cmd = f"/timeout {username} {seconds}"
        if reason:
            cmd += f" {reason}"
        self.send_command(cmd)

    def delete_message(self, msg_id: str) -> None:
        self.send_command(f"/delete {msg_id}")

    def clear_chat(self) -> None:
        self.send_command("/clear")

    def set_slow_mode(self, seconds: int) -> None:
        if seconds > 0:
            self.send_command(f"/slow {seconds}")
        else:
            self.send_command("/slowoff")

    def set_sub_only(self, enabled: bool) -> None:
        self.send_command("/subscribers" if enabled else "/subscribersoff")

    def set_emote_only(self, enabled: bool) -> None:
        self.send_command("/emoteonly" if enabled else "/emoteonlyoff")

    def clear_local_messages(self) -> None:
        self._messages.clear()
        self._signals.messages_changed.emit()

    # ── client callbacks (may come from background thread) ────────────────────

    def _on_message(self, msg: ChatMessage) -> None:
        self._messages.append(msg)
        self._signals.messages_changed.emit()

    def _on_status(self, status: ConnectionStatus, error: str) -> None:
        self._state.status = status
        self._state.error_message = error
        self._signals.state_changed.emit()

    def _on_room_state(self, tags: dict) -> None:
        if "slow" in tags:
            self._state.slow_mode = int(tags["slow"] or 0)
        if "subs-only" in tags:
            self._state.sub_only = tags["subs-only"] == "1"
        if "emote-only" in tags:
            self._state.emote_only = tags["emote-only"] == "1"
        if "followers-only" in tags:
            self._state.follower_only = int(tags["followers-only"] or -1)
        self._signals.state_changed.emit()

    def _on_clear_chat(self, target_user: str | None) -> None:
        if target_user is None:
            for msg in self._messages:
                msg.deleted = True
        else:
            for msg in self._messages:
                if msg.username == target_user:
                    msg.deleted = True
        self._signals.messages_changed.emit()

    def _on_delete_message(self, msg_id: str) -> None:
        for msg in self._messages:
            if msg.msg_id == msg_id:
                msg.deleted = True
        self._signals.messages_changed.emit()

    # ── notify ────────────────────────────────────────────────────────────────

    def _notify(self) -> None:
        msgs = list(self._messages)
        state = self._state
        dead = []
        for cb in self._listeners:
            try:
                cb(msgs, state)
            except RuntimeError:
                dead.append(cb)
        for cb in dead:
            self._listeners.remove(cb)
