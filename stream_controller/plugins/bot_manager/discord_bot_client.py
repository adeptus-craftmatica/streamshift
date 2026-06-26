from __future__ import annotations

import json
import logging
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

logger = logging.getLogger(__name__)

_API_BASE = "https://discord.com/api/v10"
_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Gateway opcodes
_OP_DISPATCH = 0
_OP_HEARTBEAT = 1
_OP_IDENTIFY = 2
_OP_HELLO = 10
_OP_HEARTBEAT_ACK = 11


class DiscordBotClient:
    """
    Discord bot using HTTP REST for sending messages and WebSocket gateway for receiving events.
    No discord.py dependency — uses urllib for HTTP and websocket-client for the gateway.
    """

    def __init__(
        self,
        on_message: Callable[[str, str, str], None],
        on_command: Callable[[str, str, str], None],
        on_status: Callable[[str, str], None],
    ) -> None:
        self._on_message = on_message
        self._on_command = on_command
        self._on_status = on_status

        self._bot_token: str = ""
        self._ws = None
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._heartbeat_interval: float = 41.25
        self._last_sequence: int | None = None
        self._session_id: str | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._heartbeat_ack_received = threading.Event()

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, bot_token: str) -> None:
        self.disconnect()
        self._bot_token = bot_token.strip()
        self._stop_event.clear()
        self._connected = False
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="discord-bot-client"
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

    def send_message(self, channel_id: str, text: str) -> None:
        """POST a message to a Discord channel via HTTP REST."""
        url = f"{_API_BASE}/channels/{channel_id}/messages"
        payload = json.dumps({"content": text}).encode("utf-8")
        headers = {
            "Authorization": f"Bot {self._bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "StreamShift-BotManager/1.0",
        }
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            import ssl as _ssl
            try:
                import certifi
                _ctx = _ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                _ctx = _ssl.create_default_context()
            with urllib.request.urlopen(req, context=_ctx, timeout=10) as resp:
                if resp.status not in (200, 201):
                    logger.warning("Discord send_message HTTP %s", resp.status)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error("Discord send_message HTTP error %s: %s", exc.code, body)
        except Exception as exc:
            logger.error("Discord send_message failed: %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── internal ──────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        retries = 0
        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
                if self._stop_event.is_set():
                    break
                retries += 1
                wait = min(30, 2 ** retries)
                logger.info("Discord gateway disconnected, reconnecting in %ds…", wait)
                self._on_status("disconnected", f"Reconnecting in {wait}s…")
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)
            except Exception as exc:
                logger.error("Discord client error: %s", exc)
                self._on_status("error", str(exc))
                retries += 1
                wait = min(30, 2 ** retries)
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
        ws.settimeout(60)
        ws.connect(_GATEWAY_URL)

        with self._lock:
            self._ws = ws

        self._heartbeat_ack_received.clear()

        # Use recv_data() so we can inspect the WebSocket opcode and close code.
        # ws.recv() silently returns None for close frames, hiding the error code.
        while not self._stop_event.is_set():
            try:
                opcode, data = ws.recv_data()
                from websocket import ABNF
                if opcode == ABNF.OPCODE_CLOSE:
                    close_code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 0
                    close_reason = data[2:].decode("utf-8", errors="replace") if len(data) > 2 else ""
                    logger.info("Discord: gateway closed — code %d: %s", close_code, close_reason)
                    if close_code == 4014:
                        self._on_status(
                            "error",
                            "Discord: Enable 'Message Content Intent' in the Discord Developer Portal → "
                            "your app → Bot → Privileged Gateway Intents, then toggle the bot off and back on.",
                        )
                        self._stop_event.set()
                    elif close_code == 4004:
                        self._on_status("error", "Discord: Invalid bot token. Reset it in the Developer Portal → Bot → Reset Token.")
                        self._stop_event.set()
                    elif close_code == 4013:
                        self._on_status("error", "Discord: Invalid intent value in the connect payload.")
                        self._stop_event.set()
                    elif close_code not in (1000, 1001, 4000):
                        logger.warning("Discord: unhandled close code %d: %s", close_code, close_reason)
                    break
                elif opcode == ABNF.OPCODE_TEXT:
                    raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
                    if raw:
                        self._handle_gateway_message(raw)
                # PING/PONG frames are handled automatically by recv_data(); ignore here
            except ws_lib.WebSocketTimeoutException:
                self._send_heartbeat()
            except ws_lib.WebSocketConnectionClosedException as exc:
                logger.info("Discord: connection closed: %s", exc)
                break
            except Exception as exc:
                logger.debug("Discord recv error: %s", exc)
                break

        self._connected = False
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None

        with self._lock:
            if self._ws is ws:
                self._ws = None
        try:
            ws.close()
        except Exception:
            pass

    def _handle_gateway_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        op = msg.get("op")
        data = msg.get("d")
        seq = msg.get("s")
        event = msg.get("t")

        if seq is not None:
            self._last_sequence = seq

        if op == _OP_HELLO:
            interval_ms = data.get("heartbeat_interval", 41250) if isinstance(data, dict) else 41250
            self._heartbeat_interval = interval_ms / 1000.0
            self._start_heartbeat_thread()
            self._identify()

        elif op == _OP_HEARTBEAT_ACK:
            self._heartbeat_ack_received.set()

        elif op == _OP_HEARTBEAT:
            self._send_heartbeat()

        elif op == _OP_DISPATCH:
            self._handle_dispatch(event, data)

    def _identify(self) -> None:
        payload = {
            "op": _OP_IDENTIFY,
            "d": {
                "token": self._bot_token,
                "intents": 1 << 9 | 1 << 15,  # GUILD_MESSAGES + MESSAGE_CONTENT
                "properties": {
                    "$os": "linux",
                    "$browser": "StreamShift",
                    "$device": "StreamShift",
                },
            },
        }
        self._ws_send(payload)

    def _start_heartbeat_thread(self) -> None:
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="discord-heartbeat"
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self._heartbeat_interval)
            if self._stop_event.is_set():
                break
            self._send_heartbeat()

    def _send_heartbeat(self) -> None:
        self._ws_send({"op": _OP_HEARTBEAT, "d": self._last_sequence})

    def _ws_send(self, payload: dict) -> None:
        with self._lock:
            ws = self._ws
        if ws is not None:
            try:
                ws.send(json.dumps(payload))
            except Exception as exc:
                logger.warning("Discord ws_send failed: %s", exc)

    def _handle_dispatch(self, event: str | None, data: dict | None) -> None:
        if not event or not isinstance(data, dict):
            return

        if event == "READY":
            self._session_id = data.get("session_id")
            user = data.get("user", {})
            username = user.get("username", "bot")
            self._connected = True
            self._on_status("connected", f"Connected as {username}")

        elif event == "MESSAGE_CREATE":
            channel_id = data.get("channel_id", "")
            author = data.get("author", {})
            # Skip messages from bots (including ourselves)
            if author.get("bot"):
                return
            username = author.get("username", "")
            content = data.get("content", "")
            self._on_message(channel_id, username, content)
            stripped = content.strip()
            if stripped.startswith("!"):
                parts = stripped.split(maxsplit=1)
                trigger = parts[0].lower()
                self._on_command(trigger, username, channel_id)
