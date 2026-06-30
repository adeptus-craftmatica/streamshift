from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from stream_controller import __version__
from stream_controller.core.action_registry import ActionRegistry
from stream_controller.core.app_context import AppContext
from stream_controller.core.command_registry import CommandRegistry
from stream_controller.core.event_bus import EventBus
from stream_controller.core.hotkey_manager import HotkeyManager
from stream_controller.core.plugin_manager import PluginManager
from stream_controller.core.settings_registry import SettingsRegistry
from stream_controller.core.settings_manager import SettingsManager
from stream_controller.ui.main_window import MainWindow
from stream_controller.ui.theme import apply_theme


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)
    logging.getLogger("websocket").setLevel(logging.CRITICAL)


def create_application(argv: Sequence[str] | None = None) -> tuple[QApplication, AppContext, MainWindow]:
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("StreamShift")
    app.setApplicationDisplayName("StreamShift")
    app.setOrganizationName("StreamShift")
    app.setApplicationVersion(__version__)

    apply_theme(app)

    event_bus = EventBus()
    action_registry = ActionRegistry(event_bus=event_bus)
    command_registry = CommandRegistry()
    settings_registry = SettingsRegistry()
    settings_manager = SettingsManager()
    hotkey_manager = HotkeyManager(
        action_registry=action_registry,
        settings_manager=settings_manager,
        event_bus=event_bus,
    )
    app_context = AppContext(
        action_registry=action_registry,
        event_bus=event_bus,
        command_registry=command_registry,
        hotkey_manager=hotkey_manager,
        settings_registry=settings_registry,
        settings_manager=settings_manager,
    )

    plugins_directory = Path(__file__).resolve().parent / "plugins"
    plugin_manager = PluginManager(plugins_directory=plugins_directory)
    app_context.attach_plugin_manager(plugin_manager)

    main_window = MainWindow(app_context=app_context)
    app_context.attach_main_window(main_window)
    hotkey_manager.attach_host(main_window)

    plugin_manager.load_plugins(app_context)
    main_window.refresh_runtime_state()

    return app, app_context, main_window


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the StreamShift desktop application.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Launch the app and exit automatically after startup checks.",
    )
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw_args)

    configure_logging()
    app, app_context, main_window = create_application(argv=[sys.argv[0]])

    # Show the first-time setup wizard before the main window if setup hasn't been done.
    from stream_controller.ui.setup_wizard import is_setup_complete, SetupWizard
    if not is_setup_complete() and not args.smoke_test:
        wizard = SetupWizard(parent=main_window)
        wizard.exec()

    main_window.showMaximized()
    app_context.set_status("Base runtime ready.", timeout_ms=4000)
    app_context.mark_app_started()
    app_context.event_bus.emit("app.started", app_context.runtime_snapshot())

    if args.smoke_test:
        QTimer.singleShot(350, app.quit)

    return app.exec()
