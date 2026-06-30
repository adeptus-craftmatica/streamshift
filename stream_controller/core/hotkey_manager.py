from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QKeySequenceEdit, QWidget

from stream_controller.core.action_registry import ActionDefinition, ActionRegistry
from stream_controller.core.event_bus import EventBus
from stream_controller.core.settings_manager import SettingsManager


@dataclass(slots=True)
class HotkeyBinding:
    action_id: str
    shortcut: str | None
    display_shortcut: str | None
    default_shortcut: str | None
    default_display_shortcut: str | None
    has_user_override: bool
    conflict_action_ids: tuple[str, ...] = ()

    @property
    def is_conflicted(self) -> bool:
        return bool(self.conflict_action_ids)


class HotkeyManager:
    """Maps persisted shortcuts to registered actions and keeps live QShortcuts in sync."""

    def __init__(
        self,
        action_registry: ActionRegistry,
        settings_manager: SettingsManager,
        event_bus: EventBus,
    ) -> None:
        self._action_registry = action_registry
        self._settings_manager = settings_manager
        self._event_bus = event_bus
        self._host_widget: QWidget | None = None
        self._shortcuts: dict[str, QShortcut] = {}

    def attach_host(self, host_widget: QWidget) -> None:
        self._host_widget = host_widget

    def describe_bindings(self, actions: list[ActionDefinition] | None = None) -> list[HotkeyBinding]:
        target_actions = actions or self._action_registry.list_actions()
        stored_bindings = self._settings_manager.get_hotkey_bindings()

        resolved_bindings: list[HotkeyBinding] = []
        shortcut_owners: dict[str, list[str]] = {}

        for action in target_actions:
            default_shortcut = self.normalize_shortcut(action.default_shortcut)
            has_user_override = action.action_id in stored_bindings
            shortcut = (
                self.normalize_shortcut(stored_bindings.get(action.action_id))
                if has_user_override
                else default_shortcut
            )

            if shortcut is not None:
                shortcut_owners.setdefault(shortcut, []).append(action.action_id)

            resolved_bindings.append(
                HotkeyBinding(
                    action_id=action.action_id,
                    shortcut=shortcut,
                    display_shortcut=self.to_display_shortcut(shortcut),
                    default_shortcut=default_shortcut,
                    default_display_shortcut=self.to_display_shortcut(default_shortcut),
                    has_user_override=has_user_override,
                )
            )

        conflicts = {
            shortcut: tuple(action_ids)
            for shortcut, action_ids in shortcut_owners.items()
            if len(action_ids) > 1
        }

        for binding in resolved_bindings:
            if binding.shortcut is None:
                continue
            binding.conflict_action_ids = tuple(
                action_id
                for action_id in conflicts.get(binding.shortcut, ())
                if action_id != binding.action_id
            )

        return resolved_bindings

    def get_binding_map(self, actions: list[ActionDefinition] | None = None) -> dict[str, HotkeyBinding]:
        return {
            binding.action_id: binding
            for binding in self.describe_bindings(actions)
        }

    def sync_actions(self, actions: list[ActionDefinition] | None = None) -> None:
        if self._host_widget is None:
            return

        action_bindings = self.get_binding_map(actions)
        active_shortcuts = {
            action_id: binding.shortcut
            for action_id, binding in action_bindings.items()
            if binding.shortcut and not binding.is_conflicted
        }

        for action_id, shortcut in list(self._shortcuts.items()):
            expected_shortcut = active_shortcuts.get(action_id)
            current_shortcut = shortcut.key().toString(QKeySequence.PortableText) or None
            if expected_shortcut == current_shortcut:
                continue

            shortcut.setEnabled(False)
            shortcut.deleteLater()
            self._shortcuts.pop(action_id, None)

        for action_id, shortcut_text in active_shortcuts.items():
            if action_id in self._shortcuts or shortcut_text is None:
                continue

            shortcut = QShortcut(
                QKeySequence.fromString(shortcut_text, QKeySequence.PortableText),
                self._host_widget,
            )
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda action_id=action_id, shortcut_text=shortcut_text: self._execute_action(action_id, shortcut_text)
            )
            self._shortcuts[action_id] = shortcut

    def validate_bindings(
        self,
        bindings: dict[str, str | None],
        actions: list[ActionDefinition] | None = None,
    ) -> dict[str, str | None]:
        target_actions = actions or self._action_registry.list_actions()
        actions_by_id = {action.action_id: action for action in target_actions}
        normalized_bindings: dict[str, str | None] = {}
        shortcut_owners: dict[str, list[str]] = {}

        for action_id, shortcut in bindings.items():
            if action_id not in actions_by_id:
                continue

            normalized_shortcut = self.normalize_shortcut(shortcut)
            normalized_bindings[action_id] = normalized_shortcut
            if normalized_shortcut is not None:
                shortcut_owners.setdefault(normalized_shortcut, []).append(action_id)

        conflicts = {
            shortcut: action_ids
            for shortcut, action_ids in shortcut_owners.items()
            if len(action_ids) > 1
        }
        if conflicts:
            raise ValueError(self._build_conflict_message(conflicts, actions_by_id))

        return normalized_bindings

    def save_bindings(self, bindings: dict[str, str | None]) -> None:
        actions = self._action_registry.list_actions()
        normalized_bindings = self.validate_bindings(bindings, actions)
        actions_by_id = {action.action_id: action for action in actions}
        existing_bindings = self._settings_manager.get_hotkey_bindings()

        stored_bindings = {
            action_id: shortcut
            for action_id, shortcut in existing_bindings.items()
            if action_id not in actions_by_id
        }

        for action_id, action in actions_by_id.items():
            assigned_shortcut = normalized_bindings.get(action_id)
            default_shortcut = self.normalize_shortcut(action.default_shortcut)

            if assigned_shortcut == default_shortcut:
                continue

            if assigned_shortcut is None and default_shortcut is None:
                continue

            stored_bindings[action_id] = assigned_shortcut

        self._settings_manager.set_hotkey_bindings(stored_bindings)
        self.sync_actions(actions)
        self._event_bus.emit(
            "hotkeys.updated",
            {"bindings": dict(stored_bindings)},
        )

    def reset_bindings(self, action_ids: list[str] | tuple[str, ...] | None = None) -> None:
        self._settings_manager.reset_hotkey_bindings(action_ids=action_ids)
        self.sync_actions()
        self._event_bus.emit(
            "hotkeys.updated",
            {"bindings": self._settings_manager.get_hotkey_bindings()},
        )

    @staticmethod
    def normalize_shortcut(shortcut: str | None) -> str | None:
        if shortcut is None:
            return None

        normalized_text = str(shortcut).strip()
        if not normalized_text:
            return None

        sequence = QKeySequence.fromString(normalized_text, QKeySequence.PortableText)
        portable_text = sequence.toString(QKeySequence.PortableText).strip()
        return portable_text or None

    @staticmethod
    def to_display_shortcut(shortcut: str | None) -> str | None:
        if shortcut is None:
            return None

        sequence = QKeySequence.fromString(shortcut, QKeySequence.PortableText)
        display_text = sequence.toString(QKeySequence.NativeText).strip()
        return display_text or shortcut

    def _execute_action(self, action_id: str, shortcut_text: str) -> None:
        if isinstance(QApplication.focusWidget(), QKeySequenceEdit):
            return

        try:
            self._action_registry.execute(action_id)
            self._event_bus.emit(
                "hotkey.executed",
                {"action_id": action_id, "shortcut": shortcut_text},
            )
        except Exception as exc:
            self._event_bus.emit(
                "hotkey.execution_failed",
                {"action_id": action_id, "shortcut": shortcut_text, "error": str(exc)},
            )

    @staticmethod
    def _build_conflict_message(
        conflicts: dict[str, list[str]],
        actions_by_id: dict[str, ActionDefinition],
    ) -> str:
        conflict_parts: list[str] = []
        for shortcut, action_ids in sorted(conflicts.items()):
            action_titles = ", ".join(actions_by_id[action_id].title for action_id in action_ids)
            conflict_parts.append(f"{shortcut}: {action_titles}")
        return "Shortcut conflicts detected. Resolve these duplicates first: " + "; ".join(conflict_parts)
