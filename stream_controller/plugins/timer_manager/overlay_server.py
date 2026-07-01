from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from stream_controller.constants import TIMER_OVERLAY_PORT

if TYPE_CHECKING:
    from stream_controller.plugins.timer_manager.timer_engine import TimerEngine

try:
    from flask import Flask, Response, request, send_from_directory
    _FLASK = True
except ImportError:
    _FLASK = False

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_DEFAULT_PORT = TIMER_OVERLAY_PORT


class TimerOverlayServer:
    def __init__(self, engine: "TimerEngine", port: int = _DEFAULT_PORT) -> None:
        self._engine = engine
        self._port = port
        self._thread: threading.Thread | None = None
        self._server = None
        self._theme: dict = {
            "accent":  "7c3aed",
            "bg":      "0d0d0f",
            "text":    "f0f0ff",
            "opacity": 92,
        }

    def push_theme(self, accent: str = "", bg: str = "", text: str = "", opacity: int = -1) -> None:
        if accent:  self._theme["accent"]  = accent.lstrip("#")
        if bg:      self._theme["bg"]      = bg.lstrip("#")
        if text:    self._theme["text"]    = text.lstrip("#")
        if opacity >= 0: self._theme["opacity"] = opacity

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        if not _FLASK:
            logger.warning("Flask not available — timer overlay server not started")
            return
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="timer-overlay-server"
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)
        logger.info("Timer overlay server ready on port %d", self._port)

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _run(self) -> None:
        import logging as _log
        _log.getLogger("werkzeug").setLevel(_log.ERROR)
        app = Flask(__name__, static_folder=None)
        engine = self._engine

        @app.after_request
        def _no_cache(response):
            if "text/html" in response.content_type:
                response.headers["Cache-Control"] = "no-store"
            return response

        def _timer_data(timer_id: str | None):
            timers = engine.timers
            if timer_id:
                t = engine.get(timer_id)
                if t:
                    return t.to_dict()
            # default: first running, else first
            running = [t for t in timers if t.status.value == "running"]
            target = running[0] if running else (timers[0] if timers else None)
            return target.to_dict() if target else {"id":"","label":"","status":"idle","display":"00:00","progress":0,"color":"7c3aed","mode":"countdown","end_message":"","remaining":0,"elapsed":0}

        @app.route("/api/theme")
        def api_theme():
            resp = Response(json.dumps(self._theme), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/api/state")
        def api_state():
            tid = request.args.get("id")
            data = _timer_data(tid)
            data["_theme"] = self._theme
            resp = Response(json.dumps(data), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/api/timers")
        def api_timers():
            data = [t.to_dict() for t in engine.timers]
            resp = Response(json.dumps(data), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/card")
        def overlay_card():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_card.html")

        @app.route("/minimal")
        def overlay_minimal():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_minimal.html")

        @app.route("/circle")
        def overlay_circle():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_circle.html")

        @app.route("/fullscreen")
        def overlay_fullscreen():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_fullscreen.html")

        @app.route("/corner")
        def overlay_corner():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_corner.html")

        @app.route("/split")
        def overlay_split():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_split.html")

        @app.route("/neon")
        def overlay_neon():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_neon.html")

        @app.route("/orbit")
        def overlay_orbit():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_orbit.html")

        @app.route("/surge")
        def overlay_surge():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_surge.html")

        @app.route("/")
        def index():
            return send_from_directory(str(_OVERLAYS_DIR), "timer_card.html")

        @app.route("/static/<path:filename>")
        def static_files(filename):
            return send_from_directory(str(_OVERLAYS_DIR / "static"), filename)

        try:
            import werkzeug.serving
            server = werkzeug.serving.make_server("localhost", self._port, app, threaded=True)
            self._server = server
            self._ready.set()
            server.serve_forever()
        except OSError as exc:
            self._ready.set()
            logger.error("Timer overlay server failed to bind port %d: %s", self._port, exc)
        except Exception as exc:
            logger.error("Timer overlay server error: %s", exc)
