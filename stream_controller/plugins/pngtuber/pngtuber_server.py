from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.pngtuber.pngtuber_repository import PngTuberRepository
    from stream_controller.plugins.pngtuber.avatar_engine import AvatarEngine

logger = logging.getLogger(__name__)

from stream_controller.constants import PNGTUBER_PORT

try:
    from flask import Flask, Response, send_from_directory
    _FLASK = True
except ImportError:
    _FLASK = False

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_PORT = PNGTUBER_PORT


class PngTuberServer:
    def __init__(self, repo: "PngTuberRepository", engine: "AvatarEngine") -> None:
        self._repo = repo
        self._engine = engine
        self._server = None
        self._sse_queues: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._current_level: float = 0.0

    @property
    def base_url(self) -> str:
        return f"http://localhost:{_PORT}"

    def start(self) -> None:
        if not _FLASK:
            logger.warning("Flask not available — pngtuber server not started")
            return
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="pngtuber-server").start()
        self._ready.wait(timeout=5.0)
        logger.info("PNGtuber server ready on port %d", _PORT)

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def push_state(self, state: str, level: float) -> None:
        self._current_level = level
        payload = json.dumps({"state": state, "level": round(float(level), 3)})
        data = f"data: {payload}\n\n"
        with self._sse_lock:
            dead = []
            for q in self._sse_queues:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_queues.remove(q)

    def _run(self) -> None:
        import logging as _log
        _log.getLogger("werkzeug").setLevel(_log.ERROR)

        app = Flask(__name__, static_folder=None)
        repo = self._repo
        engine = self._engine

        def _state_dict():
            return {
                "state": engine.state,
                "expression": repo.get("active_expression"),
                "level": round(self._current_level, 3),
                "chroma_color": repo.get("chroma_color"),
                "canvas_width": repo.get("canvas_width"),
                "canvas_height": repo.get("canvas_height"),
            }

        @app.route("/")
        def index():
            return send_from_directory(str(_OVERLAYS_DIR), "avatar.html")

        @app.route("/avatar")
        def avatar():
            return send_from_directory(str(_OVERLAYS_DIR), "avatar.html")

        @app.route("/api/state")
        def api_state():
            resp = Response(json.dumps(_state_dict()), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/api/images/<expression>/<layer>")
        def api_image(expression: str, layer: str):
            allowed_layers = {"idle", "talking", "idle_blink", "talking_blink"}
            if layer not in allowed_layers:
                return Response("Invalid layer", status=400)
            if expression not in repo.list_expressions():
                return Response("Unknown expression", status=404)
            layers = repo.get_expression(expression)
            path_str = layers.get(layer, "")
            if not path_str:
                return Response("Not configured", status=404)
            p = Path(path_str).resolve()
            if not p.exists() or not p.is_file():
                return Response("File not found", status=404)
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                return Response("Invalid file type", status=400)
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            return Response(p.read_bytes(), mimetype=mime)

        @app.route("/events")
        def events():
            q: queue.Queue = queue.Queue(maxsize=50)
            with self._sse_lock:
                self._sse_queues.append(q)

            def generate():
                try:
                    # Send current state immediately on connect
                    yield f"data: {json.dumps({'state': engine.state, 'level': round(self._current_level, 3)})}\n\n"
                    while True:
                        try:
                            msg = q.get(timeout=30)
                            yield msg
                        except queue.Empty:
                            yield ": keepalive\n\n"
                except GeneratorExit:
                    pass
                finally:
                    with self._sse_lock:
                        if q in self._sse_queues:
                            self._sse_queues.remove(q)

            return Response(generate(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        try:
            import werkzeug.serving
            server = werkzeug.serving.make_server("localhost", _PORT, app, threaded=True)
            self._server = server
            self._ready.set()
            server.serve_forever()
        except OSError as exc:
            self._ready.set()
            logger.error("PNGtuber server failed on port %d: %s", _PORT, exc)
        except Exception as exc:
            self._ready.set()
            logger.error("PNGtuber server error: %s", exc)
