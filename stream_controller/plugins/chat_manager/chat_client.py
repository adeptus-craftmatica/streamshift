from __future__ import annotations

import logging
import random
import re
import ssl
import threading
import time
import uuid
from datetime import datetime
from typing import Callable

from stream_controller.plugins.chat_manager.chat_models import (
    ChatMessage, ConnectionStatus, MsgType, decode_system_msg
)

logger = logging.getLogger(__name__)

_IRC_HOST = "irc-ws.chat.twitch.tv"
_IRC_PORT = 443

_LINE_RE      = re.compile(r"^(?:@([^ ]+) )?(?::(\S+) )?(\S+)(?: (#?\S+))?(?: :(.*))?$")
_CLEARCHAT_RE = re.compile(r"@([^ ]+) :\S+ CLEARCHAT (#\S+)(?: :(\S+))?")
_CLEARMSG_RE  = re.compile(r"@([^ ]+) :\S+ CLEARMSG (#\S+) :(.*)")
_ROOMSTATE_RE = re.compile(r"@([^ ]+) :\S+ ROOMSTATE (#\S+)")


def _parse_tags(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            result[k] = v
    return result


def _user_from_prefix(prefix: str) -> str:
    return prefix.split("!")[0] if prefix and "!" in prefix else (prefix or "")


class TwitchChatClient:
    """
    Connects to Twitch IRC over WebSocket (wss://).
    Handles PRIVMSG, USERNOTICE (subs/gifts/raids), CLEARCHAT, CLEARMSG, ROOMSTATE.
    Runs on a background daemon thread.
    """

    def __init__(
        self,
        on_message: Callable[[ChatMessage], None],
        on_status: Callable[[ConnectionStatus, str], None],
        on_room_state: Callable[[dict], None],
        on_clear_chat: Callable[[str | None], None],
        on_delete_message: Callable[[str], None],
    ) -> None:
        self._on_message = on_message
        self._on_status = on_status
        self._on_room_state = on_room_state
        self._on_clear_chat = on_clear_chat
        self._on_delete_message = on_delete_message

        self._ws = None
        self._channel: str = ""
        self._username: str = ""
        self._token: str = ""
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected = False

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, channel: str, token: str = "", username: str = "") -> None:
        self.disconnect()
        self._channel = channel.lstrip("#").lower()
        self._token = token.strip()
        self._username = username.strip().lower() or f"justinfan{random.randint(10000, 99999)}"
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="twitch-chat-client"
        )
        self._thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._connected = False

    def send_message(self, text: str) -> None:
        if self._ws and self._connected and self._token:
            try:
                self._ws.send(f"PRIVMSG #{self._channel} :{text}\r\n")
            except Exception as exc:
                logger.warning("send_message failed: %s", exc)

    def send_command(self, command: str) -> None:
        self.send_message(command)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def can_write(self) -> bool:
        return bool(self._connected and self._token)

    # ── internal ──────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        retries = 0
        while not self._stop_event.is_set():
            try:
                self._on_status(ConnectionStatus.CONNECTING, "")
                self._connect_and_listen()
                if self._stop_event.is_set():
                    break
                retries += 1
                wait = min(30, 2 ** retries)
                logger.info("Chat disconnected, reconnecting in %ds…", wait)
                self._on_status(ConnectionStatus.CONNECTING, f"Reconnecting in {wait}s…")
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)
            except Exception as exc:
                logger.error("Chat client error: %s", exc)
                self._on_status(ConnectionStatus.ERROR, str(exc))
                time.sleep(5)
        self._on_status(ConnectionStatus.DISCONNECTED, "")

    def _connect_and_listen(self) -> None:
        try:
            import websocket as ws_lib
        except ImportError:
            self._on_status(
                ConnectionStatus.ERROR,
                "websocket-client not installed. Run: pip install websocket-client",
            )
            self._stop_event.set()
            return

        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_ctx = ssl.create_default_context()

        ws = ws_lib.WebSocket(sslopt={"context": ssl_ctx})
        ws.settimeout(30)
        ws.connect(f"wss://{_IRC_HOST}:{_IRC_PORT}")
        self._ws = ws

        if self._token:
            tok = self._token if self._token.startswith("oauth:") else f"oauth:{self._token}"
            ws.send(f"PASS {tok}\r\n")
        else:
            ws.send("PASS SCHMOOPIIE\r\n")

        ws.send(f"NICK {self._username}\r\n")
        ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\r\n")
        ws.send(f"JOIN #{self._channel}\r\n")

        self._connected = True
        self._on_status(ConnectionStatus.CONNECTED, "")

        ws.settimeout(60)
        buffer = ""
        while not self._stop_event.is_set():
            try:
                raw = ws.recv()
                if not raw:
                    break
                buffer += raw
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    self._handle_line(line)
            except ws_lib.WebSocketTimeoutException:
                ws.send("PING :tmi.twitch.tv\r\n")
            except ws_lib.WebSocketConnectionClosedException:
                break
            except Exception as exc:
                logger.debug("recv error: %s", exc)
                break

        self._connected = False
        try:
            ws.close()
        except Exception:
            pass

    def _handle_line(self, line: str) -> None:
        if not line:
            return

        if line.startswith("PING"):
            if self._ws:
                try:
                    self._ws.send("PONG :tmi.twitch.tv\r\n")
                except Exception:
                    pass
            return

        m = _LINE_RE.match(line)
        if not m:
            return

        tags_raw, prefix, command, channel, body = m.groups()
        tags = _parse_tags(tags_raw) if tags_raw else {}
        channel = (channel or "").lstrip("#")

        if command == "PRIVMSG":
            self._handle_privmsg(tags, prefix, channel, body or "")

        elif command == "USERNOTICE":
            self._handle_usernotice(tags, channel, body or "")

        elif command == "ROOMSTATE":
            self._on_room_state(tags)

        elif command == "CLEARCHAT":
            # body = username being banned/timed-out, or None for full clear
            self._on_clear_chat(body if body else None)

        elif command == "CLEARMSG":
            msg_id = tags.get("target-msg-id", "")
            if msg_id:
                self._on_delete_message(msg_id)

    def _handle_privmsg(self, tags: dict, prefix: str, channel: str, text: str) -> None:
        user_login = _user_from_prefix(prefix)
        badges_raw = tags.get("badges", "")
        badges = [b for b in badges_raw.split(",") if b]
        badge_names = [b.split("/")[0] for b in badges]

        bits = int(tags.get("bits", 0) or 0)
        reward_id = tags.get("custom-reward-id", "")

        if bits:
            msg_type = MsgType.BITS
        elif reward_id:
            msg_type = MsgType.CHANNEL_POINTS
        else:
            msg_type = MsgType.CHAT

        msg = ChatMessage(
            msg_id=tags.get("id", "") or uuid.uuid4().hex,
            ts=datetime.now(),
            username=user_login,
            display_name=tags.get("display-name", user_login),
            color=tags.get("color", ""),
            badges=badges,
            text=text,
            channel=channel,
            msg_type=msg_type,
            bits=bits,
            is_mod="moderator" in badge_names or tags.get("mod") == "1",
            is_sub="subscriber" in badge_names or tags.get("subscriber") == "1",
            is_broadcaster="broadcaster" in badge_names,
        )
        self._on_message(msg)

    def _handle_usernotice(self, tags: dict, channel: str, body: str) -> None:
        """Handle subscription, gift, raid and other USERNOTICE events."""
        msg_id_tag = tags.get("msg-id", "")
        system_raw = tags.get("system-msg", "")
        system_text = decode_system_msg(system_raw) if system_raw else ""

        user_login = tags.get("login", "")
        display_name = tags.get("display-name", user_login)
        color = tags.get("color", "")
        badges_raw = tags.get("badges", "")
        badges = [b for b in badges_raw.split(",") if b]

        type_map = {
            "sub":              MsgType.SUB,
            "resub":            MsgType.RESUB,
            "subgift":          MsgType.SUBGIFT,
            "submysterygift":   MsgType.SUBMYSTERYGIFT,
            "giftpaidupgrade":  MsgType.SUBGIFT,
            "primepaidupgrade": MsgType.SUB,
            "raid":             MsgType.RAID,
            "ritual":           MsgType.RITUAL,
            "announcement":     MsgType.ANNOUNCEMENT,
        }
        msg_type = type_map.get(msg_id_tag, MsgType.SUB)

        # For raids: show who raided + viewer count
        if msg_type == MsgType.RAID:
            raider = tags.get("msg-param-displayName", display_name)
            viewers = tags.get("msg-param-viewerCount", "?")
            system_text = system_text or f"{raider} is raiding with {viewers} viewers!"

        # The user-typed message (only for resub)
        user_text = body if body else ""

        # Display text: prefer system_text, fall back to type label
        display_text = system_text or f"{display_name} {msg_id_tag}"

        msg = ChatMessage(
            msg_id=tags.get("id", "") or uuid.uuid4().hex,
            ts=datetime.now(),
            username=user_login,
            display_name=display_name,
            color=color,
            badges=badges,
            text=display_text,
            system_text=system_text,
            channel=channel,
            msg_type=msg_type,
            is_sub=True,
        )
        self._on_message(msg)

        # If resub included a personal message, emit that too as a separate chat
        if msg_type == MsgType.RESUB and user_text:
            personal = ChatMessage(
                msg_id=uuid.uuid4().hex,
                ts=datetime.now(),
                username=user_login,
                display_name=display_name,
                color=color,
                badges=badges,
                text=user_text,
                channel=channel,
                msg_type=MsgType.CHAT,
                is_sub=True,
            )
            self._on_message(personal)
