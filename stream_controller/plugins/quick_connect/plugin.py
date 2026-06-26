from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)


class QuickConnectPlugin:
    def __init__(self) -> None:
        self._app_context = None
        self._page = None

    def register(self, app_context: "AppContext") -> None:
        self._app_context = app_context
        from stream_controller.plugins.quick_connect.ui.quick_connect_page import QuickConnectPage
        self._page = QuickConnectPage(app_context)
        app_context.register_plugin_page(
            page_id="quick_connect",
            title="Quick Connect",
            subtitle="Connect and disconnect all your streaming services at once.",
            widget=self._page,
            help_text=(
                "<h3>Quick Connect</h3>"
                "<p>Quick Connect lets you bring all your streaming services online or offline in one place "
                "rather than visiting each plugin individually.</p>"
                "<h4>Connecting services</h4>"
                "<p>Each card represents a service (OBS, Twitch, Bots, Chat, Stats, PNGtuber). "
                "Click <b>Connect</b> on a card to connect that service, or use <b>Connect All</b> "
                "at the top to bring everything online at once. The status indicator on each card "
                "turns green when connected.</p>"
                "<h4>Tips</h4>"
                "<ul>"
                "<li>Connect OBS first — other services like Scene Manager depend on it.</li>"
                "<li>You can also connect services automatically via a Macro — add a <b>Connect Services</b> step.</li>"
                "<li>If a service shows an error, visit its dedicated page to check credentials.</li>"
                "</ul>"
            ),
        )
        from stream_controller.plugins.quick_connect.ui.quick_connect_tile import QuickConnectTile
        app_context.register_stage_widget(
            panel_id="quick_connect.tile",
            title="Quick Connect",
            icon="⚡",
            factory=lambda: QuickConnectTile(app_context),
        )
        logger.info("Quick Connect plugin registered")

    def unregister(self, app_context: "AppContext") -> None:
        self._page = None
        self._app_context = None
