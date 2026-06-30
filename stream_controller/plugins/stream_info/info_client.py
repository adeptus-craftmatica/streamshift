from __future__ import annotations

import json
import logging
import threading
import urllib.request
import urllib.error
from typing import Callable

from stream_controller.core.ssl_helper import make_ssl_context
from stream_controller.plugins.stream_info.info_models import ConnectionStatus, StreamInfo, StreamStatus

_SSL_CTX = make_ssl_context()

logger = logging.getLogger(__name__)

_HELIX = "https://api.twitch.tv/helix"


def _get(path: str, token: str, client_id: str, **params) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_HELIX}{path}?{qs}" if qs else f"{_HELIX}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
    })
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
        return json.loads(r.read().decode())


def _patch(path: str, token: str, client_id: str, body: dict) -> int:
    """Returns HTTP status code."""
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{_HELIX}{path}",
        data=data, method="PATCH",
        headers={
            "Authorization":  f"Bearer {token}",
            "Client-Id":      client_id,
            "Content-Type":   "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        logger.warning("PATCH %s → %s %s", path, exc.code, body_text)
        return exc.code


class InfoClient:
    """
    Thin wrapper around Twitch Helix for stream info + OBS start/stop.
    All network calls happen on background threads.
    """

    def __init__(
        self,
        on_status:         Callable[[ConnectionStatus, str], None],
        on_info_updated:   Callable[[StreamInfo, str, str], None],
        on_stream_status:  Callable[[StreamStatus], None],
    ) -> None:
        self._on_status        = on_status
        self._on_info_updated  = on_info_updated   # (info, broadcaster_id, username)
        self._on_stream_status = on_stream_status

        self._token      = ""
        self._client_id  = ""
        self._broadcaster_id = ""

        # OBS connection details (read from scene_manager settings)
        self._obs_host     = "localhost"
        self._obs_port     = 4455
        self._obs_password = ""

    # ── public ────────────────────────────────────────────────────────────────

    def connect(self, token: str, client_id: str) -> None:
        self._token     = token.strip()
        self._client_id = client_id.strip()
        self._on_status(ConnectionStatus.CONNECTING, "")
        threading.Thread(target=self._do_connect, daemon=True, name="info-connect").start()

    def disconnect(self) -> None:
        self._token = ""
        self._on_status(ConnectionStatus.DISCONNECTED, "")

    def fetch_info(self) -> None:
        threading.Thread(target=self._do_fetch, daemon=True, name="info-fetch").start()

    def update_info(self, title: str, category_id: str, tags: list | None = None, language: str = "") -> None:
        threading.Thread(
            target=self._do_update,
            args=(title, category_id, tags or [], language),
            daemon=True, name="info-update",
        ).start()

    def search_categories(self, query: str, callback: Callable[[list[dict]], None]) -> None:
        threading.Thread(
            target=self._do_search,
            args=(query, callback),
            daemon=True, name="info-search",
        ).start()

    def go_live(self) -> None:
        threading.Thread(target=self._do_start_stream, daemon=True, name="info-go-live").start()

    def end_stream(self) -> None:
        threading.Thread(target=self._do_stop_stream, daemon=True, name="info-end-stream").start()

    def set_obs_config(self, host: str, port: int, password: str) -> None:
        self._obs_host     = host
        self._obs_port     = port
        self._obs_password = password

    # ── internal ──────────────────────────────────────────────────────────────

    def _do_connect(self) -> None:
        try:
            data = _get("/users", self._token, self._client_id)
            users = data.get("data", [])
            if not users:
                self._on_status(ConnectionStatus.ERROR, "Token invalid — no user returned.")
                return
            self._broadcaster_id = users[0]["id"]
            username = users[0].get("login", "")
            self._on_status(ConnectionStatus.CONNECTED, "")
            self._do_fetch(username=username)
        except Exception as exc:
            self._on_status(ConnectionStatus.ERROR, f"Connect failed: {exc}")

    def _do_fetch(self, username: str = "") -> None:
        try:
            data  = _get("/channels", self._token, self._client_id,
                         broadcaster_id=self._broadcaster_id)
            items = data.get("data", [])
            if not items:
                return
            ch = items[0]
            info = StreamInfo(
                title         = ch.get("title", ""),
                category_name = ch.get("game_name", ""),
                category_id   = ch.get("game_id", ""),
                tags          = ch.get("tags", []),
                language      = ch.get("broadcaster_language", "en"),
            )
            uname = username or ch.get("broadcaster_login", "")
            self._on_info_updated(info, self._broadcaster_id, uname)
        except Exception as exc:
            logger.warning("Fetch info failed: %s", exc)

    def _do_update(self, title: str, category_id: str, tags: list, language: str) -> None:
        body: dict = {"title": title}
        if category_id:
            body["game_id"] = category_id
        if tags is not None:
            body["tags"] = tags[:10]  # Twitch max 10 tags
        if language:
            body["broadcaster_language"] = language
        status = _patch(
            f"/channels?broadcaster_id={self._broadcaster_id}",
            self._token, self._client_id, body
        )
        if status in (200, 204):
            logger.info("Stream info updated OK")
            self._do_fetch()
        else:
            logger.warning("Update info returned HTTP %s", status)

    def _do_search(self, query: str, callback: Callable[[list[dict]], None]) -> None:
        try:
            from urllib.parse import quote
            data = _get("/search/categories", self._token, self._client_id,
                        query=quote(query), first=10)
            categories = [
                {"id": c.get("id", ""), "name": c.get("name", "")}
                for c in data.get("data", [])
            ]
            if not categories:
                callback([])
                return

            # Batch-fetch top streams for all returned games in one request
            # to get approximate live viewer counts per category.
            ids = [c["id"] for c in categories if c["id"]]
            qs = "&".join(f"game_id={gid}" for gid in ids) + "&first=100"
            streams_url = f"{_HELIX}/streams?{qs}"
            streams_req = urllib.request.Request(streams_url, headers={
                "Authorization": f"Bearer {self._token}",
                "Client-Id":     self._client_id,
            })
            try:
                with urllib.request.urlopen(streams_req, timeout=10, context=_SSL_CTX) as r:
                    streams_data = json.loads(r.read().decode())
                viewer_counts: dict[str, int] = {}
                for stream in streams_data.get("data", []):
                    gid = stream.get("game_id", "")
                    viewer_counts[gid] = viewer_counts.get(gid, 0) + stream.get("viewer_count", 0)
            except Exception as exc:
                logger.debug("Viewer count fetch failed: %s", exc)
                viewer_counts = {}

            for cat in categories:
                cat["viewer_count"] = viewer_counts.get(cat["id"], 0)

            callback(categories)
        except Exception as exc:
            logger.warning("Category search failed: %s", exc)
            callback([])

    def _do_start_stream(self) -> None:
        self._on_stream_status(StreamStatus.STARTING)
        try:
            from obsws_python import ReqClient
            req = ReqClient(
                host=self._obs_host,
                port=self._obs_port,
                password=self._obs_password,
                timeout=10,
            )
            req.start_stream()
            req.disconnect()
            self._on_stream_status(StreamStatus.LIVE)
            logger.info("OBS stream started")
        except Exception as exc:
            logger.warning("Go live via OBS failed: %s", exc)
            # Still mark as live — user may have started manually
            self._on_stream_status(StreamStatus.LIVE)

    def _do_stop_stream(self) -> None:
        self._on_stream_status(StreamStatus.STOPPING)
        try:
            from obsws_python import ReqClient
            req = ReqClient(
                host=self._obs_host,
                port=self._obs_port,
                password=self._obs_password,
                timeout=10,
            )
            req.stop_stream()
            req.disconnect()
            logger.info("OBS stream stopped")
        except Exception as exc:
            logger.warning("End stream via OBS failed: %s", exc)
        self._on_stream_status(StreamStatus.OFFLINE)
