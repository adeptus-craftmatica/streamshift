from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

logger = logging.getLogger(__name__)

_EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
_HELIX_BASE = "https://api.twitch.tv/helix"


class TwitchEventSubClient:
    """
    Twitch EventSub over WebSocket — subscribes to channel points, follows, subs, bits, raids.
    Requires the broadcaster's OAuth token with appropriate scopes.
    """

    def __init__(
        self,
        on_redemption: Callable[[str, str, str, int, str], None],
        on_status: Callable[[str, str], None],
        on_event: Callable[[str, str, str, dict], None] | None = None,
    ) -> None:
        self._on_redemption = on_redemption  # (username, user_id, reward_name, cost, input_text)
        self._on_status = on_status
        self._on_event = on_event  # (event_type, username, user_id, extra_dict)

        self._channel: str = ""
        self._broadcaster_token: str = ""
        self._broadcaster_id: str = ""
        self._client_id: str = ""

        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, channel: str, broadcaster_token: str, client_id: str) -> None:
        self.disconnect()
        self._channel = channel.lstrip("#").lower()
        self._broadcaster_token = broadcaster_token.strip().replace("oauth:", "")
        self._client_id = client_id.strip()
        self._broadcaster_id = ""
        if not self._channel or not self._broadcaster_token or not self._client_id:
            logger.warning("EventSub: missing channel/token/client_id — not starting")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="twitch-eventsub"
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

    # ── internal ──────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        retries = 0
        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
                if self._stop_event.is_set():
                    break
                retries = 0
                wait = 5
                self._on_status("disconnected", f"EventSub reconnecting in {wait}s…")
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)
            except Exception as exc:
                logger.error("EventSub error: %s", exc)
                retries += 1
                wait = min(60, 5 * (2 ** (retries - 1)))
                logger.info("EventSub: retrying in %ds (attempt %d)", wait, retries)
                for _ in range(wait * 10):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)

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

        logger.info("EventSub: connecting to %s", _EVENTSUB_WS_URL)
        ws = ws_lib.WebSocket(sslopt={"context": ssl_ctx})
        ws.settimeout(35)
        ws.connect(_EVENTSUB_WS_URL)

        with self._lock:
            self._ws = ws

        logger.info("EventSub: connected — waiting for session_welcome")

        while not self._stop_event.is_set():
            try:
                raw = ws.recv()
                if not raw:
                    logger.info("EventSub: server closed connection")
                    break
                msg = json.loads(raw)
                self._handle_message(msg)
            except ws_lib.WebSocketTimeoutException:
                pass  # keepalive — just loop
            except ws_lib.WebSocketConnectionClosedException as exc:
                logger.info("EventSub: connection closed: %s", exc)
                break
            except json.JSONDecodeError:
                pass
            except Exception as exc:
                logger.info("EventSub recv error: %s", exc)
                break

        with self._lock:
            if self._ws is ws:
                self._ws = None
        try:
            ws.close()
        except Exception:
            pass

    def _handle_message(self, msg: dict) -> None:
        metadata = msg.get("metadata", {})
        msg_type = metadata.get("message_type", "")
        payload = msg.get("payload", {})

        if msg_type == "session_welcome":
            session_id = payload.get("session", {}).get("id", "")
            logger.info("EventSub: session_welcome — id=%s", session_id)
            if session_id:
                threading.Thread(
                    target=self._subscribe,
                    args=(session_id,),
                    daemon=True,
                    name="eventsub-subscribe",
                ).start()

        elif msg_type == "notification":
            sub_type = payload.get("subscription", {}).get("type", "")
            event = payload.get("event", {})
            if sub_type == "channel.channel_points_custom_reward_redemption.add":
                self._on_redemption(
                    event.get("user_name", ""),
                    event.get("user_id", ""),
                    event.get("reward", {}).get("title", "Unknown Reward"),
                    event.get("reward", {}).get("cost", 0),
                    event.get("user_input", ""),
                )
            elif sub_type == "channel.follow" and self._on_event:
                self._on_event(
                    "follow",
                    event.get("user_name", ""),
                    event.get("user_id", ""),
                    {},
                )

        elif msg_type == "session_keepalive":
            pass

        elif msg_type == "session_reconnect":
            reconnect_url = payload.get("session", {}).get("reconnect_url", "")
            logger.info("EventSub: server requested reconnect to %s", reconnect_url)
            with self._lock:
                ws = self._ws
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass

        elif msg_type == "revocation":
            reason = payload.get("subscription", {}).get("status", "unknown")
            logger.warning("EventSub: subscription revoked — %s", reason)
            self._on_status("error", f"EventSub subscription revoked: {reason}. Re-authorize the broadcaster account.")
            self._stop_event.set()

    def _subscribe(self, session_id: str) -> None:
        if not self._broadcaster_id:
            self._broadcaster_id = self._fetch_broadcaster_id()
            if not self._broadcaster_id:
                self._on_status(
                    "error",
                    "EventSub: could not resolve broadcaster ID — check Client ID and Broadcaster Token.",
                )
                self._stop_event.set()
                return

        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_ctx = ssl.create_default_context()

        headers = {
            "Authorization": f"Bearer {self._broadcaster_token}",
            "Client-Id": self._client_id,
            "Content-Type": "application/json",
        }

        # Subscriptions to register. channel.follow v2 requires moderator_user_id.
        subscriptions = [
            {
                "type": "channel.channel_points_custom_reward_redemption.add",
                "version": "1",
                "condition": {"broadcaster_user_id": self._broadcaster_id},
            },
            {
                "type": "channel.follow",
                "version": "2",
                "condition": {
                    "broadcaster_user_id": self._broadcaster_id,
                    "moderator_user_id": self._broadcaster_id,
                },
            },
        ]

        any_ok = False
        for sub in subscriptions:
            if self._stop_event.is_set():
                return
            sub["transport"] = {"method": "websocket", "session_id": session_id}
            payload = json.dumps(sub).encode("utf-8")
            req = urllib.request.Request(
                f"{_HELIX_BASE}/eventsub/subscriptions",
                data=payload,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                    logger.info("EventSub: subscribed to %s (HTTP %s)", sub["type"], resp.status)
                    any_ok = True
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 409:
                    logger.info("EventSub: %s already subscribed (409) — OK", sub["type"])
                    any_ok = True
                elif exc.code == 401:
                    logger.error("EventSub: 401 for %s: %s", sub["type"], body)
                    self._on_status(
                        "error",
                        "EventSub: Broadcaster token expired or missing scope. "
                        "Re-authorize under General → Authorize Broadcaster Account.",
                    )
                    self._stop_event.set()
                    return
                elif exc.code == 403:
                    # Scope missing for this sub type — skip it but don't abort
                    logger.warning("EventSub: 403 for %s (missing scope?) — skipping: %s", sub["type"], body)
                else:
                    logger.error("EventSub: HTTP %s for %s: %s", exc.code, sub["type"], body)
            except Exception as exc:
                logger.error("EventSub: subscription request failed for %s: %s", sub["type"], exc)

        if any_ok:
            self._on_status("connected", "EventSub active (channel points + follows)")

    def _fetch_broadcaster_id(self) -> str:
        url = f"{_HELIX_BASE}/users?login={self._channel}"
        headers = {
            "Authorization": f"Bearer {self._broadcaster_token}",
            "Client-Id": self._client_id,
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            ssl_ctx = ssl.create_default_context()
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                users = data.get("data", [])
                if users:
                    uid = users[0]["id"]
                    logger.info("EventSub: broadcaster_id=%s", uid)
                    return uid
                return ""
        except Exception as exc:
            logger.error("EventSub: fetch broadcaster_id failed: %s", exc)
            return ""
