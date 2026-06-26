from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_FIELDS = {"name", "version", "description", "author", "entry_point"}
PLUGIN_NAMESPACE = "stream_controller_runtime_plugins"


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    entry_point: str
    path: Path


@dataclass(slots=True)
class LoadedPlugin:
    manifest: PluginManifest
    instance: Any


@dataclass(slots=True)
class FailedPlugin:
    plugin_id: str
    path: Path
    reason: str
    manifest: PluginManifest | None = None


class PluginManager:
    """Discovers, imports, and registers plugins with the running application."""

    ENABLED_PLUGINS_SETTINGS_KEY = "plugins.enabled"

    def __init__(self, plugins_directory: Path) -> None:
        self._plugins_directory = plugins_directory
        self._app_context: AppContext | None = None
        self._active_plugin_id: str | None = None
        self.discovered_manifests: list[PluginManifest] = []
        self._loaded_plugins: dict[str, LoadedPlugin] = {}
        self._discovery_failures: dict[str, FailedPlugin] = {}
        self._load_failures: dict[str, FailedPlugin] = {}

    @property
    def plugins_directory(self) -> Path:
        return self._plugins_directory

    @property
    def current_plugin_id(self) -> str | None:
        return self._active_plugin_id

    @property
    def loaded_plugins(self) -> list[LoadedPlugin]:
        return self.get_loaded_plugins()

    @property
    def failed_plugins(self) -> list[FailedPlugin]:
        return self.get_failed_plugins()

    def discover_plugins(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        discovery_failures: dict[str, FailedPlugin] = {}

        if not self._plugins_directory.exists():
            self.discovered_manifests = []
            self._discovery_failures = {}
            return []

        for plugin_dir in sorted(self._plugins_directory.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith(".") or plugin_dir.name == "__pycache__":
                continue

            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                discovery_failures[plugin_dir.name] = (
                    FailedPlugin(
                        plugin_id=plugin_dir.name,
                        path=plugin_dir,
                        reason=f"Invalid manifest: {exc}",
                    )
                )
                continue

            missing_fields = REQUIRED_MANIFEST_FIELDS.difference(manifest_data)
            if missing_fields:
                discovery_failures[plugin_dir.name] = (
                    FailedPlugin(
                        plugin_id=plugin_dir.name,
                        path=plugin_dir,
                        reason=f"Missing manifest fields: {', '.join(sorted(missing_fields))}",
                    )
                )
                continue

            manifests.append(
                PluginManifest(
                    plugin_id=plugin_dir.name,
                    name=str(manifest_data["name"]),
                    version=str(manifest_data["version"]),
                    description=str(manifest_data["description"]),
                    author=str(manifest_data["author"]),
                    entry_point=str(manifest_data["entry_point"]),
                    path=plugin_dir,
                )
            )

        self.discovered_manifests = manifests
        self._discovery_failures = discovery_failures
        return manifests

    def load_plugins(self, app_context: AppContext) -> None:
        self._app_context = app_context
        self._loaded_plugins.clear()
        self._load_failures.clear()
        manifests = self.discover_plugins()
        enabled_plugin_ids = self._resolve_enabled_plugin_ids(manifests)

        for manifest in manifests:
            if manifest.plugin_id in enabled_plugin_ids:
                self.load_plugin(manifest.plugin_id, persist=False, discover=False)

        self.save_enabled_plugin_ids()

    def load_plugin(self, plugin_id: str, persist: bool = True, discover: bool = True) -> bool:
        if self._app_context is None:
            raise RuntimeError("Plugin manager is not attached to an app context.")

        if plugin_id in self._loaded_plugins:
            return True

        if discover:
            self.discover_plugins()

        manifest = self.get_manifest(plugin_id)
        if manifest is None:
            self._load_failures[plugin_id] = FailedPlugin(
                plugin_id=plugin_id,
                path=self._plugins_directory / plugin_id,
                reason="Plugin manifest could not be found.",
            )
            return False

        self._load_failures.pop(plugin_id, None)

        try:
            plugin_class = self._resolve_plugin_class(manifest)
            plugin_instance = plugin_class()
            setattr(plugin_instance, "manifest", manifest)

            register_method = getattr(plugin_instance, "register", None)
            if not callable(register_method):
                raise TypeError(
                    f"Plugin '{manifest.name}' does not define a callable register(app_context) method."
                )

            self._active_plugin_id = plugin_id
            try:
                register_method(self._app_context)
            finally:
                self._active_plugin_id = None

            self._loaded_plugins[plugin_id] = LoadedPlugin(manifest=manifest, instance=plugin_instance)
            if persist:
                self.save_enabled_plugin_ids()
            return True
        except Exception as exc:
            logger.exception("Failed to load plugin '%s'.", plugin_id)
            self._active_plugin_id = None
            self._attempt_partial_unregister(plugin_id, locals().get("plugin_instance"))
            self._app_context.main_window.unregister_plugin_ui(plugin_id)
            self._load_failures[plugin_id] = FailedPlugin(
                plugin_id=plugin_id,
                path=manifest.path,
                reason=str(exc),
                manifest=manifest,
            )
            if persist:
                self.save_enabled_plugin_ids()
            return False

    def unload_plugin(self, plugin_id: str, persist: bool = True) -> bool:
        if self._app_context is None:
            raise RuntimeError("Plugin manager is not attached to an app context.")

        loaded_plugin = self._loaded_plugins.get(plugin_id)
        if loaded_plugin is None:
            return True

        unregister_method = getattr(loaded_plugin.instance, "unregister", None)
        if callable(unregister_method):
            try:
                unregister_method(self._app_context)
            except Exception as exc:
                logger.exception("Failed to unload plugin '%s'.", plugin_id)
                self._load_failures[plugin_id] = FailedPlugin(
                    plugin_id=plugin_id,
                    path=loaded_plugin.manifest.path,
                    reason=f"Unload failed: {exc}",
                    manifest=loaded_plugin.manifest,
                )
                return False

        self._app_context.action_registry.unregister_actions_for_plugin(plugin_id)
        self._app_context.settings_registry.unregister_settings_for_plugin(plugin_id)
        self._app_context.unregister_plugin_commands(plugin_id)
        self._app_context.unregister_stage_widgets_for_plugin(plugin_id)
        self._app_context.main_window.unregister_plugin_ui(plugin_id)
        self._loaded_plugins.pop(plugin_id, None)
        self._load_failures.pop(plugin_id, None)

        if persist:
            self.save_enabled_plugin_ids()

        return True

    def get_loaded_plugins(self) -> list[LoadedPlugin]:
        return sorted(self._loaded_plugins.values(), key=lambda plugin: plugin.manifest.name.lower())

    def get_failed_plugins(self) -> list[FailedPlugin]:
        failures = list(self._discovery_failures.values()) + list(self._load_failures.values())
        return sorted(failures, key=lambda plugin: plugin.plugin_id.lower())

    def get_failed_plugin(self, plugin_id: str) -> FailedPlugin | None:
        return self._load_failures.get(plugin_id) or self._discovery_failures.get(plugin_id)

    def get_manifest(self, plugin_id: str) -> PluginManifest | None:
        for manifest in self.discovered_manifests:
            if manifest.plugin_id == plugin_id:
                return manifest
        return None

    def save_enabled_plugin_ids(self) -> None:
        if self._app_context is None:
            return

        enabled_plugin_ids = sorted(self._loaded_plugins)
        self._app_context.settings_manager.set(
            self.ENABLED_PLUGINS_SETTINGS_KEY,
            enabled_plugin_ids,
        )

    def _resolve_plugin_class(self, manifest: PluginManifest) -> type[Any]:
        module_name, class_name = self._parse_entry_point(manifest.entry_point)
        module = self._import_plugin_module(manifest, module_name)

        plugin_class = getattr(module, class_name, None)
        if plugin_class is None:
            raise ImportError(
                f"Entry point '{manifest.entry_point}' did not expose class '{class_name}'."
            )

        return plugin_class

    def _import_plugin_module(self, manifest: PluginManifest, module_name: str) -> Any:
        self._ensure_namespace_package(PLUGIN_NAMESPACE)
        package_name = f"{PLUGIN_NAMESPACE}.{manifest.plugin_id}"
        self._ensure_namespace_package(package_name, path=manifest.path)
        full_module_name = f"{package_name}.{module_name}"

        return importlib.import_module(full_module_name)

    def _resolve_enabled_plugin_ids(self, manifests: list[PluginManifest]) -> set[str]:
        available_plugin_ids = {manifest.plugin_id for manifest in manifests}
        if self._app_context is None:
            return available_plugin_ids

        stored_plugin_ids = self._app_context.settings_manager.get(self.ENABLED_PLUGINS_SETTINGS_KEY)
        if isinstance(stored_plugin_ids, list):
            return {str(plugin_id) for plugin_id in stored_plugin_ids if str(plugin_id) in available_plugin_ids}

        return available_plugin_ids

    def _attempt_partial_unregister(self, plugin_id: str, plugin_instance: Any | None) -> None:
        if self._app_context is None or plugin_instance is None:
            return

        unregister_method = getattr(plugin_instance, "unregister", None)
        if not callable(unregister_method):
            return

        try:
            unregister_method(self._app_context)
        except Exception:
            logger.exception("Partial cleanup failed while loading plugin '%s'.", plugin_id)
        finally:
            self._app_context.action_registry.unregister_actions_for_plugin(plugin_id)
            self._app_context.settings_registry.unregister_settings_for_plugin(plugin_id)

    def _ensure_namespace_package(self, package_name: str, path: Path | None = None) -> None:
        module = sys.modules.get(package_name)
        if module is None:
            module = ModuleType(package_name)
            module.__package__ = package_name
            module.__path__ = []  # type: ignore[attr-defined]
            sys.modules[package_name] = module

        if path is not None and str(path) not in module.__path__:  # type: ignore[attr-defined]
            module.__path__.append(str(path))  # type: ignore[attr-defined]

    @staticmethod
    def _parse_entry_point(entry_point: str) -> tuple[str, str]:
        if ":" not in entry_point:
            raise ValueError(
                f"Entry point '{entry_point}' is invalid. Use the format 'module_name:ClassName'."
            )
        module_name, class_name = entry_point.split(":", maxsplit=1)
        return module_name, class_name
