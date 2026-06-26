from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from stream_controller.core.settings_manager import SettingsManager

SettingFieldType = Literal["text", "number", "toggle", "select", "secret"]
SettingValidator = Callable[[Any], str | None]


@dataclass(frozen=True, slots=True)
class SettingOption:
    label: str
    value: Any


@dataclass(slots=True)
class SettingDefinition:
    setting_key: str
    label: str
    field_type: SettingFieldType
    description: str = ""
    default: Any = None
    options: tuple[SettingOption, ...] = field(default_factory=tuple)
    placeholder: str | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    required: bool = False
    validator: SettingValidator | None = None
    plugin_id: str | None = None
    plugin_name: str | None = None

    @property
    def storage_key(self) -> str:
        if self.plugin_id is None:
            raise RuntimeError("Plugin settings must be associated with a plugin id.")
        return f"{self.plugin_id}.{self.setting_key}"

    def expects_integer(self) -> bool:
        numeric_values = [self.default, self.minimum, self.maximum, self.step]
        for value in numeric_values:
            if value is None:
                continue
            if isinstance(value, float) and not value.is_integer():
                return False
        return True


class SettingsRegistry:
    """Tracks plugin-declared settings schemas and validates stored values."""

    def __init__(self) -> None:
        self._settings: dict[str, SettingDefinition] = {}

    def register(self, definition: SettingDefinition) -> None:
        storage_key = definition.storage_key
        if storage_key in self._settings:
            raise ValueError(f"Setting '{storage_key}' is already registered.")
        self._settings[storage_key] = definition

    def unregister(self, plugin_id: str, setting_key: str) -> None:
        storage_key = f"{plugin_id}.{setting_key}"
        if storage_key not in self._settings:
            raise KeyError(f"Setting '{storage_key}' is not registered.")
        self._settings.pop(storage_key, None)

    def unregister_settings_for_plugin(self, plugin_id: str) -> None:
        for storage_key in [
            definition.storage_key
            for definition in self._settings.values()
            if definition.plugin_id == plugin_id
        ]:
            self._settings.pop(storage_key, None)

    def list_settings(self) -> list[SettingDefinition]:
        return sorted(
            self._settings.values(),
            key=lambda definition: (
                (definition.plugin_name or definition.plugin_id or "").lower(),
                definition.label.lower(),
                definition.setting_key.lower(),
            ),
        )

    def get_settings_for_plugin(self, plugin_id: str) -> list[SettingDefinition]:
        return [
            definition
            for definition in self.list_settings()
            if definition.plugin_id == plugin_id
        ]

    def get_definition(self, plugin_id: str, setting_key: str) -> SettingDefinition | None:
        return self._settings.get(f"{plugin_id}.{setting_key}")

    def get_value(
        self,
        settings_manager: SettingsManager,
        plugin_id: str,
        setting_key: str,
        default: Any = None,
    ) -> Any:
        definition = self.get_definition(plugin_id, setting_key)
        if definition is None:
            return settings_manager.get_plugin_setting(plugin_id, setting_key, default)
        return settings_manager.get_plugin_setting(plugin_id, setting_key, definition.default)

    def get_resolved_values(
        self,
        settings_manager: SettingsManager,
        plugin_id: str,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for definition in self.get_settings_for_plugin(plugin_id):
            values[definition.setting_key] = self.get_value(
                settings_manager=settings_manager,
                plugin_id=plugin_id,
                setting_key=definition.setting_key,
                default=definition.default,
            )
        return values

    def validate_plugin_values(self, plugin_id: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for definition in self.get_settings_for_plugin(plugin_id):
            if definition.setting_key not in values:
                normalized[definition.setting_key] = definition.default
                continue
            normalized[definition.setting_key] = self._validate_value(definition, values[definition.setting_key])
        return normalized

    def reset_plugin_settings(self, settings_manager: SettingsManager, plugin_id: str) -> None:
        settings_manager.reset_plugin_settings(plugin_id)

    def _validate_value(self, definition: SettingDefinition, value: Any) -> Any:
        normalized: Any

        if definition.field_type in {"text", "secret"}:
            normalized = "" if value is None else str(value)
            if definition.required and not normalized.strip():
                raise ValueError(f"'{definition.label}' is required.")
        elif definition.field_type == "toggle":
            normalized = bool(value)
        elif definition.field_type == "number":
            normalized = self._normalize_number(definition, value)
        elif definition.field_type == "select":
            valid_values = {option.value for option in definition.options}
            if value not in valid_values:
                raise ValueError(f"'{definition.label}' must be one of the configured options.")
            normalized = value
        else:
            raise ValueError(f"Unsupported field type '{definition.field_type}'.")

        if definition.validator is not None:
            error = definition.validator(normalized)
            if error:
                raise ValueError(error)

        return normalized

    def _normalize_number(self, definition: SettingDefinition, value: Any) -> int | float:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'{definition.label}' must be numeric.") from exc

        if definition.minimum is not None and numeric_value < float(definition.minimum):
            raise ValueError(f"'{definition.label}' must be at least {definition.minimum}.")
        if definition.maximum is not None and numeric_value > float(definition.maximum):
            raise ValueError(f"'{definition.label}' must be at most {definition.maximum}.")

        if definition.expects_integer():
            if not numeric_value.is_integer():
                raise ValueError(f"'{definition.label}' must be a whole number.")
            return int(numeric_value)
        return numeric_value
