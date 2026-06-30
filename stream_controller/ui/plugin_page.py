from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from stream_controller.core.plugin_manager import FailedPlugin, LoadedPlugin, PluginManifest
from stream_controller.ui.theme import create_badge, create_card
from stream_controller.ui.ui_utils import clear_layout


class PluginCatalogPage(QWidget):
    load_requested = Signal(str)
    unload_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        root_layout.addWidget(scroll_area)

        container = QWidget()
        scroll_area.setWidget(container)

        self._content_layout = QVBoxLayout(container)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(24)

        intro_card, intro_body = create_card(
            "Plugin System",
            "Plugins can contribute commands, subscribe to events, register settings, and add dedicated workspaces to the shell.",
        )
        intro_meta = QLabel(
            "Each plugin is discovered from the local plugins directory, can be enabled or disabled on demand, and restores its last loaded state the next time the app launches."
        )
        intro_meta.setObjectName("MetaText")
        intro_meta.setWordWrap(True)
        intro_body.addWidget(intro_meta)
        self._content_layout.addWidget(intro_card)

        installed_title = QLabel("Installed Plugins")
        installed_title.setObjectName("SectionTitle")
        self._content_layout.addWidget(installed_title)

        self._installed_layout = QVBoxLayout()
        self._installed_layout.setSpacing(16)
        self._content_layout.addLayout(self._installed_layout)

        self._installed_empty_state = QLabel("No plugins were found yet.")
        self._installed_empty_state.setObjectName("EmptyState")
        self._installed_empty_state.setWordWrap(True)
        self._content_layout.addWidget(self._installed_empty_state)

        failed_title = QLabel("Plugin Issues")
        failed_title.setObjectName("SectionTitle")
        self._content_layout.addWidget(failed_title)

        self._failed_layout = QVBoxLayout()
        self._failed_layout.setSpacing(16)
        self._content_layout.addLayout(self._failed_layout)

        self._failed_empty_state = QLabel("No plugin failures detected.")
        self._failed_empty_state.setObjectName("EmptyState")
        self._failed_empty_state.setWordWrap(True)
        self._content_layout.addWidget(self._failed_empty_state)

        self._content_layout.addStretch(1)

    def set_plugins(
        self,
        discovered_manifests: list[PluginManifest],
        loaded_plugins: list[LoadedPlugin],
        failed_plugins: list[FailedPlugin],
    ) -> None:
        clear_layout(self._installed_layout)
        clear_layout(self._failed_layout)

        loaded_by_id = {plugin.manifest.plugin_id: plugin for plugin in loaded_plugins}
        failed_by_id = {plugin.plugin_id: plugin for plugin in failed_plugins}

        if discovered_manifests:
            self._installed_empty_state.hide()
            for manifest in discovered_manifests:
                self._installed_layout.addWidget(
                    self._build_manifest_card(
                        manifest=manifest,
                        loaded_plugin=loaded_by_id.get(manifest.plugin_id),
                        failure=failed_by_id.get(manifest.plugin_id),
                    )
                )
        else:
            self._installed_empty_state.setText(
                "No plugins were found. Add plugin folders under stream_controller/plugins to extend the app."
            )
            self._installed_empty_state.show()

        issue_plugins = [
            plugin for plugin in failed_plugins if plugin.plugin_id not in {manifest.plugin_id for manifest in discovered_manifests}
        ]

        if issue_plugins:
            self._failed_empty_state.hide()
            for plugin in issue_plugins:
                self._failed_layout.addWidget(self._build_failed_plugin_card(plugin))
        else:
            self._failed_empty_state.show()

    def _build_manifest_card(
        self,
        manifest: PluginManifest,
        loaded_plugin: LoadedPlugin | None,
        failure: FailedPlugin | None,
    ) -> QFrame:
        card, body = create_card()
        title_row = QHBoxLayout()
        title_label = QLabel(manifest.name)
        title_label.setObjectName("CardTitle")
        description_label = QLabel(manifest.description)
        description_label.setObjectName("CardDescription")
        description_label.setWordWrap(True)

        title_row.addWidget(title_label)
        title_row.addStretch(1)
        if loaded_plugin is not None:
            title_row.addWidget(create_badge("Loaded", "success"))
        elif failure is not None:
            title_row.addWidget(create_badge("Load Error", "danger"))
        else:
            title_row.addWidget(create_badge("Available", "neutral"))

        metadata = QLabel(
            f"ID: {manifest.plugin_id}   |   Version: {manifest.version}   |   Author: {manifest.author}"
        )
        metadata.setObjectName("MetaText")
        metadata.setWordWrap(True)

        entry_point = QLabel(f"Entry point: {manifest.entry_point}")
        entry_point.setObjectName("MetaText")
        entry_point.setWordWrap(True)

        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        action_button = QPushButton("Unload Plugin" if loaded_plugin is not None else "Load Plugin")
        action_button.setObjectName("SecondaryButton" if loaded_plugin is not None else "PrimaryButton")
        if loaded_plugin is not None:
            action_button.clicked.connect(lambda checked=False, plugin_id=manifest.plugin_id: self.unload_requested.emit(plugin_id))
        else:
            action_button.clicked.connect(lambda checked=False, plugin_id=manifest.plugin_id: self.load_requested.emit(plugin_id))

        action_row.addWidget(action_button)
        action_row.addStretch(1)

        body.addLayout(title_row)
        body.addWidget(description_label)
        body.addWidget(metadata)
        body.addWidget(entry_point)
        if failure is not None:
            failure_label = QLabel(f"Load error: {failure.reason}")
            failure_label.setObjectName("PluginErrorText")
            failure_label.setWordWrap(True)
            body.addWidget(failure_label)
        body.addLayout(action_row)
        return card

    def _build_failed_plugin_card(self, plugin: FailedPlugin) -> QFrame:
        card, body = create_card()
        title_row = QHBoxLayout()
        title_label = QLabel(plugin.manifest.name if plugin.manifest else plugin.plugin_id)
        title_label.setObjectName("CardTitle")

        title_row.addWidget(title_label)
        title_row.addStretch(1)
        title_row.addWidget(create_badge("Failed", "danger"))

        path_label = QLabel(f"Located at: {plugin.path}")
        path_label.setObjectName("MetaText")
        path_label.setWordWrap(True)

        reason_label = QLabel(plugin.reason)
        reason_label.setObjectName("PluginErrorText")
        reason_label.setWordWrap(True)

        body.addLayout(title_row)
        body.addWidget(reason_label)
        body.addWidget(path_label)
        return card
