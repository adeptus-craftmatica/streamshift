from __future__ import annotations

"""
Shared Twitch implicit-grant OAuth flow for StreamShift plugins.

Usage:
    from stream_controller.core.twitch_auth import TwitchAuthFlow

    flow = TwitchAuthFlow(
        client_id="...",
        scopes="chat:read+chat:edit",
        on_complete=lambda token, username: ...,
        on_error=lambda msg: ...,
    )
    flow.start()   # opens browser, returns immediately; callbacks fire later

The token is delivered to the local callback server via an HTTP POST body
(not a GET query string) so it never appears in browser history or server logs.
"""

import logging
import socket
import threading
import urllib.parse
import webbrowser
from typing import Callable

logger = logging.getLogger(__name__)

_AUTH_PORT = 47893  # Single redirect URI registered in the Twitch dev console
_DEFAULT_SAVE_PATH = "/twitch-auth-save"

_CALLBACK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>StreamShift — Twitch Authorization</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0d0d0f; color: #f0f0ff;
          display: flex; align-items: center; justify-content: center;
          height: 100vh; margin: 0; }}
  .box {{ text-align: center; padding: 40px; max-width: 480px; }}
  h2   {{ font-size: 1.6em; margin-bottom: 12px; }}
  p    {{ color: #8090b0; font-size: 0.95em; }}
  .ok  {{ color: #22c55e; }}
  .err {{ color: #ef4444; }}
</style>
</head>
<body>
<div class="box" id="msg"><p>Completing authorization…</p></div>
<script>
  var hash = location.hash.substring(1);
  var params = {{}};
  hash.split('&').forEach(function(p) {{
    var kv = p.split('=');
    if (kv.length === 2) params[kv[0]] = decodeURIComponent(kv[1]);
  }});
  if (params.access_token) {{
    // POST so the token is in the request body, not the URL / browser history
    fetch('{save_path}', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{token: params.access_token, username: params.login || ''}})
    }})
    .then(function() {{
      document.getElementById('msg').innerHTML =
        '<h2 class="ok">✓ Authorized!</h2>' +
        '<p>You can close this tab and return to StreamShift.</p>';
    }})
    .catch(function() {{
      document.getElementById('msg').innerHTML =
        '<h2 class="err">Something went wrong.</h2><p>Please try again.</p>';
    }});
  }} else if (params.error) {{
    document.getElementById('msg').innerHTML =
      '<h2 class="err">Authorization denied.</h2>' +
      '<p>' + (params.error_description || params.error) + '</p>';
    fetch('{save_path}', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{error: params.error}})
    }});
  }} else {{
    document.getElementById('msg').innerHTML =
      '<h2 class="err">No token received.</h2><p>Please try again.</p>';
  }}
</script>
</body>
</html>"""

_SUCCESS_JSON = b'{"ok": true}'


class TwitchAuthFlow:
    """
    One-shot local HTTP server that handles the Twitch implicit OAuth redirect.
    Opens the user's browser, waits for the redirect, then calls the callback.

    Thread-safe: all network I/O runs on a daemon thread.
    """

    def __init__(
        self,
        client_id: str,
        scopes: str,
        on_complete: Callable[[str, str], None],
        on_error: Callable[[str], None],
        save_path: str = _DEFAULT_SAVE_PATH,
    ) -> None:
        self._client_id = client_id.strip()
        self._scopes = scopes
        self._on_complete = on_complete
        self._on_error = on_error
        self._save_path = save_path

    def start(self) -> None:
        if not self._client_id:
            self._on_error("Enter your Twitch Client ID before authorizing.")
            return
        threading.Thread(
            target=self._run, daemon=True, name="twitch-auth-server"
        ).start()

    def _run(self) -> None:
        # Try IPv6 first (macOS resolves localhost → ::1); fall back to IPv4.
        try:
            srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            srv.bind(("::1", _AUTH_PORT))
            srv.listen(5)
            srv.settimeout(120)
        except OSError:
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("127.0.0.1", _AUTH_PORT))
                srv.listen(5)
                srv.settimeout(120)
            except OSError as exc:
                self._on_error(f"Could not start auth server: {exc}")
                return

        redirect_uri = f"http://localhost:{_AUTH_PORT}/callback"
        auth_url = (
            "https://id.twitch.tv/oauth2/authorize"
            f"?client_id={self._client_id}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
            "&response_type=token"
            f"&scope={self._scopes}"
            "&force_verify=true"
        )
        webbrowser.open(auth_url)

        try:
            while True:
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    self._on_error("Authorization timed out.")
                    return
                with conn:
                    raw = _recv_request(conn)
                    request_line = raw.split("\r\n")[0] if raw else ""
                    method = request_line.split(" ")[0] if request_line else ""

                    if f"POST {self._save_path}" in request_line:
                        body = _extract_body(raw)
                        payload = _parse_json_body(body)
                        _send_http(conn, b"application/json", _SUCCESS_JSON)
                        if "token" in payload:
                            self._on_complete(
                                payload["token"],
                                payload.get("username", ""),
                            )
                        else:
                            self._on_error(payload.get("error", "Authorization denied"))
                        return
                    elif "/callback" in request_line:
                        html = _CALLBACK_HTML.format(save_path=self._save_path)
                        _send_http(conn, b"text/html", html.encode())
        finally:
            try:
                srv.close()
            except Exception:
                pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _recv_request(conn: socket.socket, max_bytes: int = 8192) -> str:
    conn.settimeout(5)
    data = b""
    try:
        while len(data) < max_bytes:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                # For POST, also read the body
                header_end = data.index(b"\r\n\r\n") + 4
                header_part = data[:header_end].decode("utf-8", errors="replace")
                content_length = 0
                for line in header_part.splitlines():
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                body_so_far = data[header_end:]
                while len(body_so_far) < content_length:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    body_so_far += chunk
                data = data[:header_end] + body_so_far
                break
    except socket.timeout:
        pass
    return data.decode("utf-8", errors="replace")


def _extract_body(raw: str) -> str:
    if "\r\n\r\n" in raw:
        return raw.split("\r\n\r\n", 1)[1]
    return ""


def _parse_json_body(body: str) -> dict:
    import json
    try:
        return json.loads(body)
    except Exception:
        return {}


def _send_http(conn: socket.socket, content_type: bytes, body: bytes) -> None:
    headers = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: " + content_type + b"\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n"
    )
    try:
        conn.sendall(headers + body)
    except Exception:
        pass
