from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from stream_controller.plugins.scene_manager.scene_models import (
    ConnectionStatus, Scene, SceneManagerState
)

logger = logging.getLogger(__name__)


class _Signals(QObject):
    state_changed = Signal()


class SceneClient:
    """
    Wraps obsws-python v1.8.0 ReqClient + EventClient.

    obsws-python v1.8.0 specifics:
    - ReqClient methods take POSITIONAL args (no kwargs).
    - Responses are dataclasses with SNAKE_CASE attrs (as_dataclass converts camelCase).
    - EventClient.callback.trigger matches fn.__name__ against "on_<snake_case_event>",
      so handler methods MUST be named on_<snake_case_event_name> exactly.

    All OBS I/O runs on background threads; state changes are marshalled back
    to the Qt main thread via a queued signal.
    """

    def __init__(self, on_state_changed: Callable[[SceneManagerState], None]) -> None:
        self._on_state_changed = on_state_changed
        self._signals = _Signals()
        self._signals.state_changed.connect(self._emit_state, Qt.QueuedConnection)

        self._req: object | None = None
        self._ev:  object | None = None
        self._state = SceneManagerState()
        self._lock = threading.Lock()
        self._subscribers: list[Callable] = []

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def state(self) -> SceneManagerState:
        return self._state

    def connect(self, host: str, port: int, password: str) -> None:
        threading.Thread(
            target=self._do_connect,
            args=(host, port, password),
            daemon=True,
            name="scene-manager-connect",
        ).start()

    def disconnect(self) -> None:
        self._close_clients()
        self._state = SceneManagerState()
        self._signals.state_changed.emit()

    def switch_scene(self, name: str) -> None:
        if self._req is None:
            return
        try:
            # v1.8.0: positional arg only
            self._req.set_current_program_scene(name)
        except Exception as exc:
            logger.warning("switch_scene failed: %s", exc)

    def start_stream(self) -> None:
        """Start OBS streaming on a background thread. No-op if not connected."""
        if self._req is None:
            return
        req = self._req
        def _do():
            try:
                req.start_stream()
            except Exception as exc:
                logger.warning("start_stream failed: %s", exc)
        threading.Thread(target=_do, daemon=True, name="obs-start-stream").start()

    def stop_stream(self) -> None:
        """Stop OBS streaming on a background thread. No-op if not connected."""
        if self._req is None:
            return
        req = self._req
        def _do():
            try:
                req.stop_stream()
            except Exception as exc:
                logger.warning("stop_stream failed: %s", exc)
        threading.Thread(target=_do, daemon=True, name="obs-stop-stream").start()

    def refresh(self) -> None:
        if self._req is None:
            return
        threading.Thread(
            target=self._fetch_state,
            daemon=True,
            name="scene-manager-refresh",
        ).start()

    def get_preview_screenshot(self, scene_name: str) -> str | None:
        """Returns a base64 data-URL JPEG, or None. Safe to call from any thread."""
        if self._req is None or not scene_name:
            return None
        try:
            # v1.8.0: positional args (name, img_format, width, height, quality)
            resp = self._req.get_source_screenshot(scene_name, "jpeg", 320, 180, 50)
            return getattr(resp, "image_data", None)
        except Exception:
            return None

    def subscribe(self, cb: Callable) -> None:
        """Register a callable(SceneManagerState) for live updates on the main thread."""
        if cb not in self._subscribers:
            self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    # ── internal ──────────────────────────────────────────────────────────────

    def _do_connect(self, host: str, port: int, password: str) -> None:
        self._close_clients()
        with self._lock:
            self._state = SceneManagerState(status=ConnectionStatus.CONNECTING)
        self._signals.state_changed.emit()

        try:
            from obsws_python import ReqClient, EventClient, Subs
        except ImportError:
            self._set_error("obsws-python not installed — run: pip install obsws-python")
            return

        try:
            req = ReqClient(host=host, port=port, password=password, timeout=10)
        except Exception as exc:
            self._set_error(f"Could not connect to OBS: {exc}")
            return

        self._req = req

        try:
            ev = EventClient(
                host=host, port=port, password=password,
                subs=Subs.SCENES | Subs.OUTPUTS,
            )
            # IMPORTANT: obsws-python v1.8.0 matches callbacks by __name__ against
            # "on_<to_snake_case(eventType)>". Methods must be named exactly:
            #   CurrentProgramSceneChanged  ->  on_current_program_scene_changed
            #   StreamStateChanged          ->  on_stream_state_changed
            #   RecordStateChanged          ->  on_record_state_changed
            ev.callback.register([
                self.on_current_program_scene_changed,
                self.on_stream_state_changed,
                self.on_record_state_changed,
            ])
            self._ev = ev
        except Exception as exc:
            logger.warning("EventClient failed (live updates disabled): %s", exc)

        self._fetch_state()

    def _fetch_state(self) -> None:
        req = self._req
        if req is None:
            return
        try:
            scene_list    = req.get_scene_list()
            current_info  = req.get_current_program_scene()
            stream_status = req.get_stream_status()
            record_status = req.get_record_status()

            # v1.8.0 responses are dataclasses with snake_case attrs
            current = str(
                getattr(current_info, "current_program_scene_name", None)
                or getattr(scene_list, "current_program_scene_name", None)
                or ""
            )
            raw_scenes = getattr(scene_list, "scenes", []) or []
            scenes = [
                Scene(
                    name=str(s.get("sceneName", "")),
                    uuid=str(s.get("sceneUuid", "")),
                    is_current=str(s.get("sceneName", "")) == current,
                    is_group=bool(s.get("isGroup", False)),
                )
                for s in raw_scenes
                if isinstance(s, dict) and str(s.get("sceneName", ""))
            ]
            with self._lock:
                self._state = SceneManagerState(
                    status=ConnectionStatus.CONNECTED,
                    current_scene=current,
                    scenes=scenes,
                    stream_active=bool(getattr(stream_status, "output_active", False)),
                    record_active=bool(getattr(record_status, "output_active", False)),
                )
            self._signals.state_changed.emit()
        except Exception as exc:
            self._set_error(str(exc))

    def _close_clients(self) -> None:
        for attr in ("_ev", "_req"):
            client = getattr(self, attr, None)
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _set_error(self, msg: str) -> None:
        with self._lock:
            self._state = SceneManagerState(
                status=ConnectionStatus.ERROR, error=msg
            )
        self._signals.state_changed.emit()

    # ── OBS event handlers (background thread) ────────────────────────────────
    # Names MUST match "on_<snake_case_event>" for obsws-python v1.8.0 callback dispatch.

    def on_current_program_scene_changed(self, data) -> None:
        name = str(getattr(data, "scene_name", "") or "")
        with self._lock:
            self._state.current_scene = name
            for s in self._state.scenes:
                s.is_current = s.name == name
            self._state.status = ConnectionStatus.CONNECTED
        self._signals.state_changed.emit()

    def on_stream_state_changed(self, data) -> None:
        active = bool(getattr(data, "output_active", False))
        with self._lock:
            self._state.stream_active = active
        self._signals.state_changed.emit()

    def on_record_state_changed(self, data) -> None:
        active = bool(getattr(data, "output_active", False))
        with self._lock:
            self._state.record_active = active
        self._signals.state_changed.emit()

    def _emit_state(self) -> None:
        self._on_state_changed(self._state)
        for cb in list(self._subscribers):
            try:
                cb(self._state)
            except RuntimeError:
                self._subscribers = [s for s in self._subscribers if s is not cb]
