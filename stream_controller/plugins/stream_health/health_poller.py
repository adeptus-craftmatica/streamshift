from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 1.5
_RECONNECT_INTERVAL = 5.0

_EMPTY_STATS: dict = {
    "connected": False,
    "streaming": False,
    "fps": 0.0,
    "cpu_usage": 0.0,
    "memory_mb": 0.0,
    "render_time_ms": 0.0,
    "dropped_frames": 0,
    "total_frames": 0,
    "dropped_pct": 0.0,
    "stream_duration_ms": 0,
    "output_bytes": 0,
    "error": None,
}


class HealthPoller:
    def __init__(
        self,
        on_stats: Callable[[dict], None],
        get_obs_config: Callable[[], tuple[str, int, str]],
    ) -> None:
        self._on_stats = on_stats
        self._get_obs_config = get_obs_config
        self._client = None
        self._connected = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_reconnect_attempt = 0.0
        self._listeners: list[Callable[[dict], None]] = []
        self._listeners_lock = threading.Lock()

    def add_listener(self, cb: Callable[[dict], None]) -> None:
        with self._listeners_lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[dict], None]) -> None:
        with self._listeners_lock:
            self._listeners = [l for l in self._listeners if l is not cb]

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HealthPoller")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._disconnect()

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._connected = False

    def _try_connect(self) -> bool:
        try:
            from obsws_python import ReqClient
            from stream_controller.plugins.obs_studio.obs_discovery import discover_obs_websocket
            discovered = discover_obs_websocket()
            host, port, password = discovered if discovered else self._get_obs_config()
            self._client = ReqClient(host=host, port=port, password=password, timeout=3)
            self._connected = True
            logger.info("HealthPoller: connected to OBS at %s:%s", host, port)
            return True
        except Exception as exc:
            logger.debug("HealthPoller: connection failed: %s", exc)
            self._client = None
            self._connected = False
            return False

    def _poll(self) -> dict:
        stats_resp = self._client.get_stats()
        stream_resp = self._client.get_stream_status()

        total_frames = getattr(stats_resp, "output_total_frames", 0) or 0
        skipped_frames = getattr(stats_resp, "output_skipped_frames", 0) or 0

        stream_total = getattr(stream_resp, "output_total_frames", 0) or 0
        stream_skipped = getattr(stream_resp, "output_skipped_frames", 0) or 0

        if stream_total > 0:
            total_frames = stream_total
            skipped_frames = stream_skipped

        dropped_pct = (skipped_frames / total_frames * 100.0) if total_frames > 0 else 0.0

        return {
            "connected": True,
            "streaming": bool(getattr(stream_resp, "output_active", False)),
            "fps": float(getattr(stats_resp, "active_fps", 0.0) or 0.0),
            "cpu_usage": float(getattr(stats_resp, "cpu_usage", 0.0) or 0.0),
            "memory_mb": float(getattr(stats_resp, "memory_usage", 0.0) or 0.0),
            "render_time_ms": float(getattr(stats_resp, "average_frame_render_time", 0.0) or 0.0),
            "dropped_frames": int(skipped_frames),
            "total_frames": int(total_frames),
            "dropped_pct": dropped_pct,
            "stream_duration_ms": int(getattr(stream_resp, "output_duration", 0) or 0),
            "output_bytes": int(getattr(stream_resp, "output_bytes", 0) or 0),
            "error": None,
        }

    def _broadcast(self, stats: dict) -> None:
        try:
            self._on_stats(stats)
        except Exception:
            pass
        with self._listeners_lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(stats)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._connected:
                now = time.monotonic()
                if now - self._last_reconnect_attempt >= _RECONNECT_INTERVAL:
                    self._last_reconnect_attempt = now
                    if not self._try_connect():
                        stats = dict(_EMPTY_STATS)
                        stats["error"] = "Cannot connect to OBS WebSocket"
                        self._broadcast(stats)
                        self._stop_event.wait(_POLL_INTERVAL)
                        continue
                else:
                    self._stop_event.wait(_POLL_INTERVAL)
                    continue

            try:
                stats = self._poll()
                self._broadcast(stats)
            except Exception as exc:
                logger.warning("HealthPoller: poll error: %s", exc)
                self._disconnect()
                stats = dict(_EMPTY_STATS)
                stats["error"] = f"OBS connection lost: {exc}"
                self._broadcast(stats)

            self._stop_event.wait(_POLL_INTERVAL)
