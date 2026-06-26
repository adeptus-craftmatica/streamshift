from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stream_controller.plugins.music_manager.music_state import MusicState

try:
    from flask import Flask, Response, send_from_directory
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False
    logger.warning("flask not installed — overlays unavailable. Run: pip install flask")

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_DEFAULT_PORT = 47891


class OverlayServer:
    """Tiny Flask server that serves Now Playing HTML overlays and a JSON state endpoint."""

    def __init__(self, music_state: "MusicState", port: int = _DEFAULT_PORT) -> None:
        self._music_state = music_state
        self._port = port
        self._thread: threading.Thread | None = None
        self._server = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        if not _FLASK_AVAILABLE:
            logger.warning("Flask not available — overlay server not started")
            return
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="music-overlay-server")
        self._thread.start()
        self._ready.wait(timeout=5.0)
        logger.info("Overlay server ready on port %d", self._port)

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _run(self) -> None:
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

        app = Flask(__name__, static_folder=None)

        music_state = self._music_state

        @app.after_request
        def _no_cache(response):
            if "text/html" in response.content_type:
                response.headers["Cache-Control"] = "no-store"
            return response

        @app.route("/api/state")
        def api_state():
            state = music_state.state
            track = state.current_track
            data = {
                "status": state.status.value,
                "title": track.display_title if track else "",
                "artist": track.display_artist if track else "",
                "album": track.album if track else "",
                "duration": track.duration if track else 0,
                "position": state.position,
                "volume": state.volume,
                "muted": state.muted,
                "shuffle": state.shuffle,
                "loop_mode": state.loop_mode.value,
                "queue_index": state.queue_index,
                "queue_total": len(state.queue),
            }
            resp = Response(json.dumps(data), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/")
        def index():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_card.html")

        @app.route("/card")
        def card():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_card.html")

        @app.route("/minimal")
        def minimal():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_minimal.html")

        @app.route("/ticker")
        def ticker():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_ticker.html")

        @app.route("/circle")
        def circle():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_circle.html")

        @app.route("/equalizer")
        def equalizer():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_equalizer.html")

        @app.route("/vinyl")
        def vinyl():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_vinyl.html")

        @app.route("/corner")
        def corner():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_corner.html")

        @app.route("/banner")
        def banner():
            return send_from_directory(str(_OVERLAYS_DIR), "now_playing_banner.html")

        @app.route("/static/<path:filename>")
        def static_files(filename):
            return send_from_directory(str(_OVERLAYS_DIR / "static"), filename)

        try:
            import werkzeug.serving
            server = werkzeug.serving.make_server("localhost", self._port, app)
            self._server = server
            self._ready.set()
            server.serve_forever()
        except OSError as exc:
            self._ready.set()
            logger.error("Overlay server failed to bind port %d: %s", self._port, exc)
        except Exception as exc:
            logger.error("Overlay server error: %s", exc)
