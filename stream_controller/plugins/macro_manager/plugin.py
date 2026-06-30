from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.macro_manager.macro_engine import MacroEngine
from stream_controller.plugins.macro_manager.macro_repository import MacroRepository

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "macro_manager"


class MacroManagerPlugin:
    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo: MacroRepository | None = None
        self._engine: MacroEngine | None = None
        self._page_widget = None
        self._registered_macro_action_ids: list[str] = []
        self._registered_stage_widget_ids: list[str] = []

    def register(self, app_context: AppContext) -> None:
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo = MacroRepository(_DATA_DIR / "macros.json")
        self._engine = MacroEngine(
            repo=self._repo,
            action_registry=app_context.action_registry,
            hotkey_manager=app_context.hotkey_manager,
            app_context=app_context,
        )

        app_context.register_action(
            action_id="macro.open_panel",
            title="Open Macro Manager",
            description="Navigate to the Macro Manager plugin page.",
            execute=self._open_panel,
            icon="▶",
            page="Macro",
            group="Macro Manager",
        )

        self._register_macro_actions(app_context)
        self._register_page(app_context)
        self.refresh_stage_widgets()

        app_context.set_status("Macro Manager loaded.", timeout_ms=3000)
        logger.info("Macro Manager plugin registered")

    def unregister(self, app_context: AppContext) -> None:
        for action_id in list(self._registered_macro_action_ids):
            try:
                app_context.unregister_action(action_id)
            except Exception:
                pass
        self._registered_macro_action_ids.clear()

        for widget_id in list(self._registered_stage_widget_ids):
            try:
                app_context.unregister_stage_widget(widget_id)
            except Exception:
                pass
        self._registered_stage_widget_ids.clear()

        try:
            app_context.unregister_action("macro.open_panel")
        except Exception:
            pass

        self._app_context = None
        self._repo = None
        self._engine = None
        self._page_widget = None
        logger.info("Macro Manager plugin unregistered")

    def refresh_macro_actions(self) -> None:
        if self._app_context is None:
            return
        for action_id in list(self._registered_macro_action_ids):
            try:
                self._app_context.unregister_action(action_id)
            except Exception:
                pass
        self._registered_macro_action_ids.clear()
        self._register_macro_actions(self._app_context)
        self.refresh_stage_widgets()

    def refresh_stage_widgets(self) -> None:
        if self._app_context is None or self._repo is None or self._engine is None:
            return

        for widget_id in list(self._registered_stage_widget_ids):
            try:
                self._app_context.unregister_stage_widget(widget_id)
            except Exception:
                pass
        self._registered_stage_widget_ids.clear()

        from stream_controller.plugins.macro_manager.ui.macro_tile import MacroTile

        for macro in self._repo.list_macros():
            if not macro.show_on_stage:
                continue
            panel_id = f"macro.stage.{macro.macro_id}"
            macro_id = macro.macro_id
            engine = self._engine
            try:
                self._app_context.register_stage_widget(
                    panel_id=panel_id,
                    title=macro.name,
                    icon=macro.icon,
                    factory=lambda mid=macro_id, eng=engine: MacroTile(mid, eng),
                )
                self._registered_stage_widget_ids.append(panel_id)
            except Exception as exc:
                logger.warning("Could not register stage widget %s: %s", panel_id, exc)

    def _register_macro_actions(self, app_context: AppContext) -> None:
        for macro in self._repo.list_macros():
            action_id = f"macro.run.{macro.macro_id}"
            app_context.register_action(
                action_id=action_id,
                title=f"Run Macro: {macro.name}",
                description=macro.description or f"Execute the '{macro.name}' macro.",
                execute=lambda mid=macro.macro_id: self._engine.run_macro(mid),
                icon=macro.icon,
                page="Macro",
                group="Run Macro",
                default_shortcut=macro.hotkey or None,
                plugin_id="macro_manager",
            )
            self._registered_macro_action_ids.append(action_id)

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.macro_manager.ui.macro_page import MacroPage
        from stream_controller.plugins.macro_manager.ui.macro_tile import MacroCatalogTile

        self._page_widget = MacroPage(
            engine=self._engine,
            app_context=app_context,
            on_macros_changed=self.refresh_macro_actions,
        )
        app_context.register_plugin_page(
            page_id="macro_manager",
            title="Macro Manager",
            subtitle="Build and run macros — sequences of actions and delays.",
            widget=self._page_widget,
            help_text=(
                "<h3>Macro Manager</h3>"
                "<p>Macros are automated workflows that chain multiple actions together and run them "
                "in sequence with a single button press or hotkey.</p>"
                "<h4>Building a macro</h4>"
                "<ol>"
                "<li>Click <b>New Macro</b> and give it a name.</li>"
                "<li>Browse the <b>Step Library</b> on the left to find the action you want.</li>"
                "<li>Click a step type to configure its parameters on the right, then click <b>Add Step</b>.</li>"
                "<li>Reorder steps by dragging, or click an existing step to edit it.</li>"
                "<li>Click <b>Save Macro</b> when done.</li>"
                "</ol>"
                "<h4>Running a macro</h4>"
                "<p>Click <b>Run</b> next to any macro, assign it a <b>hotkey</b> in the macro settings, "
                "or add it to the Stage View as a button tile.</p>"
                "<h4>Typical go-live workflow</h4>"
                "<p><b>Connect Services</b> → <b>Update Stream Info</b> → <b>Choose Tracks</b> → "
                "<b>Create Timer</b> (wait for completion) → <b>Switch Scene</b> → "
                "<b>Play Chosen Tracks</b> → <b>Send Chat Message</b></p>"
                "<h4>Tips</h4>"
                "<ul>"
                "<li>Use a <b>Wait</b> step to add a delay between actions.</li>"
                "<li>Use <b>Run Action</b> to trigger any registered action, including other macros.</li>"
                "<li>The <b>Raid Channel</b> step uses your saved raid list — manage it in Settings.</li>"
                "</ul>"
            ),
        )
        app_context.register_dashboard_panel(
            title="Macro Manager",
            description="Build and trigger macros from the sidebar or stage view.",
            widget=self._build_dashboard_panel(),
        )
        app_context.register_stage_widget(
            panel_id="macro.main",
            title="Macro Manager",
            icon="▶",
            factory=lambda: MacroCatalogTile(self._engine),
        )
        app_context.register_stage_widget(
            panel_id="raid.control",
            title="Raid Control",
            icon="⚔",
            factory=lambda: self._build_raid_card(app_context),
        )
        app_context.register_stage_widget(
            panel_id="macros.log",
            title="Macro Log",
            icon="📋",
            factory=self._make_log_card,
        )

    def _make_log_card(self):
        from stream_controller.plugins.macro_manager.ui.macro_log_card import MacroLogCard
        return MacroLogCard(self._engine)

    def _build_raid_card(self, app_context):
        from stream_controller.plugins.macro_manager.ui.raid_card import RaidCard
        return RaidCard(app_context)

    def _build_dashboard_panel(self):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Macro Manager active — use the sidebar to create and manage macros.")
        lbl.setObjectName("CardDescription")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        return panel

    def _open_panel(self) -> None:
        if self._app_context:
            self._app_context.show_page("macro_manager")
