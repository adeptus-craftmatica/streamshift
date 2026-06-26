from __future__ import annotations

from collections import defaultdict
from typing import Any

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stream_controller.core.action_registry import ActionDefinition
from stream_controller.core.hotkey_manager import HotkeyBinding
from stream_controller.core.settings_manager import SettingsManager
from stream_controller.core.settings_registry import SettingDefinition
from stream_controller.ui.theme import create_badge, create_card
from stream_controller.ui.ui_utils import clear_layout


class PluginSettingsPage(QWidget):
    save_requested = Signal(str, object)
    reset_requested = Signal(str)
    hotkeys_save_requested = Signal(object)
    hotkeys_reset_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._plugin_fields: dict[str, dict[str, QWidget]] = {}
        self._plugin_definitions: dict[str, list[SettingDefinition]] = {}
        self._hotkey_actions: dict[str, ActionDefinition] = {}
        self._hotkey_editors: dict[str, QKeySequenceEdit] = {}
        self._hotkey_rows: dict[str, QFrame] = {}
        self._hotkey_hints: dict[str, QLabel] = {}
        self._hotkey_conflicts: dict[str, QLabel] = {}
        self._hotkey_bindings: dict[str, HotkeyBinding] = {}

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
            "Settings",
            "Configure action shortcuts and plugin-defined preferences from one polished workspace.",
        )
        intro_meta = QLabel(
            "Hotkeys are action-driven and persist between launches. Plugin settings remain self-contained and only appear when a loaded plugin declares them."
        )
        intro_meta.setObjectName("MetaText")
        intro_meta.setWordWrap(True)
        intro_body.addWidget(intro_meta)
        self._content_layout.addWidget(intro_card)

        self._hotkeys_card = self._build_hotkeys_card()
        self._content_layout.addWidget(self._hotkeys_card)

        self._raid_list_card = self._build_raid_list_card()
        self._content_layout.addWidget(self._raid_list_card)

        self._sections_layout = QVBoxLayout()
        self._sections_layout.setSpacing(20)
        self._content_layout.addLayout(self._sections_layout)

        self._empty_state_card, empty_body = create_card(
            "No plugin settings yet",
            "Load a plugin that declares configuration fields to start customizing its behavior.",
        )
        empty_label = QLabel(
            "Settings are plugin-driven, so this page will grow automatically as integrations add schemas for credentials, timing, scene names, overlays, and more."
        )
        empty_label.setObjectName("MetaText")
        empty_label.setWordWrap(True)
        empty_body.addWidget(empty_label)
        self._content_layout.addWidget(self._empty_state_card)

        self._content_layout.addStretch(1)

    def set_hotkeys(
        self,
        actions: list[ActionDefinition],
        hotkey_bindings: dict[str, HotkeyBinding],
    ) -> None:
        clear_layout(self._hotkey_rows_layout)
        self._hotkey_actions = {action.action_id: action for action in actions}
        self._hotkey_editors.clear()
        self._hotkey_rows.clear()
        self._hotkey_hints.clear()
        self._hotkey_conflicts.clear()
        self._hotkey_bindings = dict(hotkey_bindings)

        if not actions:
            self._hotkey_empty_state.show()
            self._hotkey_summary_label.setText(
                "No actions are loaded yet, so there are no shortcuts to configure."
            )
            self._hotkey_save_button.setEnabled(False)
            self._hotkey_reset_button.setEnabled(False)
            return

        self._hotkey_empty_state.hide()
        self._hotkey_save_button.setEnabled(True)
        self._hotkey_reset_button.setEnabled(True)

        for action in actions:
            binding = hotkey_bindings.get(action.action_id)
            self._hotkey_rows_layout.addWidget(self._create_hotkey_row(action, binding))

        self._update_hotkey_feedback()

    def set_settings(
        self,
        settings: list[SettingDefinition],
        settings_manager: SettingsManager,
    ) -> None:
        clear_layout(self._sections_layout)
        self._plugin_fields.clear()
        self._plugin_definitions.clear()

        grouped: dict[str, list[SettingDefinition]] = defaultdict(list)
        for definition in settings:
            if definition.plugin_id is None:
                continue
            grouped[definition.plugin_id].append(definition)

        if not grouped:
            self._empty_state_card.show()
            return

        self._empty_state_card.hide()
        for plugin_id, definitions in sorted(
            grouped.items(),
            key=lambda item: (item[1][0].plugin_name or item[0]).lower(),
        ):
            self._plugin_definitions[plugin_id] = definitions
            self._plugin_fields[plugin_id] = {}
            self._sections_layout.addWidget(
                self._build_plugin_card(
                    plugin_id=plugin_id,
                    definitions=definitions,
                    settings_manager=settings_manager,
                )
            )

    def current_plugin_values(self, plugin_id: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for definition in self._plugin_definitions.get(plugin_id, []):
            editor = self._plugin_fields.get(plugin_id, {}).get(definition.setting_key)
            if editor is None:
                continue
            values[definition.setting_key] = self._read_editor_value(definition, editor)
        return values

    def current_hotkey_values(self) -> dict[str, str | None]:
        values: dict[str, str | None] = {}
        for action_id, editor in self._hotkey_editors.items():
            portable_text = editor.keySequence().toString(QKeySequence.PortableText).strip()
            values[action_id] = portable_text or None
        return values

    def _build_hotkeys_card(self) -> QFrame:
        card, body = create_card(
            "Hotkeys",
            "Assign keyboard shortcuts to action tiles so the control deck works even when your hands are off the mouse.",
        )

        self._hotkey_summary_label = QLabel("Shortcuts will appear here as actions are loaded.")
        self._hotkey_summary_label.setObjectName("MetaText")
        self._hotkey_summary_label.setWordWrap(True)
        body.addWidget(self._hotkey_summary_label)

        self._hotkey_rows_layout = QVBoxLayout()
        self._hotkey_rows_layout.setSpacing(14)
        body.addLayout(self._hotkey_rows_layout)

        self._hotkey_empty_state = QLabel(
            "Load a plugin that registers actions to start assigning keyboard shortcuts."
        )
        self._hotkey_empty_state.setObjectName("MetaText")
        self._hotkey_empty_state.setWordWrap(True)
        body.addWidget(self._hotkey_empty_state)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self._hotkey_save_button = QPushButton("Save Hotkeys")
        self._hotkey_save_button.setObjectName("PrimaryButton")
        self._hotkey_save_button.clicked.connect(
            lambda: self.hotkeys_save_requested.emit(self.current_hotkey_values())
        )

        self._hotkey_reset_button = QPushButton("Reset to Suggested")
        self._hotkey_reset_button.setObjectName("SecondaryButton")
        self._hotkey_reset_button.clicked.connect(
            lambda: self.hotkeys_reset_requested.emit(list(self._hotkey_actions))
        )

        actions_row.addWidget(self._hotkey_save_button)
        actions_row.addWidget(self._hotkey_reset_button)
        actions_row.addStretch(1)
        body.addLayout(actions_row)

        return card

    def _build_raid_list_card(self) -> QFrame:
        card, body = create_card(
            "Raid List",
            "Save your favourite raid targets here. They'll appear in the dropdown when building a Raid Channel macro step.",
        )

        self._raid_list_widget = QListWidget()
        self._raid_list_widget.setObjectName("MacroStepsList")
        self._raid_list_widget.setMaximumHeight(200)
        body.addWidget(self._raid_list_widget)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._raid_input = QLineEdit()
        self._raid_input.setObjectName("OverlayTextField")
        self._raid_input.setPlaceholderText("Channel name (e.g. streamername)")
        self._raid_input.returnPressed.connect(self._raid_add)
        input_row.addWidget(self._raid_input, 1)

        add_btn = QPushButton("Add")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._raid_add)
        input_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("TimerDangerBtn")
        remove_btn.clicked.connect(self._raid_remove)
        input_row.addWidget(remove_btn)

        body.addLayout(input_row)

        self._raid_reload()
        return card

    def _raid_reload(self) -> None:
        try:
            from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore
            targets = RaidTargetStore.load()
        except Exception:
            targets = []
        self._raid_list_widget.clear()
        for name in targets:
            item = QListWidgetItem(name)
            self._raid_list_widget.addItem(item)

    def _raid_add(self) -> None:
        name = self._raid_input.text().strip().lstrip("@").lower()
        if not name:
            return
        try:
            from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore
            RaidTargetStore.add(name)
        except Exception:
            pass
        self._raid_input.clear()
        self._raid_reload()

    def _raid_remove(self) -> None:
        item = self._raid_list_widget.currentItem()
        if item is None:
            return
        try:
            from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore
            RaidTargetStore.remove(item.text())
        except Exception:
            pass
        self._raid_reload()

    def _build_plugin_card(
        self,
        plugin_id: str,
        definitions: list[SettingDefinition],
        settings_manager: SettingsManager,
    ) -> QFrame:
        plugin_name = definitions[0].plugin_name or plugin_id
        card, body = create_card(
            plugin_name,
            f"Plugin-specific configuration for {plugin_name}.",
        )

        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        info_row.addWidget(create_badge(f"{len(definitions)} Fields", "accent"))
        info_row.addWidget(create_badge(plugin_id, "neutral"))
        info_row.addStretch(1)
        body.addLayout(info_row)

        for definition in definitions:
            current_value = settings_manager.get_plugin_setting(
                plugin_id=plugin_id,
                setting_key=definition.setting_key,
                default=definition.default,
            )
            editor = self._create_editor(definition, current_value)
            self._plugin_fields[plugin_id][definition.setting_key] = editor
            body.addWidget(self._create_setting_row(definition, editor))

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        save_button = QPushButton("Save Settings")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(
            lambda checked=False, pid=plugin_id: self.save_requested.emit(pid, self.current_plugin_values(pid))
        )

        reset_button = QPushButton("Reset to Defaults")
        reset_button.setObjectName("SecondaryButton")
        reset_button.clicked.connect(lambda checked=False, pid=plugin_id: self.reset_requested.emit(pid))

        actions_row.addWidget(save_button)
        actions_row.addWidget(reset_button)
        actions_row.addStretch(1)
        body.addLayout(actions_row)

        return card

    def _create_hotkey_row(
        self,
        action: ActionDefinition,
        binding: HotkeyBinding | None,
    ) -> QFrame:
        row = QFrame()
        row.setObjectName("SettingRow")

        layout = QVBoxLayout(row)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        title = QLabel(action.title)
        title.setObjectName("SettingLabel")
        title.setWordWrap(True)

        title_row.addWidget(title, 1)
        if binding is not None and binding.has_user_override:
            title_row.addWidget(create_badge("Custom", "success"))
        elif binding is not None and binding.default_display_shortcut:
            title_row.addWidget(create_badge("Suggested", "neutral"))
        title_row.addStretch(1)

        metadata = QLabel(
            f"{action.plugin_name or action.plugin_id or 'Core'} plugin • {action.group} group"
        )
        metadata.setObjectName("SettingHelp")
        metadata.setWordWrap(True)

        description = QLabel(action.description)
        description.setObjectName("SettingHelp")
        description.setWordWrap(True)

        hint = QLabel(self._build_hotkey_hint(binding))
        hint.setObjectName("SettingHelp")
        hint.setWordWrap(True)

        editor_row = QHBoxLayout()
        editor_row.setSpacing(12)

        editor = QKeySequenceEdit()
        editor.setProperty("settingsEditor", True)
        if binding is not None and binding.shortcut:
            editor.setKeySequence(QKeySequence.fromString(binding.shortcut, QKeySequence.PortableText))
        editor.editingFinished.connect(self._update_hotkey_feedback)
        editor.keySequenceChanged.connect(self._update_hotkey_feedback)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("SecondaryButton")
        clear_button.clicked.connect(lambda: self._clear_hotkey(action.action_id))

        editor_row.addWidget(editor, 1)
        editor_row.addWidget(clear_button)

        conflict_label = QLabel("")
        conflict_label.setObjectName("HotkeyConflict")
        conflict_label.setWordWrap(True)
        conflict_label.hide()

        layout.addLayout(title_row)
        layout.addWidget(metadata)
        layout.addWidget(description)
        layout.addWidget(hint)
        layout.addLayout(editor_row)
        layout.addWidget(conflict_label)

        self._hotkey_editors[action.action_id] = editor
        self._hotkey_rows[action.action_id] = row
        self._hotkey_hints[action.action_id] = hint
        self._hotkey_conflicts[action.action_id] = conflict_label
        return row

    def _create_setting_row(self, definition: SettingDefinition, editor: QWidget) -> QFrame:
        row = QFrame()
        row.setObjectName("SettingRow")

        layout = QVBoxLayout(row)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        title = QLabel(definition.label)
        title.setObjectName("SettingLabel")
        title.setWordWrap(True)

        description = QLabel(definition.description or f"{definition.field_type.title()} setting")
        description.setObjectName("SettingHelp")
        description.setWordWrap(True)

        title_row.addWidget(title, 1)
        if definition.required:
            title_row.addWidget(create_badge("Required", "accent"))
        title_row.addStretch(1)

        if definition.field_type == "toggle":
            editor_container = QWidget()
            editor_layout = QHBoxLayout(editor_container)
            editor_layout.setContentsMargins(0, 0, 0, 0)
            editor_layout.setSpacing(0)
            editor_layout.addWidget(editor, 0, Qt.AlignLeft)
            editor_layout.addStretch(1)
            editor_widget = editor_container
        else:
            editor_widget = editor
            editor.setProperty("settingsEditor", True)

        layout.addLayout(title_row)
        layout.addWidget(description)
        layout.addWidget(editor_widget)
        return row

    def _create_editor(self, definition: SettingDefinition, current_value: Any) -> QWidget:
        if definition.field_type in {"text", "secret"}:
            editor = QLineEdit()
            if definition.placeholder:
                editor.setPlaceholderText(definition.placeholder)
            if current_value is not None:
                editor.setText(str(current_value))
            if definition.field_type == "secret":
                editor.setEchoMode(QLineEdit.Password)
            return editor

        if definition.field_type == "toggle":
            editor = QCheckBox("Enabled")
            editor.setChecked(bool(current_value))
            return editor

        if definition.field_type == "select":
            editor = QComboBox()
            for option in definition.options:
                editor.addItem(option.label, option.value)
            current_index = editor.findData(current_value)
            editor.setCurrentIndex(max(current_index, 0))
            return editor

        if definition.field_type == "number":
            if definition.expects_integer():
                editor = QSpinBox()
                if definition.minimum is not None:
                    editor.setMinimum(int(definition.minimum))
                if definition.maximum is not None:
                    editor.setMaximum(int(definition.maximum))
                if definition.step is not None:
                    editor.setSingleStep(int(definition.step))
                editor.setValue(int(current_value if current_value is not None else definition.default or 0))
                return editor

            editor = QDoubleSpinBox()
            editor.setDecimals(2)
            if definition.minimum is not None:
                editor.setMinimum(float(definition.minimum))
            if definition.maximum is not None:
                editor.setMaximum(float(definition.maximum))
            if definition.step is not None:
                editor.setSingleStep(float(definition.step))
            editor.setValue(float(current_value if current_value is not None else definition.default or 0.0))
            return editor

        raise ValueError(f"Unsupported settings field type '{definition.field_type}'.")

    def _read_editor_value(self, definition: SettingDefinition, editor: QWidget) -> Any:
        if definition.field_type in {"text", "secret"} and isinstance(editor, QLineEdit):
            return editor.text()
        if definition.field_type == "toggle" and isinstance(editor, QCheckBox):
            return editor.isChecked()
        if definition.field_type == "select" and isinstance(editor, QComboBox):
            return editor.currentData()
        if definition.field_type == "number" and isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        return None

    def _update_hotkey_feedback(self) -> None:
        action_ids_by_shortcut: dict[str, list[str]] = defaultdict(list)
        hotkey_values = self.current_hotkey_values()

        for action_id, shortcut in hotkey_values.items():
            if shortcut:
                action_ids_by_shortcut[shortcut].append(action_id)

        conflict_count = 0
        assigned_count = 0

        for action_id, editor in self._hotkey_editors.items():
            shortcut = hotkey_values.get(action_id)
            row = self._hotkey_rows[action_id]
            conflict_label = self._hotkey_conflicts[action_id]
            binding = self._hotkey_bindings.get(action_id)

            has_conflict = bool(shortcut and len(action_ids_by_shortcut.get(shortcut, [])) > 1)
            if shortcut:
                assigned_count += 1

            if has_conflict:
                conflicting_titles = ", ".join(
                    self._hotkey_actions[other_action_id].title
                    for other_action_id in action_ids_by_shortcut[shortcut]
                    if other_action_id != action_id
                )
                conflict_label.setText(f"Conflicts with: {conflicting_titles}")
                conflict_label.show()
                conflict_count += 1
            else:
                conflict_label.hide()
                conflict_label.setText("")

            row.setProperty("hotkeyConflict", has_conflict)
            self._refresh_widget_style(row)
            self._hotkey_hints[action_id].setText(
                self._build_hotkey_hint(binding, override_shortcut=shortcut)
            )

        if not self._hotkey_actions:
            self._hotkey_summary_label.setText(
                "No actions are loaded yet, so there are no shortcuts to configure."
            )
            self._hotkey_save_button.setEnabled(False)
            self._hotkey_reset_button.setEnabled(False)
            return

        if conflict_count:
            self._hotkey_summary_label.setText(
                f"{conflict_count} shortcut conflict(s) need attention before you can save."
            )
            self._hotkey_save_button.setEnabled(False)
        else:
            action_count = len(self._hotkey_actions)
            self._hotkey_summary_label.setText(
                f"{assigned_count} shortcut(s) assigned across {action_count} loaded action(s)."
            )
            self._hotkey_save_button.setEnabled(True)

        self._hotkey_reset_button.setEnabled(bool(self._hotkey_actions))

    def _clear_hotkey(self, action_id: str) -> None:
        editor = self._hotkey_editors.get(action_id)
        if editor is None:
            return

        blocker = QSignalBlocker(editor)
        try:
            editor.clear()
        finally:
            del blocker
        self._update_hotkey_feedback()

    def _build_hotkey_hint(
        self,
        binding: HotkeyBinding | None,
        override_shortcut: str | None = None,
    ) -> str:
        if binding is None:
            return "No suggested shortcut is available for this action yet."

        current_shortcut = override_shortcut if override_shortcut is not None else binding.shortcut
        current_display = (
            QKeySequence.fromString(current_shortcut, QKeySequence.PortableText).toString(QKeySequence.NativeText)
            if current_shortcut
            else ""
        )
        if current_display:
            return f"Assigned shortcut: {current_display}"
        if binding.default_display_shortcut:
            return f"Suggested shortcut: {binding.default_display_shortcut}"
        return "No shortcut assigned. This action will only be available from the UI until you add one."

    @staticmethod
    def _refresh_widget_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
