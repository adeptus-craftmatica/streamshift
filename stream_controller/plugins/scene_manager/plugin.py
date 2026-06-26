from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.scene_manager.actions import ACTION_DEFINITIONS
from stream_controller.plugins.scene_manager.scene_client import SceneClient
from stream_controller.plugins.scene_manager.scene_models import SceneManagerState, ConnectionStatus
from stream_controller.plugins.scene_manager.scene_repository import SceneRepository
from stream_controller.plugins.scene_manager.overlay_server import SceneOverlayServer

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "scene_manager"


class SceneManagerPlugin:
    """Visual OBS scene switcher with real-time events and browser-source overlays."""

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo: SceneRepository | None = None
        self._client: SceneClient | None = None
        self._overlay: SceneOverlayServer | None = None
        self._page_widget = None
        self._dynamic_action_ids: set[str] = set()
        self._retry_timer: QTimer | None = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo   = SceneRepository(_DATA_DIR / "settings.json")
        self._client = SceneClient(on_state_changed=self._on_state_changed)
        self._overlay = SceneOverlayServer(self._client)
        self._overlay.start()

        self._register_actions(app_context)
        self._register_page(app_context)

        if self._repo.get("auto_connect"):
            self._client.connect(
                host=str(self._repo.get("host")),
                port=int(self._repo.get("port")),
                password=str(self._repo.get("password")),
            )
            self._start_retry_timer()

        app_context.set_status("Scene Manager loaded.", timeout_ms=3000)

    def unregister(self, app_context: AppContext) -> None:
        self._stop_retry_timer()
        if self._client:
            self._client.disconnect()
        if self._overlay:
            self._overlay.stop()
        for aid in list(self._dynamic_action_ids):
            try:
                app_context.unregister_action(aid)
            except Exception:
                pass
        self._dynamic_action_ids.clear()
        self._app_context = None

    def _start_retry_timer(self) -> None:
        if self._retry_timer is not None:
            return
        self._retry_timer = QTimer()
        self._retry_timer.setInterval(8000)
        self._retry_timer.timeout.connect(self._retry_connect)
        self._retry_timer.start()

    def _stop_retry_timer(self) -> None:
        if self._retry_timer:
            self._retry_timer.stop()
            self._retry_timer = None

    def _retry_connect(self) -> None:
        if not self._client or not self._repo:
            return
        status = self._client.state.status
        if status == ConnectionStatus.CONNECTED:
            self._stop_retry_timer()
            return
        if status == ConnectionStatus.CONNECTING:
            return
        self._client.connect(
            host=str(self._repo.get("host")),
            port=int(self._repo.get("port")),
            password=str(self._repo.get("password")),
        )

    # ── actions ───────────────────────────────────────────────────────────────

    def _register_actions(self, app_context: AppContext) -> None:
        handlers = {
            "scene.open_panel": self._open_panel,
            "scene.refresh":    lambda: self._client.refresh() if self._client else None,
        }
        for defn in ACTION_DEFINITIONS:
            aid     = defn["action_id"]
            factory = self._make_scene_tile if aid == "scene.scene_tile" else None
            app_context.register_action(
                action_id=aid,
                title=defn["title"],
                description=defn["description"],
                execute=handlers.get(aid, lambda: None),
                icon=defn.get("icon", "SC"),
                page=defn.get("page", "Scene Manager"),
                group=defn.get("group", "Scene Manager"),
                default_shortcut=defn.get("default_shortcut"),
                widget_factory=factory,
            )

    def _plugin_id(self) -> str:
        manifest = getattr(self, "manifest", None)
        if manifest is None:
            raise RuntimeError("Plugin manifest has not been attached yet.")
        return str(manifest.plugin_id)

    def _sync_scene_actions(self, state: SceneManagerState) -> None:
        """Dynamically register one deck action per OBS scene."""
        if self._app_context is None:
            return

        try:
            pid = self._plugin_id()
        except RuntimeError:
            return

        new_ids: set[str] = set()
        for scene in state.scenes:
            if scene.is_group or not scene.name:
                continue
            aid = f"scene.switch.{scene.name}"
            new_ids.add(aid)
            if aid not in self._dynamic_action_ids:
                name = scene.name
                self._app_context.register_action(
                    action_id=aid,
                    title=scene.name,
                    description=f"Switch OBS to '{scene.name}'.",
                    execute=lambda n=name: self._client.switch_scene(n) if self._client else None,
                    icon="▶",
                    page="Scenes",
                    group="Switch Scene",
                    plugin_id=pid,
                )

        # Remove stale scene actions
        for old_aid in self._dynamic_action_ids - new_ids:
            try:
                self._app_context.unregister_action(old_aid)
            except Exception:
                pass
        self._dynamic_action_ids = new_ids

    # ── state callback (Qt main thread) ──────────────────────────────────────

    def _on_state_changed(self, state: SceneManagerState) -> None:
        if state.status == ConnectionStatus.CONNECTED:
            self._sync_scene_actions(state)
        if self._page_widget:
            try:
                self._page_widget.on_state_changed(state)
            except RuntimeError:
                pass

    # ── page ──────────────────────────────────────────────────────────────────

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.scene_manager.ui.scene_page import ScenePage
        overlay_url = self._overlay.base_url if self._overlay else ""
        self._page_widget = ScenePage(
            client=self._client,
            repo=self._repo,
            overlay_base_url=overlay_url,
        )
        app_context.register_plugin_page(
            page_id="scene_manager",
            title="Scene Manager",
            subtitle="Visual OBS scene switcher with real-time updates and browser-source overlays.",
            widget=self._page_widget,
            help_text=(
                "<h3>Scene Manager</h3>"
                "<p>Scene Manager gives you a visual overview of your OBS scenes and lets you switch "
                "between them in real time from within StreamShift.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Enter your OBS WebSocket connection details (host, port, password) in the Scene Manager settings.</li>"
                "<li>Click <b>Connect</b> — your OBS scenes will appear as clickable tiles.</li>"
                "</ol>"
                "<h4>Switching scenes</h4>"
                "<p>Click any scene tile to switch to it in OBS immediately. The currently active scene "
                "is highlighted. Changes in OBS are reflected here in real time.</p>"
                "<h4>Scene overlay for OBS</h4>"
                "<p>Scene Manager includes a browser-source overlay showing the current scene name. "
                "Copy the URL from the Scene Manager page and add it as a browser source in OBS.</p>"
                "<h4>Using in macros</h4>"
                "<p>Add a <b>Switch Scene</b> step to a macro to automatically change scenes as part "
                "of a workflow — for example, switching to a Starting Soon scene when your macro runs.</p>"
            ),
        )
        app_context.register_stage_widget(
            panel_id="scene.main",
            title="Scene Manager",
            icon="🎬",
            factory=lambda: __import__(
                'stream_controller.plugins.scene_manager.ui.scene_tile',
                fromlist=['SceneTile']
            ).SceneTile(self._client),
        )
        from stream_controller.plugins.scene_manager.ui.scene_tile import SceneTile
        app_context.register_dashboard_panel(
            title="",
            description="",
            widget=SceneTile(self._client),
        )

    def _make_scene_tile(self):
        from stream_controller.plugins.scene_manager.ui.scene_tile import SceneTile
        return SceneTile(self._client)

    def _open_panel(self) -> None:
        if self._app_context:
            self._app_context.show_page("scene_manager")
