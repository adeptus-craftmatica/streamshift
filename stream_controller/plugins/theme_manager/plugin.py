from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from stream_controller.plugins.theme_manager import theme_engine
from stream_controller.plugins.theme_manager.theme_models import PanelTheme
from stream_controller.plugins.theme_manager.theme_repository import ThemeRepository
from stream_controller.plugins.theme_manager.ui.theme_manager_page import ThemeManagerPage

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "theme_manager"


class ThemeManagerPlugin:
    """
    Theme Manager plugin — applies the saved theme on startup and exposes the
    theme editor as a navigation page.
    """

    def __init__(self) -> None:
        self._repo = ThemeRepository(_DATA_DIR)
        self._page: ThemeManagerPage | None = None
        self._app_context = None
        self._stage_view_ref = None  # held so we can disconnect on unregister

    # ── plugin lifecycle ──────────────────────────────────────────────────────

    def register(self, app_context) -> None:
        """Called by the plugin loader when the plugin is loaded."""
        self._app_context = app_context
        theme_engine.register_repo(self._repo)
        self._apply_saved_theme()
        # Hook into StagePanel creation so panel overrides are applied whenever
        # new panels are added to the stage view.  Must connect to the *instance*,
        # not the class — use a short-delay timer so the widget is fully shown first.
        QTimer.singleShot(0, self._connect_stage_signal)
        app_context.register_plugin_page(
            page_id="theme_manager",
            title="Theme Manager",
            subtitle="Customise the look and feel of StreamShift.",
            widget=self.get_page(),
            help_text=(
                "<h3>Theme Manager</h3>"
                "<p>Theme Manager lets you change the colours, fonts, and overall appearance of "
                "StreamShift to match your personal style or stream branding.</p>"
                "<h4>Applying a theme</h4>"
                "<ol>"
                "<li>Browse the available themes in the list.</li>"
                "<li>Click a theme to preview it live — the app updates immediately.</li>"
                "<li>Your chosen theme is saved and restored automatically on next launch.</li>"
                "</ol>"
                "<h4>Customising</h4>"
                "<p>Use the colour pickers and sliders to tweak accent colours, backgrounds, and text. "
                "Changes apply in real time so you can see exactly what each adjustment does.</p>"
                "<h4>Stage View theming</h4>"
                "<p>The Stage View (second monitor layout) picks up your active theme automatically, "
                "so your dashboard and stream panels always match.</p>"
            ),
        )

    def get_page(self) -> ThemeManagerPage:
        if self._page is None:
            self._page = ThemeManagerPage(self._repo)
        return self._page

    # ── internal ──────────────────────────────────────────────────────────────

    def unregister(self, app_context) -> None:
        if self._stage_view_ref is not None:
            try:
                self._stage_view_ref.panel_added.disconnect(self._on_panel_added)
            except RuntimeError:
                pass  # widget already destroyed
            self._stage_view_ref = None
        app_context.main_window.unregister_plugin_ui("theme_manager")
        self._app_context = None
        self._page = None
        logger.info("Theme Manager plugin unregistered")

    def _connect_stage_signal(self) -> None:
        from stream_controller.ui.stage_view.stage_view_page import StageViewPage
        for widget in QApplication.allWidgets():
            if isinstance(widget, StageViewPage):
                widget.panel_added.connect(self._on_panel_added)
                self._stage_view_ref = widget
                break

    def _apply_saved_theme(self) -> None:
        theme = self._repo.get_active_theme()
        theme_engine.apply_theme(theme)
        # Apply panel overrides after a brief delay to let all panels finish
        # constructing.  We call it directly — by the time the event loop runs
        # the queued call all StagePanel widgets should be visible.
        QTimer.singleShot(300, self._apply_panel_overrides)

    def _apply_panel_overrides(self) -> None:
        overrides_raw = self._repo.get_panel_overrides_for_active()
        if not overrides_raw:
            return
        from stream_controller.ui.stage_view.stage_panel import StagePanel
        for widget in QApplication.allWidgets():
            if isinstance(widget, StagePanel):
                pid = widget.panel_id
                if pid in overrides_raw:
                    pt = PanelTheme.from_dict(overrides_raw[pid])
                    theme_engine.apply_panel_theme(widget, pt)

    def _on_panel_added(self, panel_id: str) -> None:
        overrides_raw = self._repo.get_panel_overrides_for_active()
        if panel_id not in overrides_raw:
            return
        pt = PanelTheme.from_dict(overrides_raw[panel_id])
        from stream_controller.ui.stage_view.stage_panel import StagePanel
        for widget in QApplication.allWidgets():
            if isinstance(widget, StagePanel) and widget.panel_id == panel_id:
                theme_engine.apply_panel_theme(widget, pt)
                break
