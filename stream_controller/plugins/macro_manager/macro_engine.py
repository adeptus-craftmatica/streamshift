from __future__ import annotations

import json
import logging
import random
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
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

from stream_controller.plugins.macro_manager.macro_models import MacroExecutionRecord
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
    execution_finished = Signal(object)  # emits MacroExecutionRecord

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
        run_id = str(uuid.uuid4())
        started_at = time.time()
        steps_completed = 0
        total_steps = len(macro.steps) if macro else 0
        error_msg: str | None = None
        success = False

        if macro is None:
            self._running.discard(macro_id)
            self.macro_finished.emit(macro_id)
            record = MacroExecutionRecord(
                run_id=run_id,
                macro_id=macro_id,
                macro_name="",
                started_at=started_at,
                finished_at=time.time(),
                steps_completed=0,
                total_steps=0,
                error="Macro not found",
                success=False,
            )
            self.execution_finished.emit(record)
            return

        context: dict = {"vars": {}, "loop_index": 0}

        try:
            for step in macro.steps:
                ok = self._run_step(step, macro, context)
                if ok:
                    steps_completed += 1
                else:
                    error_msg = f"Step {step.step_type} returned abort"
                    break
            else:
                success = True
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Macro %s unhandled error: %s", macro_id, exc)
        finally:
            self._running.discard(macro_id)
            self.macro_finished.emit(macro_id)

        record = MacroExecutionRecord(
            run_id=run_id,
            macro_id=macro_id,
            macro_name=macro.name,
            started_at=started_at,
            finished_at=time.time(),
            steps_completed=steps_completed,
            total_steps=total_steps,
            error=error_msg,
            success=success,
        )
        self.execution_finished.emit(record)

    # ------------------------------------------------------------------
    # Template resolution
    # ------------------------------------------------------------------

    def _resolve_template(self, text: str, context: dict) -> str:
        if not text:
            return text

        def _replace(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith("var:"):
                return context.get("vars", {}).get(key[4:], "")
            if key == "loop_index":
                return str(context.get("loop_index", 0))
            if key == "title":
                try:
                    plugin = self._get_plugin("stream_info")
                    if plugin:
                        state = getattr(plugin, "_state", None)
                        info = getattr(state, "info", None) if state else None
                        if info and hasattr(info, "title"):
                            return str(info.title)
                except Exception:
                    pass
                return ""
            if key == "viewer_count":
                vc = self._get_viewer_count()
                return str(vc) if vc is not None else ""
            if key == "url":
                try:
                    bp = self._get_plugin("bot_manager")
                    if bp and hasattr(bp, "_engines"):
                        for eng in (bp._engines or {}).values():
                            cfg = getattr(eng, "_config", None)
                            ch = getattr(cfg, "twitch_channel", None) if cfg else None
                            if ch:
                                return f"https://twitch.tv/{ch}"
                except Exception:
                    pass
                return ""
            return m.group(0)  # leave unknown tokens as-is

        return re.sub(r"\{([^}]+)\}", _replace, text)

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def _run_step(self, step: MacroStep, macro: Macro, context: dict | None = None) -> bool:
        """Execute one step. Returns True to continue, False to abort macro."""
        if context is None:
            context = {"vars": {}, "loop_index": 0}

        on_error = getattr(step, "on_error", "skip")

        def _attempt() -> bool:
            return self._execute_step(step, macro, context)

        try:
            return _attempt()
        except Exception as exc:
            if on_error == "retry":
                logger.warning("Macro step %s error (retrying): %s", step.step_type, exc)
                try:
                    return _attempt()
                except Exception as exc2:
                    logger.warning("Macro step %s retry failed (skipping): %s", step.step_type, exc2)
                    return True  # treat as skip after retry
            elif on_error == "abort":
                logger.error("Macro step %s error (aborting): %s", step.step_type, exc)
                return False
            else:  # skip
                logger.warning("Macro step %s error (skipping): %s", step.step_type, exc)
                return True

    def _execute_step(self, step: MacroStep, macro: Macro, context: dict) -> bool:
        """Inner execution — raises on error so _run_step can apply on_error policy."""
        t = step.step_type
        params = step.params

        # ── Services ──────────────────────────────────────────────────
        if t in ("services.connect", "services.disconnect"):
            connecting = t == "services.connect"
            service_ids = params.get("services", [])
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

        # ── Stream Info ───────────────────────────────────────────────
        elif t == "stream_info.update":
            plugin = self._get_plugin("stream_info")
            if plugin:
                title = params.get("title", "")
                category = params.get("category", "")
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

        # ── OBS — existing ────────────────────────────────────────────
        elif t == "obs.start_stream":
            plugin = self._get_plugin("obs_studio")
            if plugin and hasattr(plugin, "_service") and plugin._service:
                plugin._service.start_stream()

        elif t == "obs.stop_stream":
            plugin = self._get_plugin("obs_studio")
            if plugin and hasattr(plugin, "_service") and plugin._service:
                plugin._service.stop_stream()

        elif t == "obs.switch_scene":
            scene_name = params.get("scene_name", "")
            plugin = self._get_plugin("scene_manager")
            if plugin and hasattr(plugin, "_client") and plugin._client:
                plugin._client.switch_scene(scene_name)

        # ── OBS — new ─────────────────────────────────────────────────
        elif t == "obs.toggle_source":
            obs_client = self._get_obs_client()
            if obs_client:
                source_name = params.get("source_name", "")
                visible = bool(params.get("visible", True))
                try:
                    # Get current scene, then find scene item id, then set enabled
                    scene_resp = obs_client.call("GetCurrentProgramScene")
                    scene_name = scene_resp.attrs().get("currentProgramSceneName", "")
                    items_resp = obs_client.call("GetSceneItemList", {"sceneName": scene_name})
                    items = items_resp.attrs().get("sceneItems", [])
                    item_id = None
                    for item in items:
                        if item.get("sourceName") == source_name:
                            item_id = item.get("sceneItemId")
                            break
                    if item_id is not None:
                        obs_client.call("SetSceneItemEnabled", {
                            "sceneName": scene_name,
                            "sceneItemId": item_id,
                            "sceneItemEnabled": visible,
                        })
                    else:
                        logger.warning("obs.toggle_source: source %r not found in scene %r", source_name, scene_name)
                except Exception as exc:
                    logger.warning("obs.toggle_source: %s", exc)

        elif t == "obs.set_mute":
            obs_client = self._get_obs_client()
            if obs_client:
                source_name = params.get("source_name", "")
                muted = bool(params.get("muted", False))
                try:
                    obs_client.call("SetInputMute", {"inputName": source_name, "inputMuted": muted})
                except Exception as exc:
                    logger.warning("obs.set_mute: %s", exc)

        elif t == "obs.set_volume":
            obs_client = self._get_obs_client()
            if obs_client:
                source_name = params.get("source_name", "")
                db = float(params.get("volume_db", -10.0))
                db = max(-100.0, min(0.0, db))
                mul = 10 ** (db / 20.0)
                try:
                    obs_client.call("SetInputVolume", {
                        "inputName": source_name,
                        "inputVolumeMul": mul,
                    })
                except Exception as exc:
                    logger.warning("obs.set_volume: %s", exc)

        elif t == "obs.start_recording":
            obs_client = self._get_obs_client()
            if obs_client:
                try:
                    obs_client.call("StartRecord")
                except Exception as exc:
                    logger.warning("obs.start_recording: %s", exc)

        elif t == "obs.stop_recording":
            obs_client = self._get_obs_client()
            if obs_client:
                try:
                    obs_client.call("StopRecord")
                except Exception as exc:
                    logger.warning("obs.stop_recording: %s", exc)

        # ── Music ─────────────────────────────────────────────────────
        elif t == "music.choose":
            paths = [str(p) for p in params.get("track_paths", [])]
            context["chosen_tracks"] = paths
            context["chosen_shuffle"] = params.get("shuffle", False)
            context["chosen_repeat"] = params.get("repeat", False)
            context["chosen_overlay"] = params.get("overlay_style", "None")

        elif t == "music.play_chosen":
            plugin = self._get_plugin("music_manager")
            if plugin and hasattr(plugin, "_music_state") and plugin._music_state:
                paths = [Path(p) for p in context.get("chosen_tracks", [])]
                if not paths:
                    logger.warning("music.play_chosen: no tracks were chosen earlier in this macro")
                else:
                    if context.get("chosen_shuffle"):
                        import random as _r
                        _r.shuffle(paths)
                    ms = plugin._music_state
                    ms.play_queue(paths)
                    try:
                        repeat = context.get("chosen_repeat", False)
                        if repeat and not ms.state.repeat:
                            ms.toggle_repeat()
                        elif not repeat and ms.state.repeat:
                            ms.toggle_repeat()
                    except Exception:
                        pass

        elif t == "music.play_playlist":
            plugin = self._get_plugin("music_manager")
            if (plugin and hasattr(plugin, "_music_state") and plugin._music_state
                    and hasattr(plugin, "_playlists") and plugin._playlists):
                playlist_id = params.get("playlist_id", "")
                pl = plugin._playlists.get(playlist_id)
                if pl and pl.tracks:
                    paths = list(pl.tracks)
                    if params.get("shuffle"):
                        import random as _r
                        _r.shuffle(paths)
                    plugin._music_state.play_queue(paths, playlist_id=playlist_id)

        elif t == "music.stop":
            plugin = self._get_plugin("music_manager")
            if plugin and hasattr(plugin, "_music_state") and plugin._music_state:
                plugin._music_state.stop()

        # ── Timer ─────────────────────────────────────────────────────
        elif t == "timer.create":
            plugin = self._get_plugin("timer_manager")
            if plugin and hasattr(plugin, "_engine") and plugin._engine:
                label = params.get("label", "Macro Timer")
                mode_str = params.get("mode", "Countdown")
                duration_source = params.get("duration_source", "Manual")

                if duration_source == "Music Tracks":
                    duration = self._sum_track_duration(macro)
                else:
                    duration = float(params.get("duration_seconds", 300))

                from stream_controller.plugins.timer_manager.timer_engine import TimerMode
                mode = TimerMode.COUNTDOWN if mode_str == "Countdown" else TimerMode.COUNTUP

                eng = plugin._engine
                from stream_controller.plugins.timer_manager.timer_models import TimerStatus

                for tm in eng.timers:
                    if tm.status == TimerStatus.RUNNING:
                        eng.stop(tm.timer_id)

                target_id = params.get("target_timer_id", "")
                if target_id and eng.get(target_id):
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

                params["_created_timer_id"] = timer_id
                eng.reset(timer_id)
                eng.start(timer_id)
                logger.info("timer.create: started timer %s (%.1fs, %s)", timer_id, duration, mode_str)

                if params.get("wait_for_finish", False):
                    logger.info("timer.create: waiting for timer %s to finish", timer_id)
                    deadline = time.monotonic() + duration + 30.0
                    while time.monotonic() < deadline:
                        tm = eng.get(timer_id)
                        if tm is None or tm.status == TimerStatus.FINISHED:
                            break
                        time.sleep(0.25)
                    else:
                        logger.warning("timer.create: timed out waiting for timer %s", timer_id)
                    logger.info("timer.create: timer %s done, continuing macro", timer_id)

        elif t in ("timer.start", "timer.stop", "timer.reset"):
            plugin = self._get_plugin("timer_manager")
            if plugin and hasattr(plugin, "_engine") and plugin._engine:
                eng = plugin._engine
                timer_id = params.get("timer_id", "")
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

        # ── Chat — existing ───────────────────────────────────────────
        elif t == "chat.send":
            message = self._resolve_template(params.get("message", ""), context)
            plugin = self._get_plugin("bot_manager")
            if plugin and hasattr(plugin, "_engines"):
                for bot_id, engine in (plugin._engines or {}).items():
                    try:
                        engine.send_chat_message(message)
                    except Exception as exc:
                        logger.warning("chat.send bot %s: %s", bot_id, exc)

        elif t == "chat.timed_sequence":
            import random as _random
            from stream_controller.plugins.macro_manager.chat_pool import ChatMessagePool

            messages: list[str] = []

            if params.get("use_pool", True):
                pool = ChatMessagePool.load()
                count = int(params.get("pool_count", 3))
                if pool:
                    drawn = _random.sample(pool, min(count, len(pool)))
                    messages.extend(drawn)

            raw_extra = params.get("extra_messages", "")
            extras = [m.strip() for m in raw_extra.splitlines() if m.strip()]
            messages.extend(extras)

            _random.shuffle(messages)

            duration = float(params.get("duration_seconds", 600.0))
            spread = params.get("spread", "Random")
            wait = params.get("wait_for_finish", True)

            if not messages:
                logger.warning("chat.timed_sequence: no messages in pool or step — skipping")
            else:
                pad = min(5.0, duration / (len(messages) + 1))
                window_start = pad
                window_end = duration - pad

                if spread == "Even":
                    step_size = (window_end - window_start) / max(len(messages) - 1, 1) if len(messages) > 1 else 0
                    offsets = sorted([window_start + i * step_size for i in range(len(messages))])
                else:
                    offsets = sorted(_random.uniform(window_start, window_end) for _ in messages)

                def _send_sequence(msgs, times, bot_plugin) -> None:
                    t0 = time.monotonic()
                    for msg, send_at in zip(msgs, times):
                        now = time.monotonic() - t0
                        wait_sec = send_at - now
                        if wait_sec > 0:
                            time.sleep(wait_sec)
                        if bot_plugin and hasattr(bot_plugin, "_engines"):
                            for bot_id, engine in (bot_plugin._engines or {}).items():
                                try:
                                    engine.send_chat_message(msg)
                                except Exception as exc:
                                    logger.warning("chat.timed_sequence bot %s: %s", bot_id, exc)
                        logger.info("chat.timed_sequence: sent %r at %.1fs", msg[:40], send_at)

                bot_plugin = self._get_plugin("bot_manager")
                if wait:
                    _send_sequence(messages, offsets, bot_plugin)
                else:
                    threading.Thread(
                        target=_send_sequence,
                        args=(messages, offsets, bot_plugin),
                        daemon=True,
                        name="chat-timed-seq",
                    ).start()

        elif t == "chat.raid":
            target = params.get("target", "").strip().lstrip("@")
            if target:
                plugin = self._get_plugin("bot_manager")
                if plugin and hasattr(plugin, "_engines"):
                    for bot_id, engine in (plugin._engines or {}).items():
                        try:
                            engine.send_chat_message(f"/raid {target}")
                        except Exception as exc:
                            logger.warning("chat.raid bot %s: %s", bot_id, exc)
                _RaidTargetStore.add(target)

        # ── Chat — new ────────────────────────────────────────────────
        elif t == "chat.announcement":
            message = self._resolve_template(params.get("message", ""), context)
            color = params.get("color", "primary")
            self._helix_announcement(message, color)

        elif t == "chat.shoutout":
            username = self._resolve_template(params.get("username", ""), context).lstrip("@")
            if username:
                self._helix_shoutout(username)

        elif t == "chat.timeout":
            username = self._resolve_template(params.get("username", ""), context).lstrip("@")
            duration = int(params.get("duration_seconds", 60))
            reason = params.get("reason", "")
            if username:
                self._helix_timeout(username, duration, reason)

        # ── Social ────────────────────────────────────────────────────
        elif t == "social.post_template":
            template_id = params.get("template_id", "").strip()
            if template_id:
                plugin = self._get_plugin("social_manager")
                if plugin and hasattr(plugin, "post_template"):
                    ok, msg = plugin.post_template(template_id)
                    if not ok:
                        logger.warning("social.post_template: %s", msg)

        elif t == "social.post_text":
            text = params.get("text", "").strip()
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

        # ── Flow — existing ───────────────────────────────────────────
        elif t == "delay":
            time.sleep(params.get("delay_ms", 500) / 1000)

        elif t == "action":
            action_id = params.get("action_id", "")
            if action_id:
                self._action_registry.execute(action_id)

        # ── Flow — new ────────────────────────────────────────────────
        elif t == "flow.delay_random":
            min_ms = int(params.get("min_ms", 1000))
            max_ms = int(params.get("max_ms", 5000))
            if max_ms < min_ms:
                max_ms = min_ms
            time.sleep(random.randint(min_ms, max_ms) / 1000.0)

        elif t == "flow.condition":
            result = self._evaluate_predicate(
                params.get("predicate_type", "always"),
                params.get("predicate_value", ""),
                context,
            )
            branch = step.then_steps if result else step.else_steps
            for substep in branch:
                ok = self._run_step(substep, macro, context)
                if not ok:
                    return False

        elif t == "flow.repeat":
            count = int(params.get("count", 1))
            for i in range(count):
                context["loop_index"] = i
                for substep in step.body_steps:
                    ok = self._run_step(substep, macro, context)
                    if not ok:
                        context["loop_index"] = 0
                        return False
            context["loop_index"] = 0

        elif t == "flow.wait_until":
            predicate_type = params.get("predicate_type", "always")
            predicate_value = params.get("predicate_value", "")
            timeout = int(params.get("timeout_seconds", 30))
            on_timeout = params.get("on_timeout", "skip")
            start = time.time()
            while True:
                if self._evaluate_predicate(predicate_type, predicate_value, context):
                    break
                if time.time() - start >= timeout:
                    if on_timeout == "abort":
                        return False
                    break
                time.sleep(1.0)

        # ── Variables ─────────────────────────────────────────────────
        elif t == "variable.set":
            name = params.get("name", "").strip()
            value = self._resolve_template(params.get("value", ""), context)
            if name:
                context["vars"][name] = value

        elif t == "variable.clear":
            name = params.get("name", "").strip()
            context["vars"].pop(name, None)

        # ── HTTP ──────────────────────────────────────────────────────
        elif t == "http.request":
            method = params.get("method", "POST").upper()
            url = self._resolve_template(params.get("url", ""), context)
            body_str = self._resolve_template(params.get("body", ""), context)
            headers_str = params.get("headers", "")
            wait = params.get("wait", True)
            response_var = params.get("response_var", "").strip()

            def _do_request() -> None:
                try:
                    headers: dict = {}
                    if headers_str.strip():
                        headers = json.loads(headers_str)
                    body_bytes = body_str.encode() if body_str else None
                    if body_bytes and "Content-Type" not in headers:
                        headers["Content-Type"] = "application/json"
                    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
                    try:
                        import certifi
                        ctx = ssl.create_default_context(cafile=certifi.where())
                    except ImportError:
                        ctx = ssl.create_default_context()
                    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                        resp_body = resp.read().decode(errors="replace")
                        if response_var:
                            context["vars"][response_var] = resp_body
                except Exception as exc:
                    logger.warning("http.request failed: %s", exc)

            if wait:
                _do_request()
            else:
                threading.Thread(target=_do_request, daemon=True).start()

        # ── Notifications ─────────────────────────────────────────────
        elif t == "notify.desktop":
            title = self._resolve_template(params.get("title", "StreamShift"), context)
            message = self._resolve_template(params.get("message", ""), context)
            if sys.platform == "darwin":
                try:
                    subprocess.Popen([
                        "osascript", "-e",
                        f'display notification "{message}" with title "{title}"',
                    ])
                except Exception as exc:
                    logger.warning("notify.desktop: %s", exc)
            elif sys.platform == "win32":
                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(title, message, duration=5, threaded=True)
                except ImportError:
                    logger.info("notify.desktop: install win10toast for Windows notifications")
                except Exception as exc:
                    logger.warning("notify.desktop: %s", exc)
            else:
                logger.info("notify.desktop: unsupported platform %s", sys.platform)

        else:
            logger.debug("MacroEngine: unknown step type %r — skipping", t)

        return True

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------

    def _evaluate_predicate(self, predicate_type: str, predicate_value: str, context: dict) -> bool:
        if predicate_type == "always":
            return True

        if predicate_type == "stream.is_live":
            return self._get_is_live()

        if predicate_type == "stream.is_offline":
            return not self._get_is_live()

        if predicate_type == "viewer_count.gte":
            vc = self._get_viewer_count()
            if vc is None:
                return False
            try:
                return vc >= int(predicate_value)
            except (ValueError, TypeError):
                return False

        if predicate_type == "viewer_count.lte":
            vc = self._get_viewer_count()
            if vc is None:
                return False
            try:
                return vc <= int(predicate_value)
            except (ValueError, TypeError):
                return False

        if predicate_type == "time.between":
            # predicate_value = "HH:MM-HH:MM"
            try:
                parts = predicate_value.split("-")
                start_str, end_str = parts[0].strip(), parts[1].strip()
                import datetime
                now = datetime.datetime.now().time()
                start = datetime.time(*map(int, start_str.split(":")))
                end = datetime.time(*map(int, end_str.split(":")))
                if start <= end:
                    return start <= now <= end
                else:  # crosses midnight
                    return now >= start or now <= end
            except Exception:
                return False

        if predicate_type == "variable.equals":
            try:
                varname, value = predicate_value.split("=", 1)
                return context.get("vars", {}).get(varname.strip()) == value
            except Exception:
                return False

        if predicate_type == "variable.contains":
            try:
                varname, substring = predicate_value.split("=", 1)
                return substring in context.get("vars", {}).get(varname.strip(), "")
            except Exception:
                return False

        if predicate_type == "service.connected":
            try:
                plugin = self._get_plugin(predicate_value.strip())
                if plugin is None:
                    return False
                # Try common "connected" attributes
                for attr in ("connected", "is_connected", "_connected"):
                    val = getattr(plugin, attr, None)
                    if val is not None:
                        return bool(val)
                # If plugin exists and has no explicit connected attr, assume connected
                return True
            except Exception:
                return False

        logger.debug("_evaluate_predicate: unknown predicate_type %r — returning True", predicate_type)
        return True

    # ------------------------------------------------------------------
    # Stats helpers
    # ------------------------------------------------------------------

    def _get_stats_engine(self):
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("stream_stats")
            if lp and lp.instance:
                return getattr(lp.instance, "_engine", None)
        except Exception:
            pass
        return None

    def _get_is_live(self) -> bool:
        try:
            eng = self._get_stats_engine()
            if eng and hasattr(eng, "_current_stats"):
                return bool(eng._current_stats.is_live)
        except Exception:
            pass
        return False

    def _get_viewer_count(self) -> int | None:
        try:
            eng = self._get_stats_engine()
            if eng and hasattr(eng, "_current_stats"):
                return int(eng._current_stats.viewer_count)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # OBS client helper
    # ------------------------------------------------------------------

    def _get_obs_client(self):
        """Return the raw OBS WS client object from scene_manager or obs_studio."""
        try:
            plugin = self._get_plugin("scene_manager")
            if plugin and hasattr(plugin, "_client") and plugin._client:
                client = plugin._client
                # The client may wrap the obsws connection; try common attrs
                if hasattr(client, "call"):
                    return client
                inner = getattr(client, "_ws", None) or getattr(client, "_client", None)
                if inner and hasattr(inner, "call"):
                    return inner
        except Exception:
            pass
        try:
            plugin = self._get_plugin("obs_studio")
            if plugin:
                svc = getattr(plugin, "_service", None)
                if svc and hasattr(svc, "call"):
                    return svc
                inner = getattr(svc, "_ws", None) or getattr(svc, "_client", None)
                if inner and hasattr(inner, "call"):
                    return inner
        except Exception:
            pass
        logger.warning("obs_client: no connected OBS WS client found")
        return None

    # ------------------------------------------------------------------
    # Helix API helpers
    # ------------------------------------------------------------------

    def _get_bot_credentials(self):
        """Yield (client_id, token, channel) for each connected bot engine."""
        try:
            bp = self._get_plugin("bot_manager")
            if bp and hasattr(bp, "_engines"):
                for engine in (bp._engines or {}).values():
                    cfg = getattr(engine, "_config", None)
                    if not cfg:
                        continue
                    client_id = getattr(cfg, "twitch_client_id", None)
                    token = (getattr(cfg, "twitch_broadcaster_token", None)
                             or getattr(cfg, "twitch_oauth_token", None))
                    channel = getattr(cfg, "twitch_channel", None)
                    if client_id and token and channel:
                        yield client_id, token, channel
        except Exception as exc:
            logger.warning("_get_bot_credentials: %s", exc)

    def _helix_request(
        self,
        method: str,
        path: str,
        client_id: str,
        token: str,
        params_qs: str = "",
        body: dict | None = None,
    ) -> dict | None:
        """Low-level Helix API call. Returns parsed JSON or None on error."""
        url = f"https://api.twitch.tv/helix/{path}"
        if params_qs:
            url = f"{url}?{params_qs}"
        body_bytes = json.dumps(body).encode() if body else None
        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token.lstrip('oauth:')}",
        }
        if body_bytes:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                raw = resp.read()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")
            logger.warning("Helix %s %s -> %s %s", method, path, exc.code, body_text)
        except Exception as exc:
            logger.warning("Helix %s %s error: %s", method, path, exc)
        return None

    def _helix_get_user_id(self, login: str, client_id: str, token: str) -> str | None:
        data = self._helix_request("GET", "users", client_id, token, f"login={login}")
        try:
            return data["data"][0]["id"]
        except (TypeError, KeyError, IndexError):
            return None

    def _helix_announcement(self, message: str, color: str) -> None:
        def _run() -> None:
            for client_id, token, channel in self._get_bot_credentials():
                broadcaster_id = self._helix_get_user_id(channel, client_id, token)
                if not broadcaster_id:
                    continue
                qs = f"broadcaster_id={broadcaster_id}&moderator_id={broadcaster_id}"
                self._helix_request(
                    "POST", "chat/announcements", client_id, token,
                    params_qs=qs,
                    body={"message": message, "color": color},
                )
                break  # first working credential is enough

        threading.Thread(target=_run, daemon=True, name="helix-announcement").start()

    def _helix_shoutout(self, username: str) -> None:
        def _run() -> None:
            for client_id, token, channel in self._get_bot_credentials():
                from_id = self._helix_get_user_id(channel, client_id, token)
                to_id = self._helix_get_user_id(username, client_id, token)
                if not from_id or not to_id:
                    continue
                qs = (
                    f"from_broadcaster_id={from_id}"
                    f"&to_broadcaster_id={to_id}"
                    f"&moderator_id={from_id}"
                )
                self._helix_request("POST", "chat/shoutouts", client_id, token, params_qs=qs)
                break

        threading.Thread(target=_run, daemon=True, name="helix-shoutout").start()

    def _helix_timeout(self, username: str, duration_seconds: int, reason: str) -> None:
        def _run() -> None:
            for client_id, token, channel in self._get_bot_credentials():
                broadcaster_id = self._helix_get_user_id(channel, client_id, token)
                user_id = self._helix_get_user_id(username, client_id, token)
                if not broadcaster_id or not user_id:
                    continue
                qs = f"broadcaster_id={broadcaster_id}&moderator_id={broadcaster_id}"
                body: dict = {"data": {"user_id": user_id, "duration": duration_seconds}}
                if reason:
                    body["data"]["reason"] = reason
                self._helix_request("POST", "moderation/bans", client_id, token,
                                    params_qs=qs, body=body)
                break

        threading.Thread(target=_run, daemon=True, name="helix-timeout").start()

    # ------------------------------------------------------------------
    # Misc helpers (preserved from original)
    # ------------------------------------------------------------------

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
