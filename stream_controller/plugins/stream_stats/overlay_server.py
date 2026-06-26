from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_PORT = 47896


class StatsOverlayServer:
    def __init__(self, engine) -> None:
        self._engine = engine
        self._thread: threading.Thread | None = None
        self._server = None
        self.base_url = f"http://localhost:{_PORT}"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="stats-overlay-server"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self) -> None:
        try:
            from flask import Flask, render_template, jsonify
            from werkzeug.serving import make_server
            import logging as _logging
            import os

            tmpl = os.path.join(os.path.dirname(__file__), "overlays", "templates")
            stat = os.path.join(os.path.dirname(__file__), "overlays", "static")
            app  = Flask(__name__, template_folder=tmpl, static_folder=stat)
            app.logger.disabled = True
            _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

            engine = self._engine

            @app.route("/api/state")
            def api_state():
                return jsonify(engine.live.to_dict())

            @app.route("/combined")
            def overlay_combined():
                return render_template("stats_combined.html")

            @app.route("/followers")
            def overlay_followers():
                return render_template("stats_followers.html")

            @app.route("/bar")
            def overlay_bar():
                return render_template("stats_bar.html")

            @app.route("/ticker")
            def overlay_ticker():
                return render_template("stats_ticker.html")

            @app.route("/minimal")
            def overlay_minimal():
                return render_template("stats_minimal.html")

            self._server = make_server("127.0.0.1", _PORT, app)
            self._server.serve_forever()
        except Exception as exc:
            logger.error("Stats overlay server failed: %s", exc)
