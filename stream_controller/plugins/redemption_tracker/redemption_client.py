from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from stream_controller.core.ssl_helper import make_ssl_context
from stream_controller.plugins.redemption_tracker.redemption_models import QueueItem

logger = logging.getLogger(__name__)

_SSL_CTX      = make_ssl_context()
_EVENTSUB_WS  = "wss://eventsub.wss.twitch.tv/ws"
_HELIX_BASE   = "https://api.twitch.tv/helix"


def _helix_get(path: str, token: str, client_id: str, **params) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_HELIX_BASE}{path}?{qs}" if qs else f"{_HELIX_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
    })
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def _helix_post(path: str, token: str, client_id: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{_HELIX_BASE}{path}",
        data=data, method="POST",
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


def _helix_patch(path: str, token: str, client_id: str, body: dict, **params) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_HELIX_BASE}{path}?{qs}" if qs else f"{_HELIX_BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="PATCH",
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
        logger.warning("Helix PATCH %s → %s %s", path, exc.code, body_text)
        return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


class RedemptionClient:
    """
    Connects to Twitch EventSub WebSocket and subscribes to:
      - channel.channel_points_custom_reward_redemption.add
      - channel.cheer
    Fires on_item(QueueItem) for each incoming event.
    """

    def __init__(self, on_item: Callable[[QueueItem], None]) -> None:
        self._on_item        = on_item
        self._token          = ""
        self._client_id      = ""
        self._broadcaster_id = ""
        self._stop           = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def broadcaster_id(self) -> str:
        return self._broadcaster_id

    @property
    def token(self) -> str:
        return self._token

    @property
    def client_id(self) -> str:
        return self._client_id

    def connect(self, token: str, client_id: str) -> None:
        self.disconnect()
        self._token     = token.strip()
        self._client_id = client_id.strip()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._ws_loop, daemon=True, name="redemption-eventsub"
        )
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def fulfil_redemption(self, item: QueueItem) -> bool:
        """Call Twitch API to mark a redemption as FULFILLED. Returns True on success."""
        if not item.twitch_redemption_id or not item.twitch_reward_id:
            return False
        try:
            _helix_patch(
                "/channel_points/custom_rewards/redemptions",
                self._token, self._client_id,
                {"status": "FULFILLED"},
                broadcaster_id=item.broadcaster_id or self._broadcaster_id,
                reward_id=item.twitch_reward_id,
                id=item.twitch_redemption_id,
            )
            logger.info("Redemption %s fulfilled on Twitch", item.twitch_redemption_id)
            return True
        except Exception as exc:
            logger.warning("Could not fulfil redemption: %s", exc)
            return False

    def cancel_redemption(self, item: QueueItem) -> bool:
        """Call Twitch API to mark a redemption as CANCELED."""
        if not item.twitch_redemption_id or not item.twitch_reward_id:
            return False
        try:
            _helix_patch(
                "/channel_points/custom_rewards/redemptions",
                self._token, self._client_id,
                {"status": "CANCELED"},
                broadcaster_id=item.broadcaster_id or self._broadcaster_id,
                reward_id=item.twitch_reward_id,
                id=item.twitch_redemption_id,
            )
            return True
        except Exception as exc:
            logger.warning("Could not cancel redemption: %s", exc)
            return False

    # ── private ───────────────────────────────────────────────────────────────

    def _ws_loop(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.error("websocket-client not installed — redemption tracker unavailable")
            return

        try:
            info = _helix_get("/users", self._token, self._client_id)
            users = info.get("data", [])
            if not users:
                logger.error("RedemptionClient: token invalid or no user returned")
                return
            self._broadcaster_id = users[0]["id"]
        except Exception as exc:
            logger.error("RedemptionClient: token validation failed: %s", exc)
            return

        try:
            ws = websocket.WebSocket(sslopt={"context": _SSL_CTX})
            ws.connect(_EVENTSUB_WS, timeout=30)
        except Exception as exc:
            logger.error("RedemptionClient: EventSub connect failed: %s", exc)
            return

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
                    self._subscribe(session_id)

                elif msg_type == "notification":
                    self._handle(msg["payload"])

                elif msg_type == "session_reconnect":
                    new_url = msg["payload"]["session"].get("reconnect_url", _EVENTSUB_WS)
                    ws.close()
                    try:
                        ws = websocket.WebSocket(sslopt={"context": _SSL_CTX})
                        ws.connect(new_url, timeout=30)
                    except Exception as exc:
                        logger.error("RedemptionClient: reconnect failed: %s", exc)
                        return
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _subscribe(self, session_id: str) -> None:
        bid = self._broadcaster_id
        transport = {"method": "websocket", "session_id": session_id}
        subs = [
            ("channel.channel_points_custom_reward_redemption.add", "1",
             {"broadcaster_user_id": bid}),
            ("channel.cheer", "1",
             {"broadcaster_user_id": bid}),
        ]
        for evt_type, version, condition in subs:
            try:
                _helix_post("/eventsub/subscriptions", self._token, self._client_id, {
                    "type": evt_type,
                    "version": version,
                    "condition": condition,
                    "transport": transport,
                })
                logger.info("RedemptionClient: subscribed to %s", evt_type)
            except Exception as exc:
                logger.warning("RedemptionClient: could not subscribe to %s: %s", evt_type, exc)

    def _handle(self, payload: dict) -> None:
        evt_type = payload.get("subscription", {}).get("type", "")
        event    = payload.get("event", {})

        if evt_type == "channel.channel_points_custom_reward_redemption.add":
            reward  = event.get("reward", {})
            item = QueueItem.new_redemption(
                viewer_name   = event.get("user_name", event.get("user_login", "Unknown")),
                reward_name   = reward.get("title", "Unknown Reward"),
                user_input    = event.get("user_input", ""),
                cost          = int(reward.get("cost", 0)),
                redemption_id = event.get("id", ""),
                reward_id     = reward.get("id", ""),
                broadcaster_id= event.get("broadcaster_user_id", self._broadcaster_id),
                timestamp     = _now_iso(),
            )
            self._on_item(item)

        elif evt_type == "channel.cheer":
            item = QueueItem.new_bits(
                viewer_name = event.get("user_name") or event.get("user_login") or "Anonymous",
                bits        = int(event.get("bits", 0)),
                message     = event.get("message", ""),
                timestamp   = _now_iso(),
            )
            self._on_item(item)
