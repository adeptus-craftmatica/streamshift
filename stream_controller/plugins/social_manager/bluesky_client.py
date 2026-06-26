from __future__ import annotations

"""
Bluesky AT Protocol client.

Uses only the stdlib `urllib` — no extra dependencies required.
App passwords (not the real account password) are used for auth, and
credentials are stored in the system keychain via keyring_helper.
"""

import json
import logging
import mimetypes
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = "https://bsky.social/xrpc"


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context using certifi's CA bundle, falling back to the default."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _post(endpoint: str, payload: dict, token: str | None = None) -> dict:
    url = f"{_BASE}/{endpoint}"
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = {"raw": raw}
        raise BlueSkyError(f"{exc.code} {exc.reason}: {detail.get('message', raw)}") from exc


def _post_bytes(endpoint: str, data: bytes, mime: str, token: str) -> dict:
    url = f"{_BASE}/{endpoint}"
    headers = {
        "Content-Type": mime,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise BlueSkyError(f"Upload failed {exc.code}: {raw}") from exc


class BlueSkyError(Exception):
    pass


class BlueSkyClient:
    """
    Thin stateful wrapper around the Bluesky AT Protocol XRPC API.
    Call `connect()` once; thereafter `post_text()` / `post_with_image()`.
    """

    def __init__(self) -> None:
        self._did: str = ""
        self._access_jwt: str = ""
        self._handle: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._access_jwt and self._did)

    @property
    def handle(self) -> str:
        return self._handle

    @property
    def did(self) -> str:
        return self._did

    def connect(self, identifier: str, app_password: str) -> None:
        """
        Authenticate with an app password (Settings → Privacy → App Passwords).
        Raises BlueSkyError on failure.
        """
        resp = _post(
            "com.atproto.server.createSession",
            {"identifier": identifier, "password": app_password},
        )
        self._access_jwt = resp["accessJwt"]
        self._did = resp["did"]
        self._handle = resp.get("handle", identifier)
        logger.info("Bluesky: authenticated as %s (%s)", self._handle, self._did)

    def disconnect(self) -> None:
        self._access_jwt = ""
        self._did = ""
        self._handle = ""

    def _require_auth(self) -> None:
        if not self.connected:
            raise BlueSkyError("Not connected to Bluesky. Go to Accounts and connect first.")

    def post_text(self, text: str) -> dict:
        """Create a plain-text post. Returns the created record URI/CID."""
        self._require_auth()
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": _now_iso(),
        }
        return _post(
            "com.atproto.repo.createRecord",
            {"repo": self._did, "collection": "app.bsky.feed.post", "record": record},
            token=self._access_jwt,
        )

    def post_with_image(self, text: str, image_path: str, alt_text: str = "") -> dict:
        """Upload an image blob then create a post embedding it."""
        self._require_auth()
        p = Path(image_path)
        if not p.exists():
            raise BlueSkyError(f"Image not found: {image_path}")
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        allowed = {"image/png", "image/jpeg", "image/gif", "image/webp"}
        if mime not in allowed:
            raise BlueSkyError(f"Unsupported image type: {mime}")

        blob_resp = _post_bytes(
            "com.atproto.repo.uploadBlob",
            p.read_bytes(),
            mime,
            self._access_jwt,
        )
        blob_ref = blob_resp["blob"]

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": _now_iso(),
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [{"image": blob_ref, "alt": alt_text}],
            },
        }
        return _post(
            "com.atproto.repo.createRecord",
            {"repo": self._did, "collection": "app.bsky.feed.post", "record": record},
            token=self._access_jwt,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
