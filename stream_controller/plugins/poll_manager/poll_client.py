from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Callable

from stream_controller.core.ssl_helper import make_ssl_context

logger = logging.getLogger(__name__)

_SSL_CTX = make_ssl_context()

REQUIRED_SCOPES = {"channel:manage:polls", "channel:read:polls"}


class PollClient:
    def __init__(self, on_status: Callable) -> None:
        self._on_status = on_status
        self._token: str = ""
        self._client_id: str = ""
        self._broadcaster_id: str = ""

    def connect(self, token: str, client_id: str) -> None:
        self._token = token
        self._client_id = client_id
        threading.Thread(target=self._validate, daemon=True, name="poll-validate").start()

    def disconnect(self) -> None:
        self._token = ""
        self._client_id = ""
        self._broadcaster_id = ""

    def _validate(self) -> None:
        import socket
        from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus
        try:
            req = urllib.request.Request(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {self._token}"},
            )
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(10)
            try:
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
                    data = json.loads(resp.read())
            finally:
                socket.setdefaulttimeout(old_timeout)
            scopes = set(data.get("scopes", []))
            missing = REQUIRED_SCOPES - scopes
            if missing:
                self._on_status(
                    ConnectionStatus.ERROR,
                    f"Token missing scopes: {', '.join(sorted(missing))}. Re-authorize.",
                )
                return
            self._broadcaster_id = data.get("user_id", "")
            self._on_status(ConnectionStatus.CONNECTED, "")
        except urllib.error.HTTPError as e:
            from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus
            if e.code == 401:
                self._on_status(ConnectionStatus.ERROR, "Token invalid or expired — re-authorize.")
            else:
                self._on_status(ConnectionStatus.ERROR, f"HTTP {e.code}")
        except Exception as e:
            from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus
            self._on_status(ConnectionStatus.ERROR, str(e))

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"https://api.twitch.tv/helix/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}",
            "Client-Id": self._client_id,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            return json.loads(resp.read())

    def create_poll(self, title: str, choices: list[str], duration: int) -> dict:
        return self._request("POST", "polls", {
            "broadcaster_id": self._broadcaster_id,
            "title": title,
            "choices": [{"title": c} for c in choices],
            "duration": duration,
        })

    def get_polls(self, status: str | None = None, first: int = 20) -> dict:
        params = f"broadcaster_id={self._broadcaster_id}&first={first}"
        if status:
            params += f"&status={status}"
        return self._request("GET", f"polls?{params}")

    def end_poll(self, poll_id: str, archive: bool = False) -> dict:
        return self._request("PATCH", "polls", {
            "broadcaster_id": self._broadcaster_id,
            "id": poll_id,
            "status": "ARCHIVED" if archive else "TERMINATED",
        })

    @property
    def broadcaster_id(self) -> str:
        return self._broadcaster_id

    @property
    def is_connected(self) -> bool:
        return bool(self._token and self._broadcaster_id)
