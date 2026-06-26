from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.core.app_context import AppContext
from stream_controller.plugins.music_manager.actions import ACTION_DEFINITIONS, make_action_handlers
from stream_controller.plugins.music_manager.audio_backend import AudioBackend
from stream_controller.plugins.music_manager.library_service import LibraryService
from stream_controller.plugins.music_manager.music_repository import MusicRepository
from stream_controller.plugins.music_manager.music_state import MusicState
from stream_controller.plugins.music_manager.overlay_server import OverlayServer
from stream_controller.plugins.music_manager.playlist_service import PlaylistService

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "music_manager"


class MusicManagerPlugin:
    """
    Music Manager — local audio playback, playlists, and Now Playing overlays.
    Registered through the StreamShift plugin system.
    """

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo: MusicRepository | None = None
        self._backend: AudioBackend | None = None
        self._library: LibraryService | None = None
        self._playlists: PlaylistService | None = None
        self._music_state: MusicState | None = None
        self._overlay_server: OverlayServer | None = None
        self._tick_timer = None
        self._page_widget = None

    # ── registration ─────────────────────────────────────────────────────────

    def register(self, app_context: AppContext) -> None:
        from PySide6.QtCore import QTimer
        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo = MusicRepository(_DATA_DIR / "music.db")

        self._backend = AudioBackend()
        self._backend.initialise()

        self._library = LibraryService(self._repo)
        self._library.load()

        self._playlists = PlaylistService(self._repo)
        self._playlists.load()

        self._music_state = MusicState(self._backend, self._library)
        self._music_state.subscribe(self._on_state_changed)

        self._overlay_server = OverlayServer(self._music_state)
        self._overlay_server.start()

        self._tick_timer = QTimer()
        self._tick_timer.setInterval(500)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._register_actions(app_context)
        self._register_page(app_context)

        app_context.set_status("Music Manager loaded.", timeout_ms=3000)
        logger.info("Music Manager plugin registered")

    def unregister(self, app_context: AppContext) -> None:
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer = None

        if self._music_state is not None:
            self._music_state.unsubscribe(self._on_state_changed)
            self._music_state.stop()

        if self._backend is not None:
            self._backend.shutdown()

        if self._overlay_server is not None:
            self._overlay_server.stop()

        if self._repo is not None:
            self._repo.close()

        self._app_context = None
        self._repo = None
        self._backend = None
        self._library = None
        self._playlists = None
        self._music_state = None
        self._overlay_server = None
        self._page_widget = None
        logger.info("Music Manager plugin unregistered")

    # ── private ───────────────────────────────────────────────────────────────

    def _register_actions(self, app_context: AppContext) -> None:
        handlers = make_action_handlers(self._music_state)
        handlers["music.open_control_panel"] = self._open_control_panel

        for defn in ACTION_DEFINITIONS:
            aid = defn["action_id"]
            factory = None
            if aid == "music.player_card":
                factory = self._make_player_card_tile
            app_context.register_action(
                action_id=aid,
                title=defn["title"],
                description=defn["description"],
                execute=handlers.get(aid, lambda: None),
                icon=defn.get("icon", "MM"),
                page=defn.get("page", "Music"),
                group=defn.get("group", "Music Manager"),
                default_shortcut=defn.get("default_shortcut"),
                widget_factory=factory,
            )

    def _make_player_card_tile(self):
        from stream_controller.plugins.music_manager.ui.player_card_tile import MusicPlayerCardTile
        return MusicPlayerCardTile(self._music_state, self._playlists)

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.music_manager.ui.music_page import MusicPage
        overlay_url = self._overlay_server.base_url if self._overlay_server else ""
        self._page_widget = MusicPage(
            music_state=self._music_state,
            library=self._library,
            playlists=self._playlists,
            overlay_base_url=overlay_url,
            overlay_server=self._overlay_server,
        )
        app_context.register_plugin_page(
            page_id="music_manager",
            title="Music Manager",
            subtitle="Local music playback, playlists, and browser-source overlays for streamers.",
            widget=self._page_widget,
            help_text=(
                "<h3>Music Manager</h3>"
                "<p>Music Manager plays local audio files during your stream and shows a Now Playing "
                "overlay in OBS so viewers can see what's on.</p>"
                "<h4>Adding music</h4>"
                "<ol>"
                "<li>Click <b>Add Tracks</b> to import MP3, FLAC, WAV, or other audio files into your library.</li>"
                "<li>Organise tracks into <b>Playlists</b> using the Playlists tab.</li>"
                "</ol>"
                "<h4>Playback</h4>"
                "<p>Use the playback controls to play, pause, skip, and adjust volume. Enable "
                "<b>Shuffle</b> or <b>Repeat</b> from the controls bar.</p>"
                "<h4>Now Playing overlay</h4>"
                "<p>Copy the browser-source URL from the Music page and add it to OBS. "
                "Choose an overlay style (Card, Ticker, Vinyl, etc.) to match your stream aesthetic.</p>"
                "<h4>Using in macros</h4>"
                "<p>Use <b>Choose Tracks</b> to pre-select music, then <b>Play Chosen Tracks</b> later in "
                "the macro (e.g. after going live). Use <b>Play Playlist</b> to play an entire playlist automatically.</p>"
            ),
        )
        app_context.register_dashboard_panel(
            title="Music Manager",
            description="Local music playback with Now Playing overlays.",
            widget=self._build_dashboard_panel(),
        )
        app_context.register_stage_widget(
            panel_id="music.main",
            title="Music Player",
            icon="🎵",
            factory=lambda: __import__(
                'stream_controller.plugins.music_manager.ui.player_card_tile',
                fromlist=['MusicPlayerCardTile']
            ).MusicPlayerCardTile(self._music_state, self._playlists),
        )

    def _build_dashboard_panel(self):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        lbl = QLabel("Music Manager active — use the sidebar to open the full player.")
        lbl.setObjectName("CardDescription")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        return panel

    def _open_control_panel(self) -> None:
        if self._app_context is not None:
            self._app_context.show_page("music_manager")

    def _on_state_changed(self, state) -> None:
        if self._page_widget is not None and hasattr(self._page_widget, "refresh"):
            self._page_widget.refresh(state)

    def _tick(self) -> None:
        if self._music_state is not None:
            self._music_state.tick()
