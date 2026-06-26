from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from stream_controller.core.action_registry import ActionDefinition
from stream_controller.core.app_context import AppContext
from stream_controller.core.hotkey_manager import HotkeyBinding
from stream_controller.ui.dashboard import DashboardPage
from stream_controller.ui.plugin_page import PluginCatalogPage
from stream_controller.ui.settings_page import PluginSettingsPage
from stream_controller.ui.sidebar import Sidebar
from stream_controller.ui.stage_view.stage_view_page import StageViewPage
from stream_controller.ui.theme import create_badge


class MainWindow(QMainWindow):
    def __init__(self, app_context: AppContext) -> None:
        super().__init__()
        self._app_context = app_context
        self._pages: dict[str, QWidget] = {}
        self._page_headers: dict[str, tuple[str, str, str]] = {}
        self._page_owners: dict[str, str | None] = {}
        self._app_context.event_bus.subscribe("action.executed", self._on_action_executed)
        self._app_context.event_bus.subscribe("hotkey.execution_failed", self._on_hotkey_execution_failed)

        self.setObjectName("RootWindow")
        self.setWindowTitle("Stream Controller")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)

        central_widget = QWidget()
        central_widget.setObjectName("AppCanvas")
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_requested.connect(self.show_page)
        root_layout.addWidget(self._sidebar)

        content_container = QWidget()
        content_container.setObjectName("ContentSurface")
        root_layout.addWidget(content_container, 1)

        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(28, 24, 28, 20)
        content_layout.setSpacing(20)

        self._header_card = self._build_header()
        content_layout.addWidget(self._header_card)

        self._content_stack = QStackedWidget()
        content_layout.addWidget(self._content_stack, 1)

        self._dashboard_page = DashboardPage()
        self._plugin_catalog_page = PluginCatalogPage()
        self._plugin_catalog_page.load_requested.connect(self._load_plugin_from_ui)
        self._plugin_catalog_page.unload_requested.connect(self._unload_plugin_from_ui)
        self._settings_page = PluginSettingsPage()
        self._stage_view_page = StageViewPage(registry=app_context.stage_registry)
        self._settings_page.save_requested.connect(self._save_plugin_settings_from_ui)
        self._settings_page.reset_requested.connect(self._reset_plugin_settings_from_ui)
        self._settings_page.hotkeys_save_requested.connect(self._save_hotkeys_from_ui)
        self._settings_page.hotkeys_reset_requested.connect(self._reset_hotkeys_from_ui)

        self._register_page(
            page_id="dashboard",
            title="Dashboard",
            subtitle="A polished overview of the base runtime and plugin activity.",
            badge="Home",
            widget=self._dashboard_page,
        )
        self._register_page(
            page_id="plugins",
            title="Plugins",
            subtitle="Inspect loaded extensions, manifests, and startup issues.",
            badge="Runtime",
            widget=self._plugin_catalog_page,
        )
        self._register_page(
            page_id="settings",
            title="Settings",
            subtitle="Configure the platform foundation and future plugin preferences.",
            badge="Preferences",
            widget=self._settings_page,
        )
        self._register_page(
            page_id="stage_view",
            title="Stage View",
            subtitle="Freeform drag-and-drop layout. Arrange plugin panels however you want, then fullscreen it on your second monitor.",
            badge="Stage",
            widget=self._stage_view_page,
        )

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Ready")

        self._restore_session()

    def register_plugin_page(
        self,
        plugin_id: str,
        page_id: str,
        title: str,
        subtitle: str,
        widget: QWidget,
        help_text: str = "",
    ) -> None:
        self._register_page(
            page_id=page_id,
            title=title,
            subtitle=subtitle,
            badge="Plugin",
            widget=widget,
            owner_plugin_id=plugin_id,
            plugin_nav=True,
            help_text=help_text,
        )

    def register_dashboard_panel(self, plugin_id: str, title: str, description: str, widget: QWidget) -> None:
        self._dashboard_page.add_plugin_panel(
            plugin_id=plugin_id,
            title=title,
            description=description,
            widget=widget,
        )

    def unregister_plugin_ui(self, plugin_id: str) -> None:
        current_widget = self._content_stack.currentWidget()
        removed_current_page = False

        page_ids_to_remove = [
            page_id for page_id, owner_plugin_id in self._page_owners.items() if owner_plugin_id == plugin_id
        ]
        for page_id in page_ids_to_remove:
            widget = self._pages.pop(page_id, None)
            self._page_headers.pop(page_id, None)
            self._page_owners.pop(page_id, None)
            if widget is None:
                continue

            if current_widget is widget:
                removed_current_page = True

            self._content_stack.removeWidget(widget)
            widget.deleteLater()
            self._sidebar.remove_plugin_page(page_id)

        self._dashboard_page.remove_plugin_panels(plugin_id)

        if removed_current_page:
            self.show_page("plugins")

    def refresh_runtime_state(self) -> None:
        actions = self._app_context.action_registry.list_actions()
        hotkey_bindings = self._app_context.hotkey_manager.get_binding_map(actions)
        self.refresh_action_state(actions=actions, hotkey_bindings=hotkey_bindings)
        self._plugin_catalog_page.set_plugins(
            discovered_manifests=self._app_context.plugin_manager.discovered_manifests,
            loaded_plugins=self._app_context.plugin_manager.get_loaded_plugins(),
            failed_plugins=self._app_context.plugin_manager.get_failed_plugins(),
        )
        self._settings_page.set_hotkeys(actions=actions, hotkey_bindings=hotkey_bindings)
        self._settings_page.set_settings(
            settings=self._app_context.settings_registry.list_settings(),
            settings_manager=self._app_context.settings_manager,
        )

    def refresh_action_state(
        self,
        actions: list[ActionDefinition] | None = None,
        hotkey_bindings: dict[str, HotkeyBinding] | None = None,
    ) -> None:
        actions = actions or self._app_context.action_registry.list_actions()
        hotkey_bindings = hotkey_bindings or self._app_context.hotkey_manager.get_binding_map(actions)
        self._app_context.hotkey_manager.sync_actions(actions)

        loaded_plugins = self._app_context.plugin_manager.get_loaded_plugins()
        failed_plugins = self._app_context.plugin_manager.get_failed_plugins()
        command_count = len(self._app_context.command_registry.list_commands())
        active_hotkeys = sum(
            1
            for binding in hotkey_bindings.values()
            if binding.shortcut is not None and not binding.is_conflicted
        )

        self._settings_page.set_hotkeys(actions=actions, hotkey_bindings=hotkey_bindings)
        self._dashboard_page.set_runtime_summary(
            loaded_plugins=len(loaded_plugins),
            failed_plugins=len(failed_plugins),
            action_count=len(actions),
        )
        plugin_count = len(loaded_plugins)
        plugin_label = "plugin" if plugin_count == 1 else "plugins"
        self._runtime_badge.setText(f"{plugin_count} Active")
        if failed_plugins:
            issue_label = "issue" if len(failed_plugins) == 1 else "issues"
            self._runtime_detail.setText(f"{len(failed_plugins)} plugin {issue_label} need attention")
        else:
            action_label = "action" if len(actions) == 1 else "actions"
            command_label = "command" if command_count == 1 else "commands"
            hotkey_label = "hotkey" if active_hotkeys == 1 else "hotkeys"
            self._runtime_detail.setText(
                f"{plugin_count} {plugin_label}, {len(actions)} {action_label}, {command_count} {command_label}, and {active_hotkeys} {hotkey_label} registered"
            )

    def set_status_message(self, message: str, timeout_ms: int = 0) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def show_page(self, page_id: str) -> None:
        widget = self._pages.get(page_id)
        if widget is None:
            return

        page_index = self._content_stack.indexOf(widget)
        if page_index < 0:
            return

        self._content_stack.setCurrentIndex(page_index)
        self._sidebar.set_active_page(page_id)

        title, subtitle, badge, help_text = self._page_headers[page_id]
        self._header_title.setText(title)
        self._header_subtitle.setText(subtitle)
        self._header_badge.setText(badge)
        self._header_help_btn.setVisible(bool(help_text))
        self._header_help_btn.setProperty("help_text", help_text)
        self._header_help_btn.setProperty("help_title", title)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("HeaderCard")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(20)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        self._header_title = QLabel()
        self._header_title.setObjectName("HeaderTitle")
        self._header_subtitle = QLabel()
        self._header_subtitle.setObjectName("HeaderSubtitle")
        self._header_subtitle.setWordWrap(True)

        text_layout.addWidget(self._header_title)
        text_layout.addWidget(self._header_subtitle)
        layout.addLayout(text_layout, 1)

        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(6)

        self._header_badge = create_badge("Home", "accent")
        self._runtime_badge = create_badge("0 Active", "neutral")
        self._runtime_detail = QLabel("Runtime metrics update as plugins register.")
        self._runtime_detail.setObjectName("MetaText")
        self._runtime_detail.setWordWrap(True)

        self._header_help_btn = QPushButton("? Help")
        self._header_help_btn.setObjectName("HelpButton")
        self._header_help_btn.setFixedHeight(28)
        self._header_help_btn.setVisible(False)
        self._header_help_btn.clicked.connect(self._show_help_dialog)

        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)
        badges_row.addWidget(self._header_badge)
        badges_row.addWidget(self._runtime_badge)
        badges_row.addWidget(self._header_help_btn)
        badges_row.addStretch(1)

        meta_layout.addLayout(badges_row)
        meta_layout.addWidget(self._runtime_detail)
        layout.addLayout(meta_layout, 1)

        return header

    def _show_help_dialog(self) -> None:
        title = self._header_help_btn.property("help_title") or "Help"
        text = self._header_help_btn.property("help_text") or ""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{title} — How to use")
        dlg.setMinimumWidth(480)
        dlg.setMaximumWidth(640)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextFormat(Qt.RichText)
        content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        content.setObjectName("HelpContent")
        content.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(content)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.accept)

        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        dlg.exec()

    def _register_page(
        self,
        page_id: str,
        title: str,
        subtitle: str,
        badge: str,
        widget: QWidget,
        owner_plugin_id: str | None = None,
        plugin_nav: bool = False,
        help_text: str = "",
    ) -> None:
        if page_id in self._pages:
            raise ValueError(f"Page '{page_id}' is already registered.")

        self._pages[page_id] = widget
        self._page_headers[page_id] = (title, subtitle, badge, help_text)
        self._page_owners[page_id] = owner_plugin_id
        self._content_stack.addWidget(widget)

        if plugin_nav:
            self._sidebar.add_plugin_page(page_id=page_id, title=title)

    def _load_plugin_from_ui(self, plugin_id: str) -> None:
        success = self._app_context.plugin_manager.load_plugin(plugin_id)
        self.refresh_runtime_state()

        if success:
            self.set_status_message(f"Loaded plugin '{plugin_id}'.", timeout_ms=3000)
            return

        failed_plugin = self._app_context.plugin_manager.get_failed_plugin(plugin_id)
        reason = failed_plugin.reason if failed_plugin is not None else "Unknown load error."
        self.set_status_message(f"Could not load '{plugin_id}': {reason}", timeout_ms=5000)

    def _unload_plugin_from_ui(self, plugin_id: str) -> None:
        success = self._app_context.plugin_manager.unload_plugin(plugin_id)
        self.refresh_runtime_state()

        if success:
            self.set_status_message(f"Unloaded plugin '{plugin_id}'.", timeout_ms=3000)
            return

        failed_plugin = self._app_context.plugin_manager.get_failed_plugin(plugin_id)
        reason = failed_plugin.reason if failed_plugin is not None else "Unknown unload error."
        self.set_status_message(f"Could not unload '{plugin_id}': {reason}", timeout_ms=5000)

    def _execute_action_from_ui(self, action_id: str) -> None:
        try:
            self._app_context.action_registry.execute(action_id)
        except Exception as exc:
            self.set_status_message(f"Could not execute '{action_id}': {exc}", timeout_ms=5000)

    def _save_plugin_settings_from_ui(self, plugin_id: str, values: object) -> None:
        if not isinstance(values, dict):
            self.set_status_message("Could not save settings: invalid editor payload.", timeout_ms=5000)
            return

        try:
            normalized = self._app_context.settings_registry.validate_plugin_values(plugin_id, values)
            self._app_context.settings_manager.set_plugin_settings(plugin_id, normalized)
            self._app_context.event_bus.emit(
                "plugin.settings.changed",
                {"plugin_id": plugin_id, "values": dict(normalized)},
            )
            self.refresh_runtime_state()
            self.set_status_message(f"Saved settings for '{plugin_id}'.", timeout_ms=3000)
        except Exception as exc:
            self.set_status_message(f"Could not save settings for '{plugin_id}': {exc}", timeout_ms=5000)

    def _reset_plugin_settings_from_ui(self, plugin_id: str) -> None:
        self._app_context.settings_registry.reset_plugin_settings(
            settings_manager=self._app_context.settings_manager,
            plugin_id=plugin_id,
        )
        self._app_context.event_bus.emit(
            "plugin.settings.reset",
            {"plugin_id": plugin_id},
        )
        self.refresh_runtime_state()
        self.set_status_message(f"Reset settings for '{plugin_id}' to defaults.", timeout_ms=3000)

    def _save_hotkeys_from_ui(self, values: object) -> None:
        if not isinstance(values, dict):
            self.set_status_message("Could not save hotkeys: invalid editor payload.", timeout_ms=5000)
            return

        try:
            self._app_context.hotkey_manager.save_bindings(
                {str(action_id): None if shortcut is None else str(shortcut) for action_id, shortcut in values.items()}
            )
            self.refresh_runtime_state()
            self.set_status_message("Saved hotkey assignments.", timeout_ms=3000)
        except Exception as exc:
            self.set_status_message(f"Could not save hotkeys: {exc}", timeout_ms=5000)

    def _reset_hotkeys_from_ui(self, action_ids: object) -> None:
        normalized_action_ids = [str(action_id) for action_id in action_ids] if isinstance(action_ids, list) else None
        self._app_context.hotkey_manager.reset_bindings(action_ids=normalized_action_ids)
        self.refresh_runtime_state()
        self.set_status_message("Hotkeys reset to their suggested defaults.", timeout_ms=3000)

    def _on_action_executed(self, payload: object) -> None:
        self.refresh_action_state()

    def _on_hotkey_execution_failed(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self.set_status_message("A hotkey could not be executed.", timeout_ms=5000)
            return

        action_id = str(payload.get("action_id", "unknown"))
        error = str(payload.get("error", "Unknown error."))
        self.set_status_message(f"Could not execute hotkey for '{action_id}': {error}", timeout_ms=5000)

    # ── session persistence ───────────────────────────────────────────────

    def _settings(self) -> QSettings:
        return QSettings("StreamShift", "StreamController")

    def _restore_session(self) -> None:
        s = self._settings()
        geom: QByteArray = s.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1440, 900)
        last_page: str = s.value("window/last_page", "dashboard")
        self.show_page(last_page if last_page in self._pages else "dashboard")

    def _save_session(self) -> None:
        s = self._settings()
        s.setValue("window/geometry", self.saveGeometry())
        current = self._content_stack.currentWidget()
        for pid, widget in self._pages.items():
            if widget is current:
                s.setValue("window/last_page", pid)
                break

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_session()
        self._app_context.plugin_manager.save_enabled_plugin_ids()
        super().closeEvent(event)
