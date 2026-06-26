from __future__ import annotations

import hashlib
from typing import Any, Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from stream_controller.core.app_context import AppContext
from stream_controller.ui.theme import create_badge, create_card
from stream_controller.plugins.obs_studio.obs_service import (
    ObsAudioInputInfo,
    ObsConnectionConfig,
    ObsOverlaySourceInfo,
    ObsSceneInfo,
    ObsServiceError,
    ObsSnapshot,
    ObsStudioService,
)


class OBSStudioPlugin:
    SETUP_PAGE = "OBS Setup"
    SCENES_PAGE = "Scenes"
    AUDIO_PAGE = "Audio"
    OVERLAYS_PAGE = "Overlays"
    OUTPUTS_PAGE = "Outputs"

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._service = ObsStudioService()
        self._snapshot: ObsSnapshot | None = None
        self._last_error: str | None = None
        self._dynamic_action_ids: set[str] = set()
        self._dynamic_action_signature: str | None = None
        self._registered_commands: list[str] = []
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(lambda: self._refresh_snapshot(notify=False, user_initiated=False))

        self._page_connection_label: QLabel | None = None
        self._page_scene_label: QLabel | None = None
        self._page_audio_label: QLabel | None = None
        self._page_overlay_label: QLabel | None = None
        self._page_output_label: QLabel | None = None
        self._page_error_label: QLabel | None = None
        self._page_actions_label: QLabel | None = None
        self._page_connect_button: QPushButton | None = None
        self._page_disconnect_button: QPushButton | None = None
        self._page_refresh_button: QPushButton | None = None

        self._dashboard_status_label: QLabel | None = None
        self._dashboard_scene_label: QLabel | None = None
        self._dashboard_output_label: QLabel | None = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context

        self._register_settings(app_context)
        self._register_commands(app_context)
        self._register_static_actions(app_context)

        app_context.event_bus.subscribe("app.started", self._on_app_started)
        app_context.event_bus.subscribe("plugin.settings.changed", self._on_plugin_settings_changed)
        app_context.event_bus.subscribe("plugin.settings.reset", self._on_plugin_settings_reset)

        app_context.register_plugin_page(
            page_id="obs_studio",
            title="OBS Studio",
            subtitle="Live OBS connection, scenes, inputs, overlays, and outputs from one plugin workspace.",
            widget=self._build_plugin_page(),
            help_text=(
                "<h3>OBS Studio</h3>"
                "<p>This plugin connects StreamShift to OBS Studio via the OBS WebSocket protocol, "
                "giving you control over scenes, audio inputs, and streaming directly from the app.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>In OBS, go to <b>Tools → WebSocket Server Settings</b> and enable the server.</li>"
                "<li>Note the port (default 4455) and set a password if desired.</li>"
                "<li>In StreamShift's OBS Studio settings, enter the host (<code>localhost</code>), port, and password.</li>"
                "<li>Click <b>Connect</b> (or use Quick Connect).</li>"
                "</ol>"
                "<h4>What you can do</h4>"
                "<ul>"
                "<li>Switch scenes, mute/unmute audio inputs, and toggle source visibility.</li>"
                "<li>Start and stop streaming via the <b>Go Live</b> / <b>End Stream</b> macro steps.</li>"
                "<li>OBS scene actions are automatically registered and available as macro steps once connected.</li>"
                "</ul>"
            ),
        )
        app_context.register_dashboard_panel(
            title="OBS Studio",
            description="Monitor your live OBS connection and jump into stream controls quickly.",
            widget=self._build_dashboard_panel(),
        )

        self._update_ui()

        if app_context.app_started:
            self._on_app_started(app_context.runtime_snapshot())

    def unregister(self, app_context: AppContext) -> None:
        app_context.event_bus.unsubscribe("app.started", self._on_app_started)
        app_context.event_bus.unsubscribe("plugin.settings.changed", self._on_plugin_settings_changed)
        app_context.event_bus.unsubscribe("plugin.settings.reset", self._on_plugin_settings_reset)

        for command_name in self._registered_commands:
            try:
                app_context.command_registry.unregister(command_name)
            except KeyError:
                pass
        self._registered_commands.clear()

        self._poll_timer.stop()
        self._clear_dynamic_actions()
        self._service.disconnect()

        self._app_context = None
        self._snapshot = None
        self._last_error = None

    def connect(self) -> bool:
        return self._connect_and_refresh(notify=True, force_reconnect=False)

    def disconnect(self) -> None:
        self._disconnect(notify=True)

    def refresh_state(self) -> bool:
        return self._refresh_snapshot(notify=True, user_initiated=True)

    def set_program_scene(self, scene_name: str) -> str:
        self._service.set_current_program_scene(scene_name)
        self._refresh_snapshot(notify=False, user_initiated=False)
        self._set_status(f"OBS scene switched to '{scene_name}'.", timeout_ms=2500)
        return scene_name

    def toggle_input_mute(self, input_name: str) -> bool:
        muted = self._service.toggle_input_mute(input_name)
        self._refresh_snapshot(notify=False, user_initiated=False)
        state = "muted" if muted else "live"
        self._set_status(f"OBS input '{input_name}' is now {state}.", timeout_ms=2500)
        return muted

    def toggle_source_visibility(self, source_name: str, scene_name: str | None = None) -> bool:
        overlay = self._resolve_overlay(source_name, scene_name)
        if overlay.scene_item_id is None:
            raise ObsServiceError(f"Overlay source '{source_name}' is not available in OBS.")

        enabled = self._service.toggle_scene_item_enabled(overlay.scene_name, overlay.scene_item_id)
        self._refresh_snapshot(notify=False, user_initiated=False)
        state = "visible" if enabled else "hidden"
        self._set_status(f"OBS source '{source_name}' is now {state}.", timeout_ms=2500)
        return enabled

    def toggle_stream(self) -> bool:
        active = self._service.toggle_stream()
        self._refresh_snapshot(notify=False, user_initiated=False)
        state = "live" if active else "stopped"
        self._set_status(f"OBS stream is now {state}.", timeout_ms=2500)
        return active

    def toggle_record(self) -> bool:
        active = self._service.toggle_record()
        self._refresh_snapshot(notify=False, user_initiated=False)
        state = "recording" if active else "stopped"
        self._set_status(f"OBS recording is now {state}.", timeout_ms=2500)
        return active

    def _register_settings(self, app_context: AppContext) -> None:
        app_context.register_setting(
            setting_key="host",
            label="OBS Host",
            field_type="text",
            description="Hostname or IP address for the OBS websocket server.",
            default="localhost",
            placeholder="localhost",
            required=True,
            validator=self._validate_host,
        )
        app_context.register_setting(
            setting_key="port",
            label="OBS Port",
            field_type="number",
            description="Websocket port exposed by OBS Studio.",
            default=4455,
            minimum=1,
            maximum=65535,
            step=1,
        )
        app_context.register_setting(
            setting_key="password",
            label="OBS Password",
            field_type="secret",
            description="Password configured in OBS under Tools > WebSocket Server Settings.",
            default="",
            placeholder="Optional",
        )
        app_context.register_setting(
            setting_key="timeout_seconds",
            label="Connection Timeout",
            field_type="number",
            description="How long OBS requests can take before the plugin treats the connection as failed.",
            default=3,
            minimum=1,
            maximum=15,
            step=1,
        )
        app_context.register_setting(
            setting_key="auto_connect",
            label="Auto Connect",
            field_type="toggle",
            description="Automatically try to connect to OBS when the app finishes launching.",
            default=True,
        )
        app_context.register_setting(
            setting_key="refresh_interval_seconds",
            label="Refresh Interval",
            field_type="number",
            description="Background refresh cadence for OBS status. Set to 0 to disable polling.",
            default=5,
            minimum=0,
            maximum=60,
            step=1,
        )
        app_context.register_setting(
            setting_key="additional_audio_inputs",
            label="Additional Audio Inputs",
            field_type="text",
            description="Optional comma or line-separated OBS input names to include on the Audio deck page.",
            default="",
            placeholder="Music, Discord",
        )
        app_context.register_setting(
            setting_key="overlay_scene_name",
            label="Overlay Scene",
            field_type="text",
            description="Scene used for overlay source toggles. Leave blank to target the current program scene.",
            default="",
            placeholder="Leave blank to use the active scene",
        )
        app_context.register_setting(
            setting_key="overlay_sources",
            label="Overlay Sources",
            field_type="text",
            description="Comma or line-separated scene item source names to expose on the Overlays deck page.",
            default="",
            placeholder="Sponsor Lower Third, Chat Frame",
        )

    def _register_commands(self, app_context: AppContext) -> None:
        command_map: dict[str, Callable[..., Any]] = {
            "obs.connect": self.connect,
            "obs.disconnect": self.disconnect,
            "obs.refresh_state": self.refresh_state,
            "obs.set_program_scene": self.set_program_scene,
            "obs.toggle_input_mute": self.toggle_input_mute,
            "obs.toggle_source_visibility": self.toggle_source_visibility,
            "obs.toggle_stream": self.toggle_stream,
            "obs.toggle_record": self.toggle_record,
        }
        for command_name, handler in command_map.items():
            app_context.command_registry.register(command_name, handler)
            self._registered_commands.append(command_name)

    def _register_static_actions(self, app_context: AppContext) -> None:
        plugin_id = self._plugin_id()
        app_context.register_action(
            action_id="obs.connect",
            title="Connect OBS",
            description="Connect to the configured OBS Studio websocket server.",
            execute=self.connect,
            icon="OB",
            page=self.SETUP_PAGE,
            group="Connection",
            enabled=self._can_connect,
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.disconnect",
            title="Disconnect OBS",
            description="Disconnect from OBS Studio and remove live OBS deck actions.",
            execute=self.disconnect,
            icon="OF",
            page=self.SETUP_PAGE,
            group="Connection",
            enabled=self._can_disconnect,
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.refresh",
            title="Refresh OBS State",
            description="Pull the latest scenes, inputs, overlays, and output state from OBS Studio.",
            execute=self.refresh_state,
            icon="RF",
            page=self.SETUP_PAGE,
            group="Connection",
            enabled=self._is_connected,
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.open_workspace",
            title="Open OBS Workspace",
            description="Jump to the OBS Studio plugin workspace for connection details and live status.",
            execute=self._open_workspace,
            icon="WS",
            page=self.SETUP_PAGE,
            group="Navigation",
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.open_scenes_page",
            title="Open Scenes Deck",
            description="Open the Scenes deck page to switch OBS program scenes quickly.",
            execute=lambda: self._open_deck_page(self.SCENES_PAGE),
            icon="SC",
            page=self.SETUP_PAGE,
            group="Navigation",
            enabled=lambda: bool(self._snapshot and self._snapshot.scenes),
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.toggle_stream",
            title="Toggle Stream",
            description="Start or stop the OBS stream output.",
            execute=self.toggle_stream,
            icon="ST",
            page=self.OUTPUTS_PAGE,
            group="Broadcast",
            enabled=self._is_connected,
            plugin_id=plugin_id,
        )
        app_context.register_action(
            action_id="obs.toggle_record",
            title="Toggle Recording",
            description="Start or stop the OBS recording output.",
            execute=self.toggle_record,
            icon="RC",
            page=self.OUTPUTS_PAGE,
            group="Broadcast",
            enabled=self._is_connected,
            plugin_id=plugin_id,
        )

    def _build_plugin_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        overview_card, overview_body = create_card(
            "OBS Studio",
            "This plugin speaks to a real OBS websocket server so the control deck can drive scenes, audio, overlays, and output state.",
        )
        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)
        badges_row.addWidget(create_badge("Real Integration", "success"))
        badges_row.addWidget(create_badge("Plugin Local Logic", "accent"))
        badges_row.addStretch(1)

        self._page_connection_label = QLabel()
        self._page_connection_label.setObjectName("MetaText")
        self._page_connection_label.setWordWrap(True)

        self._page_error_label = QLabel()
        self._page_error_label.setObjectName("MetaText")
        self._page_error_label.setWordWrap(True)

        overview_body.addLayout(badges_row)
        overview_body.addWidget(self._page_connection_label)
        overview_body.addWidget(self._page_error_label)

        actions_card, actions_body = create_card(
            "Connection Controls",
            "Use these controls to connect, disconnect, refresh state, or jump directly into the deck pages this plugin creates.",
        )
        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        self._page_connect_button = QPushButton("Connect OBS")
        self._page_connect_button.setObjectName("PrimaryButton")
        self._page_connect_button.clicked.connect(self.connect)

        self._page_disconnect_button = QPushButton("Disconnect")
        self._page_disconnect_button.setObjectName("SecondaryButton")
        self._page_disconnect_button.clicked.connect(self.disconnect)

        self._page_refresh_button = QPushButton("Refresh")
        self._page_refresh_button.setObjectName("SecondaryButton")
        self._page_refresh_button.clicked.connect(self.refresh_state)

        open_scenes_button = QPushButton("Open Scenes Deck")
        open_scenes_button.setObjectName("SecondaryButton")
        open_scenes_button.clicked.connect(lambda: self._open_deck_page(self.SCENES_PAGE))

        open_audio_button = QPushButton("Open Audio Deck")
        open_audio_button.setObjectName("SecondaryButton")
        open_audio_button.clicked.connect(lambda: self._open_deck_page(self.AUDIO_PAGE))

        open_overlays_button = QPushButton("Open Overlays Deck")
        open_overlays_button.setObjectName("SecondaryButton")
        open_overlays_button.clicked.connect(lambda: self._open_deck_page(self.OVERLAYS_PAGE))

        outputs_button = QPushButton("Open Outputs Deck")
        outputs_button.setObjectName("SecondaryButton")
        outputs_button.clicked.connect(lambda: self._open_deck_page(self.OUTPUTS_PAGE))

        button_row.addWidget(self._page_connect_button)
        button_row.addWidget(self._page_disconnect_button)
        button_row.addWidget(self._page_refresh_button)
        actions_body.addLayout(button_row)

        deck_row = QHBoxLayout()
        deck_row.setSpacing(12)
        deck_row.addWidget(open_scenes_button)
        deck_row.addWidget(open_audio_button)
        deck_row.addWidget(open_overlays_button)
        deck_row.addWidget(outputs_button)
        deck_row.addStretch(1)
        actions_body.addLayout(deck_row)

        self._page_actions_label = QLabel()
        self._page_actions_label.setObjectName("MetaText")
        self._page_actions_label.setWordWrap(True)
        actions_body.addWidget(self._page_actions_label)

        snapshot_card, snapshot_body = create_card(
            "Live Snapshot",
            "These summaries refresh from OBS so you can confirm what the deck is targeting before you press anything important.",
        )
        self._page_scene_label = QLabel()
        self._page_scene_label.setObjectName("MetaText")
        self._page_scene_label.setWordWrap(True)

        self._page_audio_label = QLabel()
        self._page_audio_label.setObjectName("MetaText")
        self._page_audio_label.setWordWrap(True)

        self._page_overlay_label = QLabel()
        self._page_overlay_label.setObjectName("MetaText")
        self._page_overlay_label.setWordWrap(True)

        self._page_output_label = QLabel()
        self._page_output_label.setObjectName("MetaText")
        self._page_output_label.setWordWrap(True)

        snapshot_body.addWidget(self._page_scene_label)
        snapshot_body.addWidget(self._page_audio_label)
        snapshot_body.addWidget(self._page_overlay_label)
        snapshot_body.addWidget(self._page_output_label)

        layout.addWidget(overview_card)
        layout.addWidget(actions_card)
        layout.addWidget(snapshot_card)
        layout.addStretch(1)
        return page

    def _build_dashboard_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._dashboard_status_label = QLabel()
        self._dashboard_status_label.setObjectName("CardDescription")
        self._dashboard_status_label.setWordWrap(True)

        self._dashboard_scene_label = QLabel()
        self._dashboard_scene_label.setObjectName("MetaText")
        self._dashboard_scene_label.setWordWrap(True)

        self._dashboard_output_label = QLabel()
        self._dashboard_output_label.setObjectName("MetaText")
        self._dashboard_output_label.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        connect_button = QPushButton("Connect")
        connect_button.setObjectName("SecondaryButton")
        connect_button.clicked.connect(self.connect)

        scenes_button = QPushButton("Scenes Deck")
        scenes_button.setObjectName("SecondaryButton")
        scenes_button.clicked.connect(lambda: self._open_deck_page(self.SCENES_PAGE))

        button_row.addWidget(connect_button)
        button_row.addWidget(scenes_button)
        button_row.addStretch(1)

        layout.addWidget(self._dashboard_status_label)
        layout.addWidget(self._dashboard_scene_label)
        layout.addWidget(self._dashboard_output_label)
        layout.addLayout(button_row)
        return panel

    def _on_app_started(self, payload: Any) -> None:
        if self._setting_bool("auto_connect", True):
            self._connect_and_refresh(notify=True, force_reconnect=False)
        else:
            self._update_ui()

    def _on_plugin_settings_changed(self, payload: Any) -> None:
        if not isinstance(payload, dict) or payload.get("plugin_id") != self._plugin_id():
            return

        values = payload.get("values")
        if not isinstance(values, dict):
            return

        previous_config = self._service.config
        next_config = self._connection_config()
        if self._service.is_connected and previous_config != next_config:
            self._connect_and_refresh(notify=True, force_reconnect=True)
            return

        self._configure_polling()
        if self._service.is_connected:
            self._refresh_snapshot(notify=False, user_initiated=False)
        elif self._setting_bool("auto_connect", True):
            self._connect_and_refresh(notify=True, force_reconnect=False)
        else:
            self._update_ui()

    def _on_plugin_settings_reset(self, payload: Any) -> None:
        if not isinstance(payload, dict) or payload.get("plugin_id") != self._plugin_id():
            return
        self._disconnect(notify=False)
        if self._setting_bool("auto_connect", True):
            self._connect_and_refresh(notify=True, force_reconnect=False)
        else:
            self._update_ui()

    def _connect_and_refresh(self, *, notify: bool, force_reconnect: bool) -> bool:
        if self._app_context is None:
            return False

        if force_reconnect:
            self._service.disconnect()
            self._snapshot = None

        if not self._service.is_connected:
            try:
                version_info = self._service.connect(self._connection_config())
                version_text = f"Connected to OBS {version_info.get('obs_version', '')}".strip()
                self._last_error = None
                self._configure_polling()
                self._emit_connection_event()
                if notify:
                    self._set_status(version_text or "Connected to OBS Studio.", timeout_ms=3000)
            except ObsServiceError as exc:
                self._last_error = str(exc)
                self._disconnect(notify=False)
                self._update_ui()
                if notify:
                    self._set_status(f"Could not connect to OBS: {exc}", timeout_ms=5000)
                return False

        return self._refresh_snapshot(notify=notify, user_initiated=False)

    def _disconnect(self, *, notify: bool) -> None:
        self._poll_timer.stop()
        self._service.disconnect()
        self._snapshot = None
        self._clear_dynamic_actions()
        self._emit_connection_event()
        self._update_ui()
        if self._app_context is not None:
            self._app_context.refresh_action_state()
        if notify:
            self._set_status("Disconnected from OBS Studio.", timeout_ms=3000)

    def _refresh_snapshot(self, *, notify: bool, user_initiated: bool) -> bool:
        if self._app_context is None:
            return False
        if not self._service.is_connected:
            self._update_ui()
            if notify:
                self._set_status("OBS Studio is not connected.", timeout_ms=4000)
            return False

        try:
            previous_snapshot = self._snapshot
            self._snapshot = self._service.fetch_snapshot(
                additional_audio_inputs=self._parsed_list_setting("additional_audio_inputs"),
                overlay_scene_name=self._string_setting("overlay_scene_name") or None,
                overlay_sources=self._parsed_list_setting("overlay_sources"),
            )
            self._last_error = None
        except ObsServiceError as exc:
            self._last_error = str(exc)
            self._disconnect(notify=False)
            if notify:
                self._set_status(f"Could not refresh OBS: {exc}", timeout_ms=5000)
            return False

        connection_transition = previous_snapshot is None
        actions_changed = self._rebuild_dynamic_actions()
        self._emit_snapshot_event()
        self._update_ui()
        if actions_changed or connection_transition:
            self._app_context.refresh_action_state()
        if notify:
            message = "OBS state refreshed." if user_initiated else "OBS connected and ready."
            self._set_status(message, timeout_ms=2500)
        return True

    def _rebuild_dynamic_actions(self) -> bool:
        if self._app_context is None:
            return False

        if self._snapshot is None:
            self._clear_dynamic_actions()
            return False

        next_signature = self._build_dynamic_action_signature(self._snapshot)
        if next_signature == self._dynamic_action_signature:
            return False

        self._clear_dynamic_actions()
        self._dynamic_action_signature = next_signature

        plugin_id = self._plugin_id()

        for scene in self._snapshot.scenes:
            if scene.is_group or not scene.name:
                continue
            action_id = self._action_id("scene", scene.name)
            self._app_context.register_action(
                action_id=action_id,
                title=scene.name,
                description=f"Switch OBS to the '{scene.name}' program scene.",
                execute=lambda scene_name=scene.name: self.set_program_scene(scene_name),
                icon="SC",
                page=self.SCENES_PAGE,
                group="Program Scenes",
                plugin_id=plugin_id,
            )
            self._dynamic_action_ids.add(action_id)

        for audio_input in self._snapshot.audio_inputs:
            state_text = "currently muted" if audio_input.muted else "currently live"
            action_id = self._action_id("audio", audio_input.name)
            self._app_context.register_action(
                action_id=action_id,
                title=audio_input.name,
                description=f"Toggle mute for '{audio_input.name}' in OBS. It is {state_text}.",
                execute=lambda input_name=audio_input.name: self.toggle_input_mute(input_name),
                icon="AU",
                page=self.AUDIO_PAGE,
                group="Audio Inputs",
                plugin_id=plugin_id,
            )
            self._dynamic_action_ids.add(action_id)

        for overlay in self._snapshot.overlay_sources:
            if not overlay.available or overlay.scene_item_id is None:
                continue
            action_id = self._action_id("overlay", f"{overlay.scene_name}:{overlay.source_name}")
            state_text = "currently visible" if overlay.enabled else "currently hidden"
            self._app_context.register_action(
                action_id=action_id,
                title=overlay.source_name,
                description=(
                    f"Toggle '{overlay.source_name}' in scene '{overlay.scene_name}'. "
                    f"It is {state_text}."
                ),
                execute=lambda source_name=overlay.source_name, scene_name=overlay.scene_name: self.toggle_source_visibility(
                    source_name,
                    scene_name,
                ),
                icon="OV",
                page=self.OVERLAYS_PAGE,
                group=overlay.scene_name,
                plugin_id=plugin_id,
            )
            self._dynamic_action_ids.add(action_id)
        return True

    def _clear_dynamic_actions(self) -> None:
        if self._app_context is None:
            self._dynamic_action_ids.clear()
            self._dynamic_action_signature = None
            return

        for action_id in list(self._dynamic_action_ids):
            try:
                self._app_context.action_registry.unregister(action_id)
            except KeyError:
                pass
        self._dynamic_action_ids.clear()
        self._dynamic_action_signature = None

    @staticmethod
    def _build_dynamic_action_signature(snapshot: ObsSnapshot) -> str:
        payload = [
            ("scene", scene.name, scene.is_group)
            for scene in snapshot.scenes
        ]
        payload.extend(
            ("audio", item.name)
            for item in snapshot.audio_inputs
        )
        payload.extend(
            ("overlay", overlay.scene_name, overlay.source_name, overlay.available, overlay.scene_item_id)
            for overlay in snapshot.overlay_sources
        )
        return repr(payload)

    def _configure_polling(self) -> None:
        interval_seconds = max(0, self._setting_int("refresh_interval_seconds", 5))
        if not self._service.is_connected or interval_seconds <= 0:
            self._poll_timer.stop()
            return

        self._poll_timer.setInterval(interval_seconds * 1000)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _resolve_overlay(self, source_name: str, scene_name: str | None) -> ObsOverlaySourceInfo:
        snapshot = self._snapshot
        if snapshot is None:
            raise ObsServiceError("OBS state has not been loaded yet.")

        target_scene_name = scene_name or self._string_setting("overlay_scene_name") or snapshot.current_scene_name
        for overlay in snapshot.overlay_sources:
            if overlay.source_name == source_name and overlay.scene_name == target_scene_name:
                return overlay

        raise ObsServiceError(f"Overlay source '{source_name}' is not available in scene '{target_scene_name}'.")

    def _build_connection_summary(self) -> str:
        config = self._connection_config()
        if self._service.is_connected and self._snapshot is not None:
            return (
                f"Connected to {config.host}:{config.port}. "
                f"OBS {self._snapshot.obs_version or 'Unknown'} • "
                f"WebSocket {self._snapshot.websocket_version or 'Unknown'}."
            )
        if self._last_error:
            return f"Connection ready for {config.host}:{config.port}, but the last attempt failed."
        return f"Ready to connect to {config.host}:{config.port}."

    def _build_actions_summary(self) -> str:
        pages: list[str] = [self.SETUP_PAGE, self.OUTPUTS_PAGE]
        if self._snapshot and self._snapshot.scenes:
            pages.append(self.SCENES_PAGE)
        if self._snapshot and self._snapshot.audio_inputs:
            pages.append(self.AUDIO_PAGE)
        if self._snapshot and any(item.available for item in self._snapshot.overlay_sources):
            pages.append(self.OVERLAYS_PAGE)
        return "Active deck pages: " + ", ".join(pages) + "."

    def _build_scene_summary(self) -> str:
        if self._snapshot is None:
            return "Scenes: Connect to OBS to discover available program scenes."
        scene_names = [scene.name for scene in self._snapshot.scenes if not scene.is_group and scene.name]
        if not scene_names:
            return "Scenes: OBS is connected, but no switchable scenes were returned."
        return (
            f"Current scene: {self._snapshot.current_scene_name or 'Unknown'}. "
            f"Available scenes: {', '.join(scene_names[:6])}"
            + (" ..." if len(scene_names) > 6 else "")
        )

    def _build_audio_summary(self) -> str:
        if self._snapshot is None:
            return "Audio: OBS audio inputs will appear here after a successful connection."
        if not self._snapshot.audio_inputs:
            return "Audio: No special or configured inputs are currently available."

        parts = [
            f"{item.name} ({'Muted' if item.muted else 'Live'})"
            for item in self._snapshot.audio_inputs
        ]
        return "Audio inputs: " + ", ".join(parts[:6]) + (" ..." if len(parts) > 6 else "")

    def _build_overlay_summary(self) -> str:
        configured_sources = self._parsed_list_setting("overlay_sources")
        if self._snapshot is None:
            if configured_sources:
                return "Overlays: Configure a scene and connect to OBS to expose overlay visibility actions."
            return "Overlays: Add source names in Settings to create overlay visibility actions."

        if not configured_sources:
            return "Overlays: Add source names in Settings to create overlay visibility actions."

        if not self._snapshot.overlay_sources:
            return "Overlays: No configured overlay sources were resolved from OBS."

        parts = []
        for overlay in self._snapshot.overlay_sources:
            if overlay.available:
                parts.append(f"{overlay.source_name} ({'Visible' if overlay.enabled else 'Hidden'})")
            else:
                parts.append(f"{overlay.source_name} (Missing)")
        return "Overlay sources: " + ", ".join(parts[:6]) + (" ..." if len(parts) > 6 else "")

    def _build_output_summary(self) -> str:
        if self._snapshot is None:
            return "Outputs: Stream and recording status will appear here after OBS connects."

        stream_state = "Live" if self._snapshot.stream_active else "Idle"
        if self._snapshot.stream_active and self._snapshot.stream_timecode:
            stream_state += f" ({self._snapshot.stream_timecode})"
        if self._snapshot.stream_reconnecting:
            stream_state += " reconnecting"

        record_state = "Recording" if self._snapshot.record_active else "Idle"
        if self._snapshot.record_active and self._snapshot.record_timecode:
            record_state += f" ({self._snapshot.record_timecode})"
        if self._snapshot.record_paused:
            record_state += " paused"

        return f"Outputs: Stream {stream_state} • Record {record_state}"

    def _update_ui(self) -> None:
        connected = self._service.is_connected

        if self._page_connection_label is not None:
            self._page_connection_label.setText(self._build_connection_summary())
        if self._page_scene_label is not None:
            self._page_scene_label.setText(self._build_scene_summary())
        if self._page_audio_label is not None:
            self._page_audio_label.setText(self._build_audio_summary())
        if self._page_overlay_label is not None:
            self._page_overlay_label.setText(self._build_overlay_summary())
        if self._page_output_label is not None:
            self._page_output_label.setText(self._build_output_summary())
        if self._page_actions_label is not None:
            self._page_actions_label.setText(self._build_actions_summary())
        if self._page_error_label is not None:
            self._page_error_label.setText(self._last_error or "")
            self._page_error_label.setVisible(bool(self._last_error))
        if self._page_connect_button is not None:
            self._page_connect_button.setEnabled(not connected)
        if self._page_disconnect_button is not None:
            self._page_disconnect_button.setEnabled(connected)
        if self._page_refresh_button is not None:
            self._page_refresh_button.setEnabled(connected)

        if self._dashboard_status_label is not None:
            self._dashboard_status_label.setText(
                "OBS connected and ready." if connected else "OBS is disconnected."
            )
        if self._dashboard_scene_label is not None:
            self._dashboard_scene_label.setText(self._build_scene_summary())
        if self._dashboard_output_label is not None:
            self._dashboard_output_label.setText(self._build_output_summary())

    def _emit_connection_event(self) -> None:
        if self._app_context is None:
            return

        config = self._connection_config()
        self._app_context.event_bus.emit(
            "obs.connection.changed",
            {
                "connected": self._service.is_connected,
                "host": config.host,
                "port": config.port,
                "current_scene": self._snapshot.current_scene_name if self._snapshot is not None else "",
            },
        )

    def _emit_snapshot_event(self) -> None:
        if self._app_context is None or self._snapshot is None:
            return

        self._app_context.event_bus.emit(
            "obs.snapshot.updated",
            {
                "connected": self._service.is_connected,
                "current_scene": self._snapshot.current_scene_name,
                "scene_count": len(self._snapshot.scenes),
                "audio_input_count": len(self._snapshot.audio_inputs),
                "overlay_count": len([item for item in self._snapshot.overlay_sources if item.available]),
                "stream_active": self._snapshot.stream_active,
                "record_active": self._snapshot.record_active,
            },
        )

    def _open_workspace(self) -> None:
        if self._app_context is None:
            return
        self._app_context.show_page("obs_studio")

    def _plugin_id(self) -> str:
        manifest = getattr(self, "manifest", None)
        if manifest is None:
            raise RuntimeError("Plugin manifest has not been attached yet.")
        return str(manifest.plugin_id)

    def _connection_config(self) -> ObsConnectionConfig:
        return ObsConnectionConfig(
            host=self._string_setting("host", "localhost") or "localhost",
            port=max(1, self._setting_int("port", 4455)),
            password=self._string_setting("password", ""),
            timeout_seconds=max(1, self._setting_int("timeout_seconds", 3)),
        )

    def _setting(self, setting_key: str, default: Any = None) -> Any:
        if self._app_context is None:
            return default
        return self._app_context.get_setting(self._plugin_id(), setting_key, default)

    def _string_setting(self, setting_key: str, default: str = "") -> str:
        return str(self._setting(setting_key, default)).strip()

    def _setting_int(self, setting_key: str, default: int) -> int:
        try:
            return int(self._setting(setting_key, default))
        except (TypeError, ValueError):
            return default

    def _setting_bool(self, setting_key: str, default: bool) -> bool:
        return bool(self._setting(setting_key, default))

    def _parsed_list_setting(self, setting_key: str) -> list[str]:
        raw_value = str(self._setting(setting_key, "") or "")
        items: list[str] = []
        for chunk in raw_value.replace("\n", ",").split(","):
            value = chunk.strip()
            if value and value not in items:
                items.append(value)
        return items

    def _set_status(self, message: str, timeout_ms: int = 0) -> None:
        if self._app_context is not None:
            self._app_context.set_status(message, timeout_ms=timeout_ms)

    def _can_connect(self) -> bool:
        return not self._service.is_connected

    def _can_disconnect(self) -> bool:
        return self._service.is_connected

    def _is_connected(self) -> bool:
        return self._service.is_connected

    @staticmethod
    def _action_id(prefix: str, raw_value: str) -> str:
        digest = hashlib.sha1(raw_value.encode("utf-8")).hexdigest()[:10]
        normalized = "".join(char.lower() if char.isalnum() else "_" for char in raw_value)
        normalized = "_".join(part for part in normalized.split("_") if part)[:32] or "item"
        return f"obs.{prefix}.{normalized}_{digest}"

    @staticmethod
    def _validate_host(value: Any) -> str | None:
        if not str(value).strip():
            return "OBS Host cannot be empty."
        return None
