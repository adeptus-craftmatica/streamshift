from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Callable

from stream_controller.core.ssl_helper import make_ssl_context
from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus

_SSL_CTX = make_ssl_context()

logger = logging.getLogger(__name__)

_EVENTSUB_WS  = "wss://eventsub.wss.twitch.tv/ws"
_HELIX_BASE   = "https://api.twitch.tv/helix"


def _helix(path: str, token: str, client_id: str, **params) -> dict:
    """GET a Helix endpoint, returns parsed JSON dict."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_HELIX_BASE}{path}?{qs}" if qs else f"{_HELIX_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
    })
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def _helix_post(path: str, token: str, client_id: str, body: dict) -> dict:
    """POST a Helix endpoint."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{_HELIX_BASE}{path}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        logger.warning("Helix POST %s → %s %s", path, exc.code, body_text)
        return {}


class StatsClient:
    """
    Connects to Twitch EventSub WebSocket for live events (follows, subs, bits).
    Also polls Helix for total followers every 60 s.
    Runs on background daemon threads; posts events back via callbacks.
    """

    def __init__(
        self,
        on_status:          Callable[[ConnectionStatus, str], None],
        on_follower:        Callable[[str], None],
        on_bits:            Callable[[int], None],
        on_sub:             Callable[[], None],
        on_gifted_subs:     Callable[[int], None],
        on_total_followers: Callable[[int], None],
    ) -> None:
        self._on_status          = on_status
        self._on_follower        = on_follower
        self._on_bits            = on_bits
        self._on_sub             = on_sub
        self._on_gifted_subs     = on_gifted_subs
        self._on_total_followers = on_total_followers

        self._token:          str = ""
        self._client_id:      str = ""
        self._broadcaster_id: str = ""

        self._stop = threading.Event()
        self._ws_thread:   threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def connect(self, token: str, client_id: str) -> None:
        self.disconnect()
        self._token     = token.strip()
        self._client_id = client_id.strip()
        self._stop.clear()
        self._ws_thread = threading.Thread(
            target=self._ws_loop, daemon=True, name="stats-eventsub"
        )
        self._ws_thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        if self._ws_thread:
            self._ws_thread.join(timeout=3)
            self._ws_thread = None
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
            self._poll_thread = None

    # ── EventSub WebSocket loop ───────────────────────────────────────────────

    def _ws_loop(self) -> None:
        try:
            import websocket  # websocket-client (used by obsws-python, already installed)
        except ImportError:
            self._on_status(ConnectionStatus.ERROR, "websocket-client not installed")
            return

        self._on_status(ConnectionStatus.CONNECTING, "")

        # Validate token + get broadcaster_id
        try:
            info = _helix("/users", self._token, self._client_id)
            users = info.get("data", [])
            if not users:
                self._on_status(ConnectionStatus.ERROR, "Token invalid or no user returned.")
                return
            self._broadcaster_id = users[0]["id"]
            logger.info("Stats: broadcaster_id=%s", self._broadcaster_id)
        except Exception as exc:
            self._on_status(ConnectionStatus.ERROR, f"Token validation failed: {exc}")
            return

        # Fetch followers immediately then every 60 s
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="stats-poll"
        )
        self._poll_thread.start()
        self._fetch_followers()  # immediate first fetch

        # Connect to EventSub WebSocket
        try:
            ws = websocket.WebSocket(sslopt={"context": _SSL_CTX})
            ws.connect(_EVENTSUB_WS, timeout=30)
        except Exception as exc:
            self._on_status(ConnectionStatus.ERROR, f"EventSub connect failed: {exc}")
            return

        session_id: str | None = None

        try:
            while not self._stop.is_set():
                ws.settimeout(35)
                try:
                    raw = ws.recv()
                except Exception:
                    break

                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("metadata", {}).get("message_type", "")

                if msg_type == "session_welcome":
                    session_id = msg["payload"]["session"]["id"]
                    self._subscribe_events(session_id)
                    self._on_status(ConnectionStatus.CONNECTED, "")
                    logger.info("Stats: EventSub session %s ready", session_id)

                elif msg_type == "session_keepalive":
                    pass

                elif msg_type == "notification":
                    self._handle_event(msg["payload"])

                elif msg_type == "session_reconnect":
                    # Reconnect to new URL
                    new_url = msg["payload"]["session"].get("reconnect_url", _EVENTSUB_WS)
                    ws.close()
                    try:
                        ws = websocket.WebSocket(sslopt={"context": _SSL_CTX})
                        ws.connect(new_url, timeout=30)
                    except Exception as exc:
                        self._on_status(ConnectionStatus.ERROR, f"Reconnect failed: {exc}")
                        return

                elif msg_type == "revocation":
                    self._on_status(ConnectionStatus.ERROR, "EventSub subscription revoked.")
                    break
        finally:
            try:
                ws.close()
            except Exception:
                pass
            if not self._stop.is_set():
                self._on_status(ConnectionStatus.DISCONNECTED, "")

    def _subscribe_events(self, session_id: str) -> None:
        bid = self._broadcaster_id
        transport = {"method": "websocket", "session_id": session_id}

        subscriptions = [
            ("channel.follow",            "2", {"broadcaster_user_id": bid, "moderator_user_id": bid}),
            ("channel.subscribe",         "1", {"broadcaster_user_id": bid}),
            ("channel.subscription.gift", "1", {"broadcaster_user_id": bid}),
            ("channel.cheer",             "1", {"broadcaster_user_id": bid}),
        ]

        for evt_type, version, condition in subscriptions:
            try:
                _helix_post("/eventsub/subscriptions", self._token, self._client_id, {
                    "type": evt_type,
                    "version": version,
                    "condition": condition,
                    "transport": transport,
                })
                logger.info("Stats: subscribed to %s", evt_type)
            except Exception as exc:
                logger.warning("Stats: could not subscribe to %s: %s", evt_type, exc)

    def _handle_event(self, payload: dict) -> None:
        evt_type = payload.get("subscription", {}).get("type", "")
        event    = payload.get("event", {})

        if evt_type == "channel.follow":
            username = event.get("user_name", event.get("user_login", ""))
            logger.info("Stats: follow from %s", username)
            self._on_follower(username)

        elif evt_type == "channel.subscribe":
            if not event.get("is_gift", False):
                logger.info("Stats: new sub from %s", event.get("user_name"))
                self._on_sub()

        elif evt_type == "channel.subscription.gift":
            count = int(event.get("total", 1))
            logger.info("Stats: %d gifted subs from %s", count, event.get("user_name"))
            self._on_gifted_subs(count)

        elif evt_type == "channel.cheer":
            bits = int(event.get("bits", 0))
            logger.info("Stats: %d bits from %s", bits, event.get("user_name"))
            self._on_bits(bits)

    # ── Followers poll ────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Poll total follower count every 60 seconds."""
        while not self._stop.wait(60):
            self._fetch_followers()

    def _fetch_followers(self) -> None:
        try:
            data = _helix("/channels/followers", self._token, self._client_id,
                          broadcaster_id=self._broadcaster_id, first=1)
            total = int(data.get("total", 0))
            self._on_total_followers(total)
        except Exception as exc:
            logger.warning("Stats: could not fetch follower count: %s", exc)
