from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from stream_controller.core.app_context import AppContext
from stream_controller.core.settings_registry import SettingOption
from stream_controller.ui.theme import create_badge, create_card


class ExamplePlugin:
    QUICK_START_PAGE = "Quick Start"
    WORKSPACE_PAGE = "Workspace"

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._has_interacted = False
        self._startup_label: QLabel | None = None
        self._dashboard_status_label: QLabel | None = None
        self._command_result_label: QLabel | None = None
        self._deck_summary_label: QLabel | None = None

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context

        app_context.register_setting(
            setting_key="greeting_name",
            label="Greeting Name",
            field_type="text",
            description="Name used by the example greeting action and command.",
            default="Creator",
            placeholder="Creator",
            required=True,
            validator=self._validate_greeting_name,
        )
        app_context.register_setting(
            setting_key="greeting_style",
            label="Greeting Style",
            field_type="select",
            description="Tone used when the example plugin speaks back.",
            default="friendly",
            options=[
                SettingOption(label="Friendly", value="friendly"),
                SettingOption(label="Professional", value="professional"),
                SettingOption(label="Hype", value="hype"),
            ],
        )
        app_context.register_setting(
            setting_key="status_timeout_seconds",
            label="Status Timeout",
            field_type="number",
            description="How long status messages from this plugin remain visible.",
            default=3,
            minimum=1,
            maximum=10,
            step=1,
        )
        app_context.register_setting(
            setting_key="show_status_notifications",
            label="Show Status Notifications",
            field_type="toggle",
            description="Toggle plugin status messages in the app status bar.",
            default=True,
        )
        app_context.register_setting(
            setting_key="demo_access_code",
            label="Demo Access Code",
            field_type="secret",
            description="Optional hidden field to demonstrate secure-style input handling.",
            default="",
            placeholder="Optional",
        )

        app_context.command_registry.register("example.say_hello", self.say_hello)
        app_context.register_action(
            action_id="example.say_hello_action",
            title="Say Hello",
            description="Run the example command and verify the control deck is wired to plugin logic.",
            execute=self._execute_say_hello_action,
            icon="HI",
            page=self.QUICK_START_PAGE,
            group="Quick Actions",
            default_shortcut="Ctrl+Alt+H",
        )
        app_context.register_action(
            action_id="example.open_workspace_action",
            title="Open Workspace",
            description="Jump directly into the Example Plugin workspace from the deck.",
            execute=self._open_workspace,
            icon="GO",
            page=self.WORKSPACE_PAGE,
            group="Navigation",
            default_shortcut="Ctrl+Alt+E",
        )
        app_context.register_action(
            action_id="example.reset_demo_state",
            title="Reset Demo State",
            description="Clear the demo feedback and return the example plugin to its initial state.",
            execute=self._reset_demo_state,
            icon="RS",
            page=self.QUICK_START_PAGE,
            group="Quick Actions",
            enabled=self._can_reset_demo_state,
            default_shortcut="Ctrl+Alt+R",
        )
        app_context.event_bus.subscribe("app.started", self._on_app_started)

        app_context.register_plugin_page(
            page_id="example_plugin",
            title="Example Plugin",
            subtitle="A bundled sample extension proving the plugin system is alive.",
            widget=self._build_plugin_page(),
        )
        app_context.register_dashboard_panel(
            title="Example Plugin",
            description="This dashboard panel is supplied by the bundled starter plugin.",
            widget=self._build_dashboard_panel(),
        )
        app_context.set_status("Example Plugin loaded successfully.", timeout_ms=3000)

        if app_context.app_started:
            self._on_app_started(app_context.runtime_snapshot())

    def unregister(self, app_context: AppContext) -> None:
        app_context.event_bus.unsubscribe("app.started", self._on_app_started)
        try:
            app_context.command_registry.unregister("example.say_hello")
        except KeyError:
            pass

        self._app_context = None
        self._has_interacted = False
        self._startup_label = None
        self._dashboard_status_label = None
        self._command_result_label = None
        self._deck_summary_label = None

    def say_hello(self, name: str = "Creator") -> str:
        self._has_interacted = True
        greeting_name = self._setting("greeting_name", name)
        greeting_style = self._setting("greeting_style", "friendly")
        message = self._build_greeting_message(greeting_name, greeting_style)
        if self._command_result_label is not None:
            self._command_result_label.setText(message)

        if self._app_context is not None and self._setting("show_status_notifications", True):
            timeout_ms = int(self._setting("status_timeout_seconds", 3)) * 1000
            self._app_context.set_status("example.say_hello executed.", timeout_ms=timeout_ms)
            self._app_context.refresh_action_state()

        return message

    def _build_plugin_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        overview_card, overview_body = create_card(
            "Example Plugin",
            "This plugin keeps its own command, event, and UI logic inside the plugin folder while integrating through AppContext.",
        )
        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)
        badges_row.addWidget(create_badge("Registered", "success"))
        badges_row.addWidget(create_badge("Self-Contained", "accent"))
        badges_row.addStretch(1)

        self._startup_label = QLabel("Waiting for the app.started event...")
        self._startup_label.setObjectName("MetaText")
        self._startup_label.setWordWrap(True)

        overview_body.addLayout(badges_row)
        overview_body.addWidget(self._startup_label)

        command_card, command_body = create_card(
            "Command Demo",
            "Run the plugin's command through the shared command registry to validate command dispatch end to end.",
        )
        run_button = QPushButton("Run example.say_hello")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self._run_registered_command)

        self._command_result_label = QLabel("Command output will appear here.")
        self._command_result_label.setObjectName("MetaText")
        self._command_result_label.setWordWrap(True)

        command_body.addWidget(run_button, 0, Qt.AlignLeft)
        command_body.addWidget(self._command_result_label)

        layout.addWidget(overview_card)
        layout.addWidget(command_card)
        layout.addStretch(1)
        return page

    def _build_dashboard_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        loaded_label = QLabel("Loaded successfully and contributing UI plus three control deck actions.")
        loaded_label.setObjectName("CardDescription")
        loaded_label.setWordWrap(True)

        self._dashboard_status_label = QLabel("Listening for app.started...")
        self._dashboard_status_label.setObjectName("MetaText")
        self._dashboard_status_label.setWordWrap(True)

        quick_action = QPushButton("Say hello")
        quick_action.setObjectName("SecondaryButton")
        quick_action.clicked.connect(self._run_registered_command)

        layout.addWidget(loaded_label)
        layout.addWidget(self._dashboard_status_label)
        layout.addWidget(quick_action, 0, Qt.AlignLeft)
        return panel

    def _on_app_started(self, payload: Any) -> None:
        loaded_plugins = 0
        if isinstance(payload, dict):
            loaded_plugins = int(payload.get("loaded_plugins", 0))

        status_text = f"Received app.started and detected {loaded_plugins} loaded plugin(s)."
        if self._startup_label is not None:
            self._startup_label.setText(status_text)
        if self._dashboard_status_label is not None:
            self._dashboard_status_label.setText(status_text)

    def _run_registered_command(self) -> None:
        if self._app_context is None:
            return
        self._app_context.command_registry.execute("example.say_hello", name="Creator")

    def _execute_say_hello_action(self) -> str:
        self._run_registered_command()
        if self._deck_summary_label is not None:
            self._deck_summary_label.setText("Last action: Say Hello fired from the Quick Start deck page.")
        return "Example Plugin greeting triggered."

    def _open_workspace(self) -> None:
        if self._app_context is None:
            return
        self._app_context.show_page("example_plugin")
        self._app_context.set_status("Example Plugin workspace opened from the control deck.", timeout_ms=2500)
        if self._deck_summary_label is not None:
            self._deck_summary_label.setText("Last action: Open Workspace navigated in from the Workspace deck page.")

    def _can_reset_demo_state(self) -> bool:
        return self._has_interacted

    def _reset_demo_state(self) -> None:
        self._has_interacted = False

        if self._command_result_label is not None:
            self._command_result_label.setText("Command output will appear here.")
        if self._deck_summary_label is not None:
            self._deck_summary_label.setText("Deck pages: Quick Start and Workspace. Suggested hotkeys are ready in Settings.")
        if self._app_context is not None:
            self._app_context.set_status("Example Plugin demo state reset.", timeout_ms=2500)
            self._app_context.refresh_action_state()

    def _setting(self, setting_key: str, default: Any = None) -> Any:
        if self._app_context is None:
            return default
        manifest = getattr(self, "manifest", None)
        if manifest is None:
            return default
        return self._app_context.get_setting(manifest.plugin_id, setting_key, default)

    @staticmethod
    def _validate_greeting_name(value: Any) -> str | None:
        if not str(value).strip():
            return "Greeting Name cannot be empty."
        return None

    @staticmethod
    def _build_greeting_message(name: str, style: str) -> str:
        if style == "professional":
            return (
                f"Hello, {name}. The Example Plugin is configured and ready to support your creator workflow."
            )
        if style == "hype":
            return f"Hey {name}! The Example Plugin is live, loaded, and ready to light up your stream deck."
        return f"Hello, {name}. The Example Plugin is connected to the command registry and ready for future creator tools."
