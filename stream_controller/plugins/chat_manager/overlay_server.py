from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stream_controller.plugins.chat_manager.chat_state import ChatStateManager

try:
    from flask import Flask, Response, jsonify, request, send_from_directory
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False

_OVERLAYS_DIR = Path(__file__).parent / "overlays"
_DEFAULT_PORT = 47892
_MAX_FEED_MESSAGES = 50


class ChatOverlayServer:
    def __init__(self, chat_state: "ChatStateManager", port: int = _DEFAULT_PORT) -> None:
        self._chat_state = chat_state
        self._port = port
        self._thread: threading.Thread | None = None
        self._server = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        if not _FLASK_AVAILABLE:
            logger.warning("Flask not available — chat overlay server not started")
            return
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="chat-overlay-server"
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)
        logger.info("Chat overlay server ready on port %d", self._port)

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
        chat_state = self._chat_state

        @app.after_request
        def _no_cache(response):
            if "text/html" in response.content_type:
                response.headers["Cache-Control"] = "no-store"
            return response

        @app.route("/api/messages")
        def api_messages():
            since_id = request.args.get("since", "")
            all_msgs = [m for m in chat_state.messages if not m.deleted][-_MAX_FEED_MESSAGES:]

            if since_id:
                found = False
                for i, m in enumerate(all_msgs):
                    if m.msg_id == since_id:
                        all_msgs = all_msgs[i + 1:]
                        found = True
                        break
                if not found:
                    all_msgs = all_msgs

            data = {
                "messages": [m.to_dict() for m in all_msgs],
                "status": chat_state.state.status.value,
                "channel": chat_state.state.channel,
            }
            resp = Response(json.dumps(data), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/api/state")
        def api_state():
            s = chat_state.state
            data = {
                "status": s.status.value,
                "channel": s.channel,
                "slow_mode": s.slow_mode,
                "sub_only": s.sub_only,
                "emote_only": s.emote_only,
            }
            resp = Response(json.dumps(data), mimetype="application/json")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp

        @app.route("/")
        @app.route("/feed")
        def feed():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_feed.html")

        @app.route("/popup")
        def popup():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_popup.html")

        @app.route("/ticker")
        def ticker():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_ticker.html")

        @app.route("/minimal")
        def minimal():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_minimal.html")

        @app.route("/alert")
        def alert():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_alert.html")

        @app.route("/sidebar")
        def sidebar():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_sidebar.html")

        @app.route("/neon")
        def neon():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_neon.html")

        @app.route("/spotlight")
        def spotlight():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_spotlight.html")

        @app.route("/bubbles")
        def bubbles():
            return send_from_directory(str(_OVERLAYS_DIR), "chat_bubbles.html")

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
            logger.error("Chat overlay server failed to bind port %d: %s", self._port, exc)
        except Exception as exc:
            self._ready.set()
            logger.error("Chat overlay server error: %s", exc)
