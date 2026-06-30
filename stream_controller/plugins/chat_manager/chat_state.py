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
    mod_error = Signal(str)  # human-readable error from Helix mod calls


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

    @property
    def mod_error(self):
        return self._signals.mod_error

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
        import threading
        threading.Thread(target=self._helix_ban, args=(username, 0, reason), daemon=True).start()

    def timeout_user(self, username: str, seconds: int = 600, reason: str = "") -> None:
        import threading
        threading.Thread(target=self._helix_ban, args=(username, seconds, reason), daemon=True).start()

    def unban_user(self, username: str) -> None:
        import threading
        threading.Thread(target=self._helix_unban, args=(username,), daemon=True).start()

    def delete_message(self, msg_id: str) -> None:
        import threading
        threading.Thread(target=self._helix_delete_message, args=(msg_id,), daemon=True).start()

    def get_banned_users(self) -> list[dict]:
        """Synchronous fetch of the banned-users list — call from a background thread."""
        import urllib.error, json as _json
        opener = self._helix_opener()
        token, client_id, broadcaster_id, _ = self._get_mod_ids(opener)
        if not (token and broadcaster_id):
            return []
        url = f"https://api.twitch.tv/helix/moderation/banned?broadcaster_id={broadcaster_id}&first=100"
        req = self._helix_req(url, token, client_id)
        try:
            with opener.open(req, timeout=10) as resp:
                return _json.loads(resp.read()).get("data", [])
        except Exception as exc:
            logger.warning("get_banned_users failed: %s", exc)
            return []

    # ── Helix helpers ─────────────────────────────────────────────────────────

    def _helix_opener(self):
        import ssl, urllib.request
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def _helix_req(self, url: str, token: str, client_id: str, method: str = "GET", body: bytes | None = None):
        import urllib.request
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Client-Id", client_id)
        if body:
            req.add_header("Content-Type", "application/json")
        return req

    def _get_mod_ids(self, opener) -> tuple[str, str, str, str]:
        """Return (token, client_id, broadcaster_id, moderator_id)."""
        token     = self._repo.get("oauth_token") or ""
        client_id = self._repo.get("client_id") or ""
        channel   = self._repo.get("channel") or ""
        if not (token and client_id and channel):
            return token, client_id, "", ""
        broadcaster_id = self._resolve_user_id(client_id, token, channel, opener)
        username = self._repo.get("username") or ""
        moderator_id = (
            self._resolve_user_id(client_id, token, username, opener)
            if username
            else self._resolve_current_user_id(client_id, token, opener)
        )
        return token, client_id, broadcaster_id, moderator_id

    def _helix_delete_message(self, msg_id: str) -> None:
        import urllib.error
        opener = self._helix_opener()
        token, client_id, broadcaster_id, moderator_id = self._get_mod_ids(opener)
        if not broadcaster_id:
            self._signals.mod_error.emit("Delete failed: could not resolve channel — check settings.")
            return
        if not moderator_id:
            self._signals.mod_error.emit("Delete failed: could not resolve your user ID — check token.")
            return
        url = (
            f"https://api.twitch.tv/helix/moderation/chat"
            f"?broadcaster_id={broadcaster_id}&moderator_id={moderator_id}&message_id={msg_id}"
        )
        try:
            with opener.open(self._helix_req(url, token, client_id, "DELETE"), timeout=10) as resp:
                if resp.status == 204:
                    self._on_delete_message(msg_id)
                    self._signals.messages_changed.emit()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            logger.warning("delete_message %s: %s", exc.code, body)
            self._signals.mod_error.emit(f"Delete failed: HTTP {exc.code} — {body[:120]}")
        except Exception as exc:
            logger.warning("delete_message failed: %s", exc)
            self._signals.mod_error.emit(f"Delete failed: {exc}")

    def _helix_ban(self, username: str, duration: int, reason: str) -> None:
        import json, urllib.error
        opener = self._helix_opener()
        token, client_id, broadcaster_id, moderator_id = self._get_mod_ids(opener)
        if not (broadcaster_id and moderator_id):
            self._signals.mod_error.emit("Ban/timeout failed: could not resolve user IDs — check settings.")
            return
        target_id = self._resolve_user_id(client_id, token, username, opener)
        if not target_id:
            self._signals.mod_error.emit(f"Ban/timeout failed: could not find user '{username}'.")
            return
        url = (
            f"https://api.twitch.tv/helix/moderation/bans"
            f"?broadcaster_id={broadcaster_id}&moderator_id={moderator_id}"
        )
        payload: dict = {"user_id": target_id}
        if duration > 0:
            payload["duration"] = duration
        if reason:
            payload["reason"] = reason
        body = json.dumps({"data": payload}).encode()
        try:
            with opener.open(self._helix_req(url, token, client_id, "POST", body), timeout=10) as resp:
                action = f"Timed out {username} for {duration}s" if duration else f"Banned {username}"
                logger.info("Helix mod: %s", action)
        except urllib.error.HTTPError as exc:
            body_txt = exc.read().decode(errors="replace")
            logger.warning("ban/timeout %s: %s", exc.code, body_txt)
            self._signals.mod_error.emit(f"Ban/timeout failed: HTTP {exc.code} — {body_txt[:120]}")
        except Exception as exc:
            logger.warning("ban/timeout failed: %s", exc)
            self._signals.mod_error.emit(f"Ban/timeout failed: {exc}")

    def _helix_unban(self, username: str) -> None:
        import urllib.error
        opener = self._helix_opener()
        token, client_id, broadcaster_id, moderator_id = self._get_mod_ids(opener)
        if not (broadcaster_id and moderator_id):
            self._signals.mod_error.emit("Unban failed: could not resolve user IDs — check settings.")
            return
        target_id = self._resolve_user_id(client_id, token, username, opener)
        if not target_id:
            self._signals.mod_error.emit(f"Unban failed: could not find user '{username}'.")
            return
        url = (
            f"https://api.twitch.tv/helix/moderation/bans"
            f"?broadcaster_id={broadcaster_id}&moderator_id={moderator_id}&user_id={target_id}"
        )
        try:
            with opener.open(self._helix_req(url, token, client_id, "DELETE"), timeout=10) as resp:
                logger.info("Helix mod: unbanned %s", username)
                self._signals.mod_error.emit(f"✓ Unbanned {username}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            logger.warning("unban %s: %s", exc.code, body)
            self._signals.mod_error.emit(f"Unban failed: HTTP {exc.code} — {body[:120]}")
        except Exception as exc:
            logger.warning("unban failed: %s", exc)
            self._signals.mod_error.emit(f"Unban failed: {exc}")

    def _resolve_current_user_id(self, client_id: str, token: str, opener=None) -> str:
        if not hasattr(self, "_user_id_cache"):
            self._user_id_cache: dict[str, str] = {}
        cache_key = "__current__"
        if cache_key in self._user_id_cache:
            return self._user_id_cache[cache_key]
        import urllib.request, json as _json
        req = urllib.request.Request("https://api.twitch.tv/helix/users")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Client-Id", client_id)
        try:
            open_fn = opener.open if opener else urllib.request.urlopen
            with open_fn(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                user = (data.get("data") or [{}])[0]
                uid = user.get("id", "")
                login = user.get("login", "")
                if uid:
                    self._user_id_cache[cache_key] = uid
                    if login:
                        self._user_id_cache[login] = uid
                        self._repo.set("username", login)
                return uid
        except Exception as exc:
            logger.warning("_resolve_current_user_id failed: %s", exc)
            return ""

    def _resolve_user_id(self, client_id: str, token: str, login: str, opener=None) -> str:
        if not hasattr(self, "_user_id_cache"):
            self._user_id_cache: dict[str, str] = {}
        login = login.lstrip("#").lower()
        if login in self._user_id_cache:
            return self._user_id_cache[login]
        import urllib.request, json as _json
        url = f"https://api.twitch.tv/helix/users?login={login}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Client-Id", client_id)
        try:
            open_fn = opener.open if opener else urllib.request.urlopen
            with open_fn(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                uid = (data.get("data") or [{}])[0].get("id", "")
                if uid:
                    self._user_id_cache[login] = uid
                return uid
        except Exception as exc:
            logger.warning("_resolve_user_id(%s) failed: %s", login, exc)
            return ""

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
