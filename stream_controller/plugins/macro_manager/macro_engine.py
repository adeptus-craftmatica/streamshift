from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from stream_controller.core.action_registry import ActionRegistry
    from stream_controller.core.app_context import AppContext
    from stream_controller.core.hotkey_manager import HotkeyManager
    from stream_controller.plugins.macro_manager.macro_models import Macro, MacroStep
    from stream_controller.plugins.macro_manager.macro_repository import MacroRepository

logger = logging.getLogger(__name__)

from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore as _RaidTargetStore


def _audio_duration_seconds(path: str) -> float:
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if f and f.info:
            return float(f.info.length)
    except Exception:
        pass
    return 0.0


class MacroEngine(QObject):
    macro_started = Signal(str)
    macro_finished = Signal(str)

    def __init__(
        self,
        repo: MacroRepository,
        action_registry: ActionRegistry,
        hotkey_manager: HotkeyManager,
        app_context: AppContext,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._action_registry = action_registry
        self._hotkey_manager = hotkey_manager
        self._app_context = app_context
        self._running: set[str] = set()

    @property
    def repo(self) -> MacroRepository:
        return self._repo

    def is_running(self, macro_id: str) -> bool:
        return macro_id in self._running

    def run_macro(self, macro_id: str) -> None:
        if macro_id in self._running:
            logger.debug("Macro %s already running, skipping", macro_id)
            return
        macro = self._repo.get_macro(macro_id)
        if macro is None:
            logger.warning("Macro %s not found", macro_id)
            return
        self._running.add(macro_id)
        self.macro_started.emit(macro_id)
        threading.Thread(
            target=self._execute,
            args=(macro_id,),
            daemon=True,
            name=f"macro-{macro_id}",
        ).start()

    def _execute(self, macro_id: str) -> None:
        macro = self._repo.get_macro(macro_id)
        if macro is None:
            self._running.discard(macro_id)
            self.macro_finished.emit(macro_id)
            return
        run_ctx: dict = {}  # shared state across steps within this single run
        try:
            for step in macro.steps:
                try:
                    self._run_step(step, macro, run_ctx)
                except Exception as exc:
                    logger.error("Macro %s step %s error: %s", macro_id, step.step_type, exc)
        finally:
            self._running.discard(macro_id)
            self.macro_finished.emit(macro_id)

    def _run_step(self, step: MacroStep, macro: Macro, run_ctx: dict | None = None) -> None:
        if run_ctx is None:
            run_ctx = {}
        t = step.step_type

        if t in ("services.connect", "services.disconnect"):
            connecting = t == "services.connect"
            service_ids = step.params.get("services", [])
            _ALLOWED_QCP_METHODS = {
                "_connect_obs", "_disconnect_obs",
                "_connect_bots", "_disconnect_bots",
                "_connect_chat", "_disconnect_chat",
                "_connect_stats", "_disconnect_stats",
                "_connect_info", "_disconnect_info",
                "_connect_pngtuber", "_disconnect_pngtuber",
            }
            qcp = self._get_qcp()
            for sid in service_ids:
                method = f"_{'connect' if connecting else 'disconnect'}_{self._service_method_name(sid)}"
                if method not in _ALLOWED_QCP_METHODS:
                    logger.warning("service %s: method %r not in allowlist, skipping", sid, method)
                    continue
                if qcp and hasattr(qcp, method):
                    try:
                        getattr(qcp, method)()
                    except Exception as e:
                        logger.warning("service %s: %s", sid, e)
                else:
                    self._connect_service_direct(sid, connecting)

        elif t == "stream_info.update":
            plugin = self._get_plugin("stream_info")
            if plugin:
                title = step.params.get("title", "")
                category = step.params.get("category", "")
                category_id = ""
                try:
                    info = getattr(getattr(plugin, "_state", None), "info", None)
                    if info and category and category.lower() == info.category_name.lower():
                        category_id = info.category_id
                except Exception:
                    pass
                try:
                    plugin.update_info(title=title, category_id=category_id)
                except Exception as exc:
                    logger.warning("stream_info.update: %s", exc)

        elif t == "obs.start_stream":
            plugin = self._get_plugin("obs_studio")
            if plugin and hasattr(plugin, "_service") and plugin._service:
                plugin._service.start_stream()

        elif t == "obs.stop_stream":
            plugin = self._get_plugin("obs_studio")
            if plugin and hasattr(plugin, "_service") and plugin._service:
                plugin._service.stop_stream()

        elif t == "obs.switch_scene":
            scene_name = step.params.get("scene_name", "")
            plugin = self._get_plugin("scene_manager")
            if plugin and hasattr(plugin, "_client") and plugin._client:
                plugin._client.switch_scene(scene_name)

        elif t == "music.choose":
            # Store tracks in run context — does NOT play yet
            paths = [str(p) for p in step.params.get("track_paths", [])]
            run_ctx["chosen_tracks"] = paths
            run_ctx["chosen_shuffle"] = step.params.get("shuffle", False)
            run_ctx["chosen_repeat"] = step.params.get("repeat", False)
            run_ctx["chosen_overlay"] = step.params.get("overlay_style", "None")

        elif t == "music.play_chosen":
            plugin = self._get_plugin("music_manager")
            if plugin and hasattr(plugin, "_music_state") and plugin._music_state:
                paths = [Path(p) for p in run_ctx.get("chosen_tracks", [])]
                if not paths:
                    logger.warning("music.play_chosen: no tracks were chosen earlier in this macro")
                else:
                    if run_ctx.get("chosen_shuffle"):
                        import random as _r
                        _r.shuffle(paths)
                    ms = plugin._music_state
                    ms.play_queue(paths)
                    try:
                        repeat = run_ctx.get("chosen_repeat", False)
                        if repeat and not ms.state.repeat:
                            ms.toggle_repeat()
                        elif not repeat and ms.state.repeat:
                            ms.toggle_repeat()
                    except Exception:
                        pass
        elif t == "music.play_playlist":
            plugin = self._get_plugin("music_manager")
            if plugin and hasattr(plugin, "_music_state") and plugin._music_state and hasattr(plugin, "_playlists") and plugin._playlists:
                playlist_id = step.params.get("playlist_id", "")
                pl = plugin._playlists.get(playlist_id)
                if pl and pl.tracks:
                    paths = list(pl.tracks)
                    if step.params.get("shuffle"):
                        import random as _r
                        _r.shuffle(paths)
                    plugin._music_state.play_queue(paths, playlist_id=playlist_id)

        elif t == "music.stop":
            plugin = self._get_plugin("music_manager")
            if plugin and hasattr(plugin, "_music_state") and plugin._music_state:
                plugin._music_state.stop()

        elif t == "timer.create":
            plugin = self._get_plugin("timer_manager")
            if plugin and hasattr(plugin, "_engine") and plugin._engine:
                label = step.params.get("label", "Macro Timer")
                mode_str = step.params.get("mode", "Countdown")
                duration_source = step.params.get("duration_source", "Manual")

                if duration_source == "Music Tracks":
                    duration = self._sum_track_duration(macro)
                else:
                    duration = float(step.params.get("duration_seconds", 300))

                from stream_controller.plugins.timer_manager.timer_engine import TimerMode
                mode = TimerMode.COUNTDOWN if mode_str == "Countdown" else TimerMode.COUNTUP

                eng = plugin._engine
                from stream_controller.plugins.timer_manager.timer_models import TimerStatus

                # Stop any currently running timers so only this one runs
                for tm in eng.timers:
                    if tm.status == TimerStatus.RUNNING:
                        eng.stop(tm.timer_id)

                target_id = step.params.get("target_timer_id", "")
                if target_id and eng.get(target_id):
                    # Pin to a specific existing timer — update its duration and start it
                    timer_id = target_id
                    eng.update_timer(timer_id, duration=duration, mode=mode)
                else:
                    existing = next((tm for tm in eng.timers if tm.label == label), None)
                    if existing:
                        timer_id = existing.timer_id
                        eng.update_timer(timer_id, duration=duration, mode=mode)
                    else:
                        created = eng.add_timer(label=label, mode=mode, duration=duration)
                        timer_id = created.timer_id

                step.params["_created_timer_id"] = timer_id
                eng.reset(timer_id)
                eng.start(timer_id)
                logger.info("timer.create: started timer %s (%.1fs, %s)", timer_id, duration, mode_str)

                if step.params.get("wait_for_finish", False):
                    logger.info("timer.create: waiting for timer %s to finish", timer_id)
                    deadline = time.monotonic() + duration + 30.0  # duration + 30s grace
                    while time.monotonic() < deadline:
                        t = eng.get(timer_id)
                        if t is None or t.status == TimerStatus.FINISHED:
                            break
                        time.sleep(0.25)
                    else:
                        logger.warning("timer.create: timed out waiting for timer %s", timer_id)
                    logger.info("timer.create: timer %s done, continuing macro", timer_id)

        elif t in ("timer.start", "timer.stop", "timer.reset"):
            plugin = self._get_plugin("timer_manager")
            if plugin and hasattr(plugin, "_engine") and plugin._engine:
                eng = plugin._engine
                timer_id = step.params.get("timer_id", "")
                if not timer_id:
                    timers = eng.timers
                    if timers:
                        timer_id = timers[0].timer_id
                if timer_id:
                    if t == "timer.start":
                        eng.reset(timer_id)
                        eng.start(timer_id)
                    elif t == "timer.stop":
                        eng.stop(timer_id)
                    elif t == "timer.reset":
                        eng.reset(timer_id)

        elif t == "chat.send":
            message = step.params.get("message", "")
            plugin = self._get_plugin("bot_manager")
            if plugin and hasattr(plugin, "_engines"):
                for bot_id, engine in (plugin._engines or {}).items():
                    try:
                        engine.send_chat_message(message)
                    except Exception as exc:
                        logger.warning("chat.send bot %s: %s", bot_id, exc)

        elif t == "chat.raid":
            target = step.params.get("target", "").strip().lstrip("@")
            if target:
                plugin = self._get_plugin("bot_manager")
                if plugin and hasattr(plugin, "_engines"):
                    for bot_id, engine in (plugin._engines or {}).items():
                        try:
                            engine.send_chat_message(f"/raid {target}")
                        except Exception as exc:
                            logger.warning("chat.raid bot %s: %s", bot_id, exc)
                _RaidTargetStore.add(target)

        elif t == "social.post_template":
            template_id = step.params.get("template_id", "").strip()
            if template_id:
                plugin = self._get_plugin("social_manager")
                if plugin and hasattr(plugin, "post_template"):
                    ok, msg = plugin.post_template(template_id)
                    if not ok:
                        logger.warning("social.post_template: %s", msg)

        elif t == "social.post_text":
            text = step.params.get("text", "").strip()
            if text:
                plugin = self._get_plugin("social_manager")
                if plugin:
                    text = plugin.resolve_template(text)
                    client = getattr(plugin, "_client", None)
                    if client and client.connected:
                        try:
                            client.post_text(text)
                        except Exception as exc:
                            logger.warning("social.post_text: %s", exc)
                    else:
                        logger.warning("social.post_text: Bluesky not connected")

        elif t == "social.connect":
            plugin = self._get_plugin("social_manager")
            if plugin:
                plugin._try_auto_connect()

        elif t == "social.disconnect":
            plugin = self._get_plugin("social_manager")
            if plugin:
                client = getattr(plugin, "_client", None)
                if client:
                    client.disconnect()

        elif t == "delay":
            time.sleep(step.params.get("delay_ms", 500) / 1000)

        elif t == "action":
            action_id = step.params.get("action_id", "")
            if action_id:
                self._action_registry.execute(action_id)

    def _sum_track_duration(self, macro: Macro) -> float:
        total = 0.0
        for step in macro.steps:
            if step.step_type == "music.choose":
                for path in step.params.get("track_paths", []):
                    total += _audio_duration_seconds(path)
        return max(total, 1.0)

    def _get_plugin(self, plugin_id: str):
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get(plugin_id)
            return lp.instance if lp else None
        except Exception:
            return None

    def _get_qcp(self):
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("quick_connect")
            if lp and lp.instance:
                return getattr(lp.instance, "_page", None)
        except Exception:
            return None

    def _service_method_name(self, sid: str) -> str:
        return {
            "obs_studio": "obs",
            "scene_manager": "obs",
            "bot_manager": "bots",
            "chat_manager": "chat",
            "stream_stats": "stats",
            "stream_info": "info",
            "pngtuber": "pngtuber",
        }.get(sid, sid)

    def _connect_service_direct(self, sid: str, connect: bool) -> None:
        plugin = self._get_plugin(sid)
        if not plugin:
            return
        method = "do_connect" if connect else "do_disconnect"
        if hasattr(plugin, method):
            getattr(plugin, method)()
        elif connect and sid == "obs_studio" and hasattr(plugin, "connect"):
            plugin.connect()
        elif not connect and sid == "obs_studio" and hasattr(plugin, "disconnect"):
            plugin.disconnect()
        elif connect and sid == "bot_manager" and hasattr(plugin, "start_all_bots"):
            plugin.start_all_bots()
        elif not connect and sid == "bot_manager" and hasattr(plugin, "stop_all_bots"):
            plugin.stop_all_bots()
        elif connect and sid == "chat_manager":
            state = getattr(plugin, "_chat_state", None)
            if state and hasattr(state, "connect"):
                state.connect()
        elif not connect and sid == "chat_manager":
            state = getattr(plugin, "_chat_state", None)
            if state and hasattr(state, "disconnect"):
                state.disconnect()


