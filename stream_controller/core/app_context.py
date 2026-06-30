from __future__ import annotations

from typing import Any, Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from stream_controller.core.action_registry import ActionDefinition, ActionEnabledState, ActionRegistry
from stream_controller.core.command_registry import CommandRegistry
from stream_controller.core.event_bus import EventBus
from stream_controller.core.hotkey_manager import HotkeyManager
from stream_controller.core.settings_registry import (
    SettingDefinition,
    SettingFieldType,
    SettingOption,
    SettingValidator,
    SettingsRegistry,
)
from stream_controller.core.settings_manager import SettingsManager
from stream_controller.ui.stage_view.stage_registry import StageRegistry

if TYPE_CHECKING:
    from stream_controller.core.plugin_manager import PluginManager
    from stream_controller.ui.main_window import MainWindow


class AppContext:
    """Shared application context exposed to plugins."""

    def __init__(
        self,
        action_registry: ActionRegistry,
        event_bus: EventBus,
        command_registry: CommandRegistry,
        hotkey_manager: HotkeyManager,
        settings_registry: SettingsRegistry,
        settings_manager: SettingsManager,
    ) -> None:
        self.action_registry = action_registry
        self.event_bus = event_bus
        self.command_registry = command_registry
        self.hotkey_manager = hotkey_manager
        self.settings_registry = settings_registry
        self.settings_manager = settings_manager
        self._plugin_manager: PluginManager | None = None
        self._main_window: MainWindow | None = None
        self._app_started = False
        self._plugin_commands: dict[str, list[str]] = {}
        self._plugin_stage_panels: dict[str, list[str]] = {}
        self._stage_registry = StageRegistry()

    @property
    def plugin_manager(self) -> PluginManager:
        if self._plugin_manager is None:
            raise RuntimeError("Plugin manager has not been attached to the app context yet.")
        return self._plugin_manager

    @property
    def main_window(self) -> MainWindow:
        if self._main_window is None:
            raise RuntimeError("Main window has not been attached to the app context yet.")
        return self._main_window

    def attach_plugin_manager(self, plugin_manager: PluginManager) -> None:
        self._plugin_manager = plugin_manager

    def attach_main_window(self, main_window: MainWindow) -> None:
        self._main_window = main_window

    @property
    def app_started(self) -> bool:
        return self._app_started

    def register_plugin_page(
        self,
        page_id: str,
        title: str,
        widget: QWidget,
        subtitle: str = "Plugin workspace",
        plugin_id: str | None = None,
        help_text: str = "",
    ) -> None:
        plugin_id = plugin_id or self._require_active_plugin_id()
        self.main_window.register_plugin_page(
            plugin_id=plugin_id,
            page_id=page_id,
            title=title,
            subtitle=subtitle,
            widget=widget,
            help_text=help_text,
        )

    def register_dashboard_panel(
        self,
        title: str,
        description: str,
        widget: QWidget,
        plugin_id: str | None = None,
    ) -> None:
        plugin_id = plugin_id or self._require_active_plugin_id()
        self.main_window.register_dashboard_panel(
            plugin_id=plugin_id,
            title=title,
            description=description,
            widget=widget,
        )

    @property
    def stage_registry(self) -> "StageRegistry":
        return self._stage_registry

    def register_stage_widget(
        self,
        panel_id: str,
        title: str,
        icon: str,
        factory,
        plugin_id: str | None = None,
    ) -> None:
        plugin_id = plugin_id or self._require_active_plugin_id()
        self._stage_registry.register(
            panel_id=panel_id,
            title=title,
            icon=icon,
            factory=factory,
        )
        self._plugin_stage_panels.setdefault(plugin_id, []).append(panel_id)

    def unregister_stage_widgets_for_plugin(self, plugin_id: str) -> None:
        for panel_id in self._plugin_stage_panels.pop(plugin_id, []):
            self._stage_registry.unregister(panel_id)

    def unregister_action(self, action_id: str) -> None:
        self.action_registry.unregister(action_id)

    def set_status(self, message: str, timeout_ms: int = 0) -> None:
        self.main_window.set_status_message(message, timeout_ms=timeout_ms)

    def show_page(self, page_id: str) -> None:
        self.main_window.show_page(page_id)

    def refresh_runtime_state(self) -> None:
        self.main_window.refresh_runtime_state()

    def refresh_action_state(self) -> None:
        self.main_window.refresh_action_state()

    def register_action(
        self,
        action_id: str,
        title: str,
        description: str,
        execute: Callable[..., Any],
        icon: str | None = None,
        page: str = "General",
        group: str = "General",
        enabled: ActionEnabledState = True,
        default_shortcut: str | None = None,
        plugin_id: str | None = None,
        widget_factory: Callable[[], Any] | None = None,
    ) -> None:
        resolved_plugin_id = plugin_id or self._require_active_plugin_id()
        manifest = self.plugin_manager.get_manifest(resolved_plugin_id)
        self.action_registry.register(
            ActionDefinition(
                action_id=action_id,
                title=title,
                description=description,
                execute=execute,
                icon=icon,
                page=page,
                group=group,
                plugin_id=resolved_plugin_id,
                plugin_name=manifest.name if manifest is not None else resolved_plugin_id,
                enabled=enabled,
                default_shortcut=default_shortcut,
                widget_factory=widget_factory,
            )
        )

    def register_setting(
        self,
        setting_key: str,
        label: str,
        field_type: SettingFieldType,
        description: str = "",
        default: Any = None,
        options: list[SettingOption] | None = None,
        placeholder: str | None = None,
        minimum: float | int | None = None,
        maximum: float | int | None = None,
        step: float | int | None = None,
        required: bool = False,
        validator: SettingValidator | None = None,
    ) -> None:
        plugin_id = self._require_active_plugin_id()
        manifest = self.plugin_manager.get_manifest(plugin_id)
        self.settings_registry.register(
            SettingDefinition(
                setting_key=setting_key,
                label=label,
                field_type=field_type,
                description=description,
                default=default,
                options=tuple(options or []),
                placeholder=placeholder,
                minimum=minimum,
                maximum=maximum,
                step=step,
                required=required,
                validator=validator,
                plugin_id=plugin_id,
                plugin_name=manifest.name if manifest is not None else plugin_id,
            )
        )

    def register_command(self, command_name: str, handler: Callable[..., Any]) -> None:
        plugin_id = self._require_active_plugin_id()
        self.command_registry.register(command_name, handler)
        self._plugin_commands.setdefault(plugin_id, []).append(command_name)

    def unregister_plugin_commands(self, plugin_id: str) -> None:
        for command_name in self._plugin_commands.pop(plugin_id, []):
            try:
                self.command_registry.unregister(command_name)
            except KeyError:
                pass

    def get_setting(self, plugin_id: str, setting_key: str, default: Any = None) -> Any:
        return self.settings_registry.get_value(
            settings_manager=self.settings_manager,
            plugin_id=plugin_id,
            setting_key=setting_key,
            default=default,
        )

    def mark_app_started(self) -> None:
        self._app_started = True

    def runtime_snapshot(self) -> dict[str, Any]:
        return {
            "actions": len(self.action_registry.list_actions()),
            "loaded_plugins": len(self.plugin_manager.loaded_plugins),
            "failed_plugins": len(self.plugin_manager.failed_plugins),
            "commands": self.command_registry.list_commands(),
        }

    def _require_active_plugin_id(self) -> str:
        plugin_id = self.plugin_manager.current_plugin_id
        if plugin_id is None:
            raise RuntimeError("Plugin UI registration must happen during plugin registration.")
        return plugin_id
