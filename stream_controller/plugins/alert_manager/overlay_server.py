from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

try:
    from flask import Flask, Response, jsonify, send_from_directory
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_STYLES_DIR = _OVERLAYS_DIR / "styles"
_DEFAULT_PORT = 47898

_ALL_TYPES = ["follower", "subscriber", "gift_sub", "bits", "raid", "donation"]


class AlertOverlayServer:
    """Flask server that serves per-type alert overlays and delivers alert events
    to browsers via type-specific long-poll endpoints."""

    def __init__(
        self,
        port: int = _DEFAULT_PORT,
        get_style: Callable[[str], str] | None = None,
    ) -> None:
        self._port = port
        self._get_style = get_style or (lambda t: "card")
        self._pending: dict[str, dict | None] = {t: None for t in _ALL_TYPES}
        self._events: dict[str, threading.Event] = {t: threading.Event() for t in _ALL_TYPES}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._server = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self._port}"

    def overlay_url(self, alert_type: str) -> str:
        return f"{self.base_url}/overlay/{alert_type}"

    def push_alert(self, alert_type: str, data: dict) -> None:
        """Called by the queue processor to deliver a typed alert to polling browsers."""
        if alert_type not in self._pending:
            logger.warning("push_alert: unknown alert type %r", alert_type)
            return
        with self._lock:
            self._pending[alert_type] = data
        self._events[alert_type].set()

    def push_style_change(self, alert_type: str) -> None:
        """Tell the browser to reload and pick up the new style immediately."""
        if alert_type not in self._pending:
            return
        with self._lock:
            self._pending[alert_type] = {"type": "style_change"}
        self._events[alert_type].set()

    def start(self) -> None:
        if not _FLASK_AVAILABLE:
            logger.warning("Flask not available — alert overlay server not started")
            return
        t = threading.Thread(target=self._run, daemon=True, name="alert-overlay-server")
        t.start()
        self._ready.wait(timeout=5.0)
        logger.info("Alert overlay server ready on port %d", self._port)

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _run(self) -> None:
        import logging as _log
        _log.getLogger("werkzeug").setLevel(_log.ERROR)

        app = Flask(__name__, static_folder=None)
        server_ref = self

        @app.route("/api/config/<alert_type>")
        def api_config(alert_type: str) -> Response:
            style = server_ref._get_style(alert_type)
            resp = Response(
                json.dumps({"style": style}),
                mimetype="application/json",
            )
            resp.headers["Cache-Control"] = "no-cache"
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp

        @app.route("/overlay/<alert_type>")
        def overlay(alert_type: str) -> Response:
            style = server_ref._get_style(alert_type)
            html_path = _STYLES_DIR / f"{style}.html"
            if not html_path.exists():
                html_path = _STYLES_DIR / "card.html"
                style = "card"
            if not html_path.exists():
                return Response("<p>Style not found.</p>", mimetype="text/html", status=404)
            html = (
                html_path.read_text(encoding="utf-8")
                .replace("__ALERT_TYPE__", alert_type)
                .replace("__ALERT_STYLE__", style)
            )
            return Response(html, mimetype="text/html")

        @app.route("/poll/<alert_type>")
        def poll(alert_type: str) -> Response:
            if alert_type not in server_ref._events:
                r = jsonify({"type": "ping"})
                r.headers["Cache-Control"] = "no-cache"
                return r
            triggered = server_ref._events[alert_type].wait(timeout=25.0)
            if not triggered:
                r = jsonify({"type": "ping"})
                r.headers["Cache-Control"] = "no-cache"
                return r
            with server_ref._lock:
                data = server_ref._pending.get(alert_type)
                server_ref._pending[alert_type] = None
            server_ref._events[alert_type].clear()
            r = jsonify(data or {"type": "ping"})
            r.headers["Cache-Control"] = "no-cache"
            return r

        @app.route("/styles/<path:filename>")
        def styles(filename: str) -> Response:
            return send_from_directory(str(_STYLES_DIR), filename)

        try:
            import werkzeug.serving
            server = werkzeug.serving.make_server("localhost", self._port, app, threaded=True)
            self._server = server
            self._ready.set()
            server.serve_forever()
        except OSError as exc:
            self._ready.set()
            logger.error("Alert overlay server failed on port %d: %s", self._port, exc)
        except Exception as exc:
            self._ready.set()
            logger.error("Alert overlay server error: %s", exc)
