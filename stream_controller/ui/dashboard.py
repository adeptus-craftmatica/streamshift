from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from stream_controller.ui.theme import create_badge, create_card


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._plugin_panel_cards: dict[str, list[QFrame]] = {}

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

        hero_card, hero_body = create_card()
        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)
        badges_row.addWidget(create_badge("Base Application", "accent"))
        badges_row.addWidget(create_badge("Plugin Ready", "neutral"))
        badges_row.addStretch(1)
        hero_body.addLayout(badges_row)

        hero_title = QLabel("A modern control foundation for stream creators.")
        hero_title.setObjectName("HeroTitle")
        hero_title.setWordWrap(True)
        hero_description = QLabel(
            "This first release focuses on architecture, polish, and extensibility so future plugins "
            "can add tools like overlays, timers, automation, and Twitch workflows without reshaping the app."
        )
        hero_description.setObjectName("HeroDescription")
        hero_description.setWordWrap(True)
        hero_body.addWidget(hero_title)
        hero_body.addWidget(hero_description)
        self._content_layout.addWidget(hero_card)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(18)
        self._plugins_metric = self._create_metric_card("Loaded plugins", "0")
        self._actions_metric = self._create_metric_card("Deck actions", "0")
        self._health_metric = self._create_metric_card("Runtime health", "Ready")
        metrics_layout.addWidget(self._plugins_metric["card"])
        metrics_layout.addWidget(self._actions_metric["card"])
        metrics_layout.addWidget(self._health_metric["card"])
        self._content_layout.addLayout(metrics_layout)

        quickstart_card, quickstart_body = create_card(
            "What this base app supports",
            "The shell is intentionally lean, but it already has the moving parts needed for real plugin-driven growth.",
        )
        for line in (
            "Dynamic plugin discovery and registration from the local plugins directory.",
            "Action registration for a shared control deck that future stream integrations can target.",
            "Command execution through a central registry for future hotkeys, macros, and actions.",
            "An event bus for cross-plugin communication and app lifecycle hooks.",
            "A polished navigation shell with room for dedicated plugin workspaces.",
        ):
            item = QLabel(line)
            item.setObjectName("MetaText")
            item.setWordWrap(True)
            quickstart_body.addWidget(item)
        self._content_layout.addWidget(quickstart_card)

        plugin_section_title = QLabel("Plugin Activity")
        plugin_section_title.setObjectName("SectionTitle")
        self._content_layout.addWidget(plugin_section_title)

        self._plugin_panels_layout = QVBoxLayout()
        self._plugin_panels_layout.setSpacing(18)
        self._content_layout.addLayout(self._plugin_panels_layout)

        self._plugin_empty_state = QLabel(
            "No plugins have contributed dashboard panels yet. Installed extensions can surface quick actions and status cards here."
        )
        self._plugin_empty_state.setObjectName("EmptyState")
        self._plugin_empty_state.setWordWrap(True)
        self._content_layout.addWidget(self._plugin_empty_state)

        self._content_layout.addStretch(1)

    def add_plugin_panel(self, plugin_id: str, title: str, description: str, widget: QWidget) -> None:
        card, body = create_card(title, description)
        body.addWidget(widget)
        self._plugin_panels_layout.addWidget(card)
        self._plugin_panel_cards.setdefault(plugin_id, []).append(card)
        self._update_plugin_empty_state()

    def remove_plugin_panels(self, plugin_id: str) -> None:
        for card in self._plugin_panel_cards.pop(plugin_id, []):
            self._plugin_panels_layout.removeWidget(card)
            card.deleteLater()
        self._update_plugin_empty_state()

    def set_runtime_summary(self, loaded_plugins: int, failed_plugins: int, action_count: int) -> None:
        self._plugins_metric["value"].setText(str(loaded_plugins))
        self._actions_metric["value"].setText(str(action_count))

        health_text = "Healthy" if failed_plugins == 0 else "Attention"
        self._health_metric["value"].setText(health_text)
        self._health_metric["label"].setText(
            "Runtime health" if failed_plugins == 0 else f"{failed_plugins} plugin issue(s) detected"
        )

    def _create_metric_card(self, label: str, value: str) -> dict[str, QWidget | QLabel]:
        card, body = create_card()
        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        label_text = QLabel(label)
        label_text.setObjectName("MetricLabel")
        label_text.setWordWrap(True)

        body.addWidget(value_label)
        body.addWidget(label_text)
        body.addStretch(1)

        return {"card": card, "value": value_label, "label": label_text}

    def _update_plugin_empty_state(self) -> None:
        if self._plugin_panel_cards:
            self._plugin_empty_state.hide()
        else:
            self._plugin_empty_state.show()
