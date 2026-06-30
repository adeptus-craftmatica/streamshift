from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from stream_controller.core.event_bus import EventBus

ActionHandler = Callable[..., Any]
ActionEnabledState = bool | Callable[[], bool]


@dataclass(slots=True)
class ActionDefinition:
    action_id: str
    title: str
    description: str
    execute: ActionHandler
    icon: str | None = None
    page: str = "General"
    group: str = "General"
    plugin_id: str | None = None
    plugin_name: str | None = None
    enabled: ActionEnabledState = True
    default_shortcut: str | None = None
    # Optional: supply a factory that returns a QWidget to embed in the live deck tile.
    # When set, the widget replaces the standard ActionTile for this action.
    widget_factory: Callable[[], Any] | None = None

    def is_enabled(self) -> bool:
        if callable(self.enabled):
            return bool(self.enabled())
        return bool(self.enabled)


class ActionRegistry:
    """Tracks controller actions registered by the app and plugins."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._actions: dict[str, ActionDefinition] = {}

    def register(self, action: ActionDefinition) -> None:
        if action.action_id in self._actions:
            raise ValueError(f"Action '{action.action_id}' is already registered.")
        self._actions[action.action_id] = action

    def unregister(self, action_id: str) -> None:
        if action_id not in self._actions:
            raise KeyError(f"Action '{action_id}' is not registered.")
        self._actions.pop(action_id, None)

    def unregister_actions_for_plugin(self, plugin_id: str) -> None:
        for action_id in [
            action.action_id for action in self._actions.values() if action.plugin_id == plugin_id
        ]:
            self._actions.pop(action_id, None)

    def execute(self, action_id: str, **kwargs: Any) -> Any:
        action = self.get_action(action_id)
        if action is None:
            raise KeyError(f"Action '{action_id}' is not registered.")
        if not action.is_enabled():
            raise RuntimeError(f"Action '{action_id}' is currently disabled.")

        result = action.execute(**kwargs)
        self._event_bus.emit(
            "action.executed",
            {
                "action_id": action.action_id,
                "plugin_id": action.plugin_id,
                "page": action.page,
                "group": action.group,
            },
        )
        return result

    def get_action(self, action_id: str) -> ActionDefinition | None:
        return self._actions.get(action_id)

    def list_actions(self) -> list[ActionDefinition]:
        return sorted(
            self._actions.values(),
            key=lambda action: (
                action.page.lower(),
                action.group.lower(),
                action.title.lower(),
                action.action_id.lower(),
            ),
        )
