from __future__ import annotations

import logging
import re
import ssl
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_IRC_HOST = "irc-ws.chat.twitch.tv"
_IRC_PORT = 443

_LINE_RE = re.compile(r"^(?:@([^ ]+) )?(?::(\S+) )?(\S+)(?: (#?\S+))?(?: :(.*))?$")

_USERNOTICE_EVENT_MAP = {
    "sub": "sub",
    "resub": "resub",
    "subgift": "subgift",
    "submysterygift": "subgift",
    "raid": "raid",
}


def _parse_tags(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            result[k] = v
    return result


def _user_from_prefix(prefix: str) -> str:
    return prefix.split("!")[0] if prefix and "!" in prefix else (prefix or "")


class TwitchBotClient:
    """
    Twitch IRC bot over WebSocket (wss://).
    Authenticates with PASS + NICK + CAP REQ tags/commands/membership.
    Parses PRIVMSG for commands and bits, USERNOTICE for sub/raid events.
    Auto-reconnects with exponential backoff.
    """

    def __init__(
        self,
        on_command: Callable[[str, str, dict], None],
        on_event: Callable[[str, str, dict], None],
        on_status: Callable[[str, str], None],
        on_message_seen: Callable[[], None],
    ) -> None:
        self._on_command = on_command
        self._on_event = on_event
        self._on_status = on_status
        self._on_message_seen = on_message_seen

        self._ws = None
        self._channel: str = ""
        self._username: str = ""
        self._oauth_token: str = ""
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected = False
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, channel: str, username: str, oauth_token: str) -> None:
        self.disconnect()
        self._channel = channel.lstrip("#").lower()
        self._username = username.strip().lower()
        self._oauth_token = oauth_token.strip()
        if not self._channel or not self._username or not self._oauth_token:
            self._on_status("error", "Missing Twitch credentials — fill in Channel, Bot Username, and OAuth Token then save.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="twitch-bot-client"
        )
        self._thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        if self._thread is not None:
            self._thread.join(timeout=4.0)
            self._thread = None
        self._connected = False

    def send_chat(self, channel: str, text: str) -> None:
        with self._lock:
            ws = self._ws
        if ws is not None and self._connected:
            ch = channel.lstrip("#").lower()
            try:
                ws.send(f"PRIVMSG #{ch} :{text}\r\n")
            except Exception as exc:
                logger.warning("send_chat failed: %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── internal ──────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        retries = 0
        while not self._stop_event.is_set():
            try:
                self._on_status("connecting", "Connecting…")
                self._connect_and_listen()
                if self._stop_event.is_set():
                    break
                retries += 1
                # Start at 5s (not 2s) to avoid hammering Twitch with rapid reconnects
                wait = min(60, 5 * (2 ** (retries - 1)))
                logger.info("Twitch IRC: disconnected, reconnecting in %ds…", wait)
                self._on_status("disconnected", f"Reconnecting in {wait}s…")
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)
            except Exception as exc:
                logger.error("Bot client error: %s", exc)
                self._on_status("error", str(exc))
                retries += 1
                wait = min(60, 5 * (2 ** (retries - 1)))
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)
        self._on_status("disconnected", "")

    def _connect_and_listen(self) -> None:
        try:
            import websocket as ws_lib
        except ImportError:
            self._on_status("error", "websocket-client not installed. Run: pip install websocket-client")
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

        with self._lock:
            self._ws = ws

        tok = self._oauth_token
        if tok and not tok.startswith("oauth:"):
            tok = f"oauth:{tok}"

        logger.info("Twitch IRC: sending credentials for user=%r channel=%r", self._username, self._channel)
        ws.send(f"PASS {tok}\r\n")
        ws.send(f"NICK {self._username}\r\n")
        ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\r\n")
        ws.send(f"JOIN #{self._channel}\r\n")

        # Do NOT mark connected yet — wait for 001 (GLOBALUSERSTATE / welcome)
        # or a NOTICE auth failure before updating status.

        # Proactive keepalive: send an IRC PING every 15 seconds so the server
        # never sees us as idle and closes the connection.
        _last_ping = [time.time()]

        ws.settimeout(5)  # short timeout so we can send keepalive PINGs regularly
        buffer = ""
        while not self._stop_event.is_set():
            try:
                raw = ws.recv()
                if not raw:
                    logger.info("Twitch IRC: empty recv — server closed connection")
                    break
                logger.debug("IRC recv: %r", raw[:300])
                buffer += raw
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    self._handle_line(line)
            except ws_lib.WebSocketTimeoutException:
                # No data in last 5 seconds — send a keepalive PING if 15s have elapsed
                now = time.time()
                if now - _last_ping[0] >= 15:
                    try:
                        ws.send("PING :tmi.twitch.tv\r\n")
                        _last_ping[0] = now
                    except Exception:
                        logger.info("Twitch IRC: PING failed — disconnecting")
                        break
            except ws_lib.WebSocketConnectionClosedException as exc:
                logger.info("Twitch IRC: connection closed by server: %s", exc)
                break
            except Exception as exc:
                logger.info("Twitch IRC: recv error: %s", exc)
                break

        self._connected = False
        with self._lock:
            if self._ws is ws:
                self._ws = None
        try:
            ws.close()
        except Exception:
            pass

    def _handle_line(self, line: str) -> None:
        if not line:
            return

        if line.startswith("PING"):
            with self._lock:
                ws = self._ws
            if ws:
                try:
                    ws.send("PONG :tmi.twitch.tv\r\n")
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
            self._handle_usernotice(tags, channel)
        elif command == "NOTICE":
            self._handle_notice(body or "")
        elif command == "001":
            # 001 = welcome — auth succeeded
            logger.info("Twitch IRC: authenticated OK, joining #%s", self._channel)
            self._connected = True
            self._on_status("connected", f"Connected to #{self._channel}")
        elif command in ("002", "003", "004", "375", "372", "376", "CAP", "JOIN",
                         "353", "366", "ROOMSTATE", "USERSTATE", "GLOBALUSERSTATE"):
            pass  # ignore other server / join messages

    def _handle_privmsg(self, tags: dict, prefix: str, channel: str, text: str) -> None:
        self._on_message_seen()
        username = _user_from_prefix(prefix)

        bits_str = tags.get("bits", "")
        if bits_str and bits_str.isdigit() and int(bits_str) > 0:
            self._on_event("bits", username, dict(tags, bits=bits_str, message=text.strip()))

        stripped = text.strip()
        if stripped.startswith("!"):
            parts = stripped.split(maxsplit=1)
            trigger = parts[0].lower()
            self._on_command(trigger, username, tags)

    def _handle_notice(self, body: str) -> None:
        low = body.lower()
        if "login authentication failed" in low or "improperly formatted auth" in low:
            self._on_status("error", f"Auth failed — check your OAuth token and Bot Username. ({body})")
            self._stop_event.set()  # Don't retry — bad creds won't fix themselves
        elif "you are permanently banned" in low or "you are banned" in low:
            self._on_status("error", f"Bot account is banned from this channel. ({body})")
            self._stop_event.set()
        else:
            logger.debug("NOTICE: %s", body)

    def _handle_usernotice(self, tags: dict, channel: str) -> None:
        msg_id_tag = tags.get("msg-id", "")
        event_type = _USERNOTICE_EVENT_MAP.get(msg_id_tag)
        if event_type is None:
            return
        username = tags.get("login", tags.get("display-name", ""))
        self._on_event(event_type, username, tags)
