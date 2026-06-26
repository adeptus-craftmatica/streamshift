from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.scene_manager.scene_client import SceneClient

logger = logging.getLogger(__name__)

try:
    from flask import Flask, Response, request, send_from_directory
    _FLASK = True
except ImportError:
    _FLASK = False

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_PORT = 47895


class SceneOverlayServer:
    def __init__(self, client: "SceneClient", port: int = _PORT) -> None:
        self._client = client
        self._port   = port
        self._server = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        if not _FLASK:
            logger.warning("Flask not available — scene overlay server not started")
            return
        threading.Thread(target=self._run, daemon=True, name="scene-overlay-server").start()
        logger.info("Scene overlay server started on port %d", self._port)

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _run(self) -> None:
        import logging as _log
        _log.getLogger("werkzeug").setLevel(_log.ERROR)
        app  = Flask(__name__, static_folder=None)
        cli  = self._client

        def _state_json():
            resp = Response(
                json.dumps(cli.state.to_dict()),
                mimetype="application/json",
            )
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/api/state")
        def api_state():
            return _state_json()

        @app.route("/name")
        def overlay_name():
            return send_from_directory(str(_OVERLAYS_DIR), "scene_name.html")

        @app.route("/bar")
        def overlay_bar():
            return send_from_directory(str(_OVERLAYS_DIR), "scene_bar.html")

        @app.route("/grid")
        def overlay_grid():
            return send_from_directory(str(_OVERLAYS_DIR), "scene_grid.html")

        @app.route("/transition")
        def overlay_transition():
            return send_from_directory(str(_OVERLAYS_DIR), "scene_transition.html")

        @app.route("/")
        def index():
            return send_from_directory(str(_OVERLAYS_DIR), "scene_name.html")

        @app.route("/static/<path:filename>")
        def static_files(filename):
            return send_from_directory(str(_OVERLAYS_DIR / "static"), filename)

        try:
            import werkzeug.serving
            server = werkzeug.serving.make_server("localhost", self._port, app)
            self._server = server
            server.serve_forever()
        except OSError as exc:
            logger.error("Scene overlay server failed on port %d: %s", self._port, exc)
        except Exception as exc:
            logger.error("Scene overlay server error: %s", exc)
