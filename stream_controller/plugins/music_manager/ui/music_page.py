from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QSettings, Qt, Signal
from PySide6.QtGui import QDrag, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stream_controller.ui.theme import create_badge, create_card

if TYPE_CHECKING:
    from stream_controller.plugins.music_manager.library_service import LibraryService
    from stream_controller.plugins.music_manager.models import PlaybackState
    from stream_controller.plugins.music_manager.music_state import MusicState
    from stream_controller.plugins.music_manager.playlist_service import PlaylistService

_MIME_PATHS = "application/x-streamshift-music-paths"


# ══════════════════════════════════════════════════════════════════════════════
# LIBRARY TREE — Artist > Album > Track, multi-select, drag-enabled
# ══════════════════════════════════════════════════════════════════════════════

class MusicLibraryTree(QTreeWidget):
    track_double_clicked = Signal(object)  # emits Path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MusicLibraryTree")
        self.setColumnCount(2)
        self.setHeaderLabels(["Track", "Time"])
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.header().setMinimumSectionSize(52)
        self.header().setDefaultAlignment(Qt.AlignLeft)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setRootIsDecorated(True)
        self.setExpandsOnDoubleClick(True)
        self.setUniformRowHeights(False)
        self.setIndentation(18)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.itemDoubleClicked.connect(self._on_double_click)

        self._artist_font = QFont()
        self._artist_font.setPointSize(13)
        self._artist_font.setWeight(QFont.Bold)

        self._album_font = QFont()
        self._album_font.setPointSize(12)
        self._album_font.setItalic(True)

    def populate(self, tracks: list) -> None:
        self.clear()
        _NO_ALBUM = ""
        grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for track in tracks:
            grouped[track.display_artist][track.album or _NO_ALBUM].append(track)

        for artist in sorted(grouped, key=str.lower):
            a_item = QTreeWidgetItem(self, [artist, ""])
            a_item.setData(0, Qt.UserRole, None)
            a_item.setFont(0, self._artist_font)
            a_item.setForeground(0, self.palette().text())
            a_item.setFlags(Qt.ItemIsEnabled)

            albums = grouped[artist]
            named_albums = {k: v for k, v in albums.items() if k}
            unnamed = albums.get(_NO_ALBUM, [])

            for track in sorted(unnamed, key=lambda t: (t.track_number or 999, t.title.lower())):
                t_item = QTreeWidgetItem(a_item, [track.display_title, track.duration_str])
                t_item.setData(0, Qt.UserRole, track.path)
                t_item.setToolTip(0, str(track.path))

            for album in sorted(named_albums, key=str.lower):
                track_nodes = sorted(named_albums[album], key=lambda t: (t.track_number or 999, t.title.lower()))
                al_item = QTreeWidgetItem(a_item, [album, ""])
                al_item.setData(0, Qt.UserRole, None)
                al_item.setFont(0, self._album_font)
                al_item.setFlags(Qt.ItemIsEnabled)
                for track in track_nodes:
                    t_item = QTreeWidgetItem(al_item, [track.display_title, track.duration_str])
                    t_item.setData(0, Qt.UserRole, track.path)
                    t_item.setToolTip(0, str(track.path))

            a_item.setExpanded(True)

    def selected_paths(self) -> list[Path]:
        return [
            item.data(0, Qt.UserRole)
            for item in self.selectedItems()
            if item.data(0, Qt.UserRole) is not None
        ]

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # type: ignore[override]
        paths = self.selected_paths()
        if not paths:
            return
        mime = QMimeData()
        mime.setData(_MIME_PATHS, json.dumps([str(p) for p in paths]).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, Qt.UserRole)
        if path is not None:
            self.track_double_clicked.emit(path)


# ══════════════════════════════════════════════════════════════════════════════
# PLAYLIST DROP LIST — accepts drops from MusicLibraryTree
# ══════════════════════════════════════════════════════════════════════════════

class PlaylistDropList(QListWidget):
    tracks_dropped = Signal(list)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MusicTrackList")
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_PATHS):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_PATHS):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_PATHS):
            raw = bytes(event.mimeData().data(_MIME_PATHS))
            paths = [Path(p) for p in json.loads(raw.decode())]
            self.tracks_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# MUSIC PAGE — tabbed: Player | Library & Playlists
# ══════════════════════════════════════════════════════════════════════════════

class MusicPage(QWidget):
    def __init__(
        self,
        music_state: "MusicState",
        library: "LibraryService",
        playlists: "PlaylistService",
        overlay_base_url: str = "",
        overlay_server=None,
    ) -> None:
        super().__init__()
        self._state = music_state
        self._library = library
        self._playlists = playlists
        self._overlay_base_url = overlay_base_url
        self._overlay_server = overlay_server
        self._selected_playlist_id: str | None = None
        self._seeking = False
        self._last_queue_len: int = 0
        self._last_queue_index: int = -1
        # overlay customisation state
        self._ov_accent = "3f94bf"
        self._ov_text = "eef6ff"
        self._ov_bg = 88
        self._ov_hide_stopped = False
        self._ov_url_labels: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_tab_bar())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_player_tab())
        self._stack.addWidget(self._build_library_tab())
        self._stack.addWidget(self._build_overlays_tab())
        saved_tab = int(QSettings("StreamShift", "StreamController").value("music/tab", 0))
        self._stack.setCurrentIndex(saved_tab if 0 <= saved_tab < 3 else 0)
        root.addWidget(self._stack, 1)

        self._refresh_playlist_view()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("MusicTabBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 0)
        layout.setSpacing(4)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)

        saved_tab = int(QSettings("StreamShift", "StreamController").value("music/tab", 0))
        for i, label in enumerate(["Now Playing", "Library / Playlists", "Overlays"]):
            btn = QPushButton(label)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == saved_tab)
            btn.clicked.connect(lambda _=False, idx=i: (
                self._stack.setCurrentIndex(idx),
                QSettings("StreamShift", "StreamController").setValue("music/tab", idx),
            ))
            self._tab_group.addButton(btn, i)
            layout.addWidget(btn)

        layout.addStretch(1)
        return bar

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 0 — NOW PLAYING
    # ══════════════════════════════════════════════════════════════════════════

    def _build_player_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_now_playing_card())
        layout.addWidget(self._build_transport_card())
        layout.addWidget(self._build_queue_card())
        layout.addWidget(self._build_settings_card())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_now_playing_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MusicNowPlayingCard")
        outer = QHBoxLayout(card)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(28)

        # Album art
        art = QFrame()
        art.setObjectName("MusicAlbumArt")
        art.setFixedSize(128, 128)
        art_layout = QVBoxLayout(art)
        art_layout.setContentsMargins(0, 0, 0, 0)
        self._art_label = QLabel("MM")
        self._art_label.setObjectName("MusicAlbumArtLabel")
        self._art_label.setAlignment(Qt.AlignCenter)
        art_layout.addWidget(self._art_label)
        outer.addWidget(art, 0, Qt.AlignVCenter)

        # Track info
        info = QVBoxLayout()
        info.setSpacing(6)

        self._track_title_label = QLabel("No track playing")
        self._track_title_label.setObjectName("MusicTrackTitle")

        self._track_artist_label = QLabel("Add a folder in the library to get started")
        self._track_artist_label.setObjectName("MusicTrackArtist")

        # Status badges
        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self._status_badge = create_badge("Stopped", "neutral")
        self._loop_badge = create_badge("Loop: Off", "neutral")
        self._shuffle_badge = create_badge("Shuffle: Off", "neutral")
        badge_row.addWidget(self._status_badge)
        badge_row.addWidget(self._loop_badge)
        badge_row.addWidget(self._shuffle_badge)
        badge_row.addStretch(1)

        info.addStretch(1)
        info.addWidget(self._track_title_label)
        info.addWidget(self._track_artist_label)
        info.addSpacing(4)
        info.addLayout(badge_row)
        info.addStretch(1)

        outer.addLayout(info, 1)
        return card

    def _build_transport_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MusicTransportCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Progress bar + timestamps
        self._progress_slider = QSlider(Qt.Horizontal)
        self._progress_slider.setObjectName("MusicProgressSlider")
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.sliderPressed.connect(self._on_seek_start)
        self._progress_slider.sliderReleased.connect(self._on_seek_end)
        layout.addWidget(self._progress_slider)

        time_row = QHBoxLayout()
        self._position_label = QLabel("0:00")
        self._position_label.setObjectName("MusicTimeLabel")
        self._duration_label = QLabel("0:00")
        self._duration_label.setObjectName("MusicTimeLabel")
        time_row.addWidget(self._position_label)
        time_row.addStretch(1)
        time_row.addWidget(self._duration_label)
        layout.addLayout(time_row)

        # Transport controls
        transport = QHBoxLayout()
        transport.setSpacing(8)

        self._prev_btn = _tbtn("⏮  Prev")
        self._prev_btn.clicked.connect(self._state.previous_track)
        self._play_pause_btn = _tbtn("▶  Play", primary=True)
        self._play_pause_btn.clicked.connect(self._state.play_pause)
        self._next_btn = _tbtn("Next  ⏭")
        self._next_btn.clicked.connect(self._state.next_track)
        self._stop_btn = _tbtn("■  Stop")
        self._stop_btn.clicked.connect(self._state.stop)

        sep = QFrame()
        sep.setObjectName("MusicTransportSep")
        sep.setFixedWidth(1)
        sep.setFixedHeight(24)

        self._shuffle_btn = _tbtn("⇄  Shuffle", checkable=True)
        self._shuffle_btn.clicked.connect(lambda: self._state.toggle_shuffle())
        self._loop_btn = _tbtn("↺  Loop: Off")
        self._loop_btn.setMinimumWidth(110)
        self._loop_btn.clicked.connect(lambda: self._state.cycle_loop_mode())

        transport.addWidget(self._prev_btn)
        transport.addWidget(self._play_pause_btn)
        transport.addWidget(self._next_btn)
        transport.addWidget(self._stop_btn)
        transport.addSpacing(4)
        transport.addWidget(sep)
        transport.addSpacing(4)
        transport.addWidget(self._shuffle_btn)
        transport.addWidget(self._loop_btn)
        transport.addStretch(1)
        layout.addLayout(transport)

        # Volume row
        vol_row = QHBoxLayout()
        vol_row.setSpacing(10)
        vol_row.addWidget(_field_label("Volume"))
        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setObjectName("MusicVolumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(140)
        self._volume_slider.valueChanged.connect(lambda v: self._state.set_volume(v / 100.0))
        self._mute_btn = _tbtn("Mute")
        self._mute_btn.clicked.connect(lambda: self._state.toggle_mute())
        vol_row.addWidget(self._volume_slider)
        vol_row.addWidget(self._mute_btn)
        vol_row.addStretch(1)
        layout.addLayout(vol_row)

        return card

    def _build_queue_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MusicSettingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        header = _field_label("Up Next")
        layout.addWidget(header)

        self._queue_list = QListWidget()
        self._queue_list.setObjectName("MusicTrackList")
        self._queue_list.setMaximumHeight(200)
        self._queue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._queue_list.itemDoubleClicked.connect(self._on_queue_item_clicked)
        self._queue_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._queue_list.customContextMenuRequested.connect(self._queue_context_menu)
        layout.addWidget(self._queue_list)

        return card

    def _build_settings_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MusicSettingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Active playlist
        pl_row = QHBoxLayout()
        pl_row.setSpacing(12)
        pl_label = _field_label("Active Playlist")
        pl_label.setMinimumWidth(120)
        self._playlist_combo = QComboBox()
        self._playlist_combo.setObjectName("MusicPlaylistCombo")
        self._playlist_combo.setMinimumWidth(200)
        self._playlist_combo.setMaxVisibleItems(16)
        self._playlist_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._playlist_combo.view().setMinimumWidth(280)
        self._playlist_combo.view().setSpacing(2)
        self._playlist_combo.setPlaceholderText("No playlist selected")
        self._playlist_combo.currentIndexChanged.connect(self._on_combo_changed)
        pl_row.addWidget(pl_label)
        pl_row.addWidget(self._playlist_combo)
        pl_row.addStretch(1)
        layout.addLayout(pl_row)

        # Output device
        dev_row = QHBoxLayout()
        dev_row.setSpacing(12)
        dev_label = _field_label("Audio Output")
        dev_label.setMinimumWidth(120)
        self._device_combo = QComboBox()
        self._device_combo.setObjectName("MusicPlaylistCombo")
        self._device_combo.setMinimumWidth(200)
        self._device_combo.setMaxVisibleItems(14)
        self._device_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._device_combo.view().setMinimumWidth(340)
        self._device_combo.view().setSpacing(2)
        self._device_combo.setToolTip("Audio output device")
        self._device_combo.addItem("System Default", None)
        for _idx, name in self._state.list_output_devices():
            self._device_combo.addItem(name, name)
        current = self._state.selected_device
        if current:
            found = self._device_combo.findData(current)
            if found >= 0:
                self._device_combo.setCurrentIndex(found)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        dev_row.addWidget(dev_label)
        dev_row.addWidget(self._device_combo)
        dev_row.addStretch(1)
        layout.addLayout(dev_row)

        obs_hint = QLabel(
            "To capture this device in OBS, go to OBS → Settings → Audio and set one of the "
            "Mic/Auxiliary Audio slots to the same device, or add an Audio Input Capture source in your scene."
        )
        obs_hint.setObjectName("MetaText")
        obs_hint.setWordWrap(True)
        layout.addWidget(obs_hint)

        # Overlay URLs
        if self._overlay_base_url:
            url_row = QHBoxLayout()
            url_row.setSpacing(8)
            url_row.addWidget(_field_label("Overlay URLs"))
            for lbl, path in [("Card", "/card"), ("Minimal", "/minimal"), ("Ticker", "/ticker")]:
                url = f"{self._overlay_base_url}{path}"
                b = QPushButton(f"Copy {lbl} URL")
                b.setObjectName("SecondaryButton")
                b.clicked.connect(lambda _=False, u=url: QGuiApplication.clipboard().setText(u))
                url_row.addWidget(b)
            url_row.addStretch(1)
            layout.addLayout(url_row)

        return card

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — LIBRARY & PLAYLISTS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_library_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("MusicLibrarySplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.addWidget(self._build_library_panel())
        splitter.addWidget(self._build_playlist_panel())
        splitter.setSizes([560, 440])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        return container

    def _build_library_panel(self) -> QFrame:
        card, body = create_card(
            "Music Library",
            "Artist / Album / Track tree. Ctrl+click or Shift+click to select multiple. Drag tracks to a playlist.",
        )
        body.setSpacing(10)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        add_btn = QPushButton("+ Add Folder")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_folder)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setObjectName("SecondaryButton")
        rescan_btn.clicked.connect(self._rescan_library)
        rm_btn = QPushButton("Remove Folder")
        rm_btn.setObjectName("SecondaryButton")
        rm_btn.clicked.connect(self._remove_folder)
        folder_row.addWidget(add_btn)
        folder_row.addWidget(rescan_btn)
        folder_row.addWidget(rm_btn)
        folder_row.addStretch(1)
        body.addLayout(folder_row)

        self._folder_list = QListWidget()
        self._folder_list.setObjectName("DeckNavList")
        self._folder_list.setMaximumHeight(62)
        self._folder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.addWidget(self._folder_list)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._library_track_count = QLabel()
        self._library_track_count.setObjectName("MetaText")
        action_row.addWidget(self._library_track_count)
        action_row.addStretch(1)

        self._edit_artist_btn = QPushButton("Edit Artist")
        self._edit_artist_btn.setObjectName("SecondaryButton")
        self._edit_artist_btn.setToolTip("Edit the artist tag for all selected tracks")
        self._edit_artist_btn.clicked.connect(self._edit_artist_for_selection)

        self._edit_album_btn = QPushButton("Edit Album")
        self._edit_album_btn.setObjectName("SecondaryButton")
        self._edit_album_btn.setToolTip("Edit the album tag for all selected tracks")
        self._edit_album_btn.clicked.connect(self._edit_album_for_selection)

        add_to_pl_btn = QPushButton("Add to Playlist")
        add_to_pl_btn.setObjectName("SecondaryButton")
        add_to_pl_btn.setToolTip("Add selected tracks to the active playlist")
        add_to_pl_btn.clicked.connect(self._add_selection_to_playlist)

        action_row.addWidget(self._edit_artist_btn)
        action_row.addWidget(self._edit_album_btn)
        action_row.addWidget(add_to_pl_btn)
        body.addLayout(action_row)

        # Play/Shuffle library row
        lib_play_row = QHBoxLayout()
        lib_play_row.setSpacing(8)
        play_lib_btn = QPushButton("▶  Play Library")
        play_lib_btn.setObjectName("PrimaryButton")
        play_lib_btn.clicked.connect(lambda: self._play_library(shuffle=False))
        shuffle_lib_btn = QPushButton("🔀  Shuffle Library")
        shuffle_lib_btn.setObjectName("SecondaryButton")
        shuffle_lib_btn.clicked.connect(lambda: self._play_library(shuffle=True))
        lib_play_row.addWidget(play_lib_btn)
        lib_play_row.addWidget(shuffle_lib_btn)
        lib_play_row.addStretch(1)
        body.addLayout(lib_play_row)

        # Search bar
        self._library_search = QLineEdit()
        self._library_search.setObjectName("OverlayTextField")
        self._library_search.setPlaceholderText("Search library…")
        self._library_search.textChanged.connect(self._filter_library)
        body.addWidget(self._library_search)

        self._empty_library_label = QLabel(
            "No folders added yet.\nClick '+ Add Folder' to scan a music directory."
        )
        self._empty_library_label.setObjectName("EmptyState")
        self._empty_library_label.setWordWrap(True)
        self._empty_library_label.setAlignment(Qt.AlignCenter)
        body.addWidget(self._empty_library_label)

        self._library_tree = MusicLibraryTree()
        self._library_tree.track_double_clicked.connect(self._state.play_track)
        self._library_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._library_tree.customContextMenuRequested.connect(self._on_library_context_menu)
        body.addWidget(self._library_tree, 1)

        self._refresh_library_view()
        return card

    def _build_playlist_panel(self) -> QFrame:
        card, body = create_card(
            "Playlists",
            "Select a playlist to manage it. Drag tracks from the library or use 'Add to Playlist'.",
        )
        body.setSpacing(10)

        # Playlist-level controls
        pl_controls = QHBoxLayout()
        pl_controls.setSpacing(8)
        new_pl_btn = QPushButton("+ New")
        new_pl_btn.setObjectName("PrimaryButton")
        new_pl_btn.clicked.connect(self._create_playlist)
        play_pl_btn = QPushButton("▶  Play All")
        play_pl_btn.setObjectName("SecondaryButton")
        play_pl_btn.clicked.connect(self._play_selected_playlist)
        queue_pl_btn = QPushButton("⏬  Queue All")
        queue_pl_btn.setObjectName("SecondaryButton")
        queue_pl_btn.clicked.connect(self._queue_playlist)
        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("SecondaryButton")
        rename_btn.clicked.connect(self._rename_playlist)
        delete_pl_btn = QPushButton("Delete")
        delete_pl_btn.setObjectName("SecondaryButton")
        delete_pl_btn.clicked.connect(self._delete_playlist)
        pl_controls.addWidget(new_pl_btn)
        pl_controls.addWidget(play_pl_btn)
        pl_controls.addWidget(queue_pl_btn)
        pl_controls.addWidget(rename_btn)
        pl_controls.addWidget(delete_pl_btn)
        pl_controls.addStretch(1)
        body.addLayout(pl_controls)

        # Playlist list — give it a fixed portion of space
        self._playlist_list = QListWidget()
        self._playlist_list.setObjectName("MusicPlaylistList")
        self._playlist_list.setMinimumHeight(80)
        self._playlist_list.setMaximumHeight(160)
        self._playlist_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._playlist_list.itemSelectionChanged.connect(self._on_playlist_selection_changed)
        body.addWidget(self._playlist_list)

        # Track count + track-level controls
        track_header = QHBoxLayout()
        track_header.setSpacing(8)
        self._playlist_track_count_label = QLabel("Select a playlist above to see its tracks.")
        self._playlist_track_count_label.setObjectName("MetaText")
        track_header.addWidget(self._playlist_track_count_label)
        track_header.addStretch(1)
        body.addLayout(track_header)

        # Drop list for track contents
        self._playlist_track_list = PlaylistDropList()
        self._playlist_track_list.tracks_dropped.connect(self._on_tracks_dropped_to_playlist)
        self._playlist_track_list.itemDoubleClicked.connect(self._on_playlist_track_double_clicked)
        body.addWidget(self._playlist_track_list, 1)

        track_actions = QHBoxLayout()
        track_actions.setSpacing(8)
        remove_btn = QPushButton("Remove Track")
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self._remove_track_from_playlist)
        up_btn = QPushButton("↑  Move Up")
        up_btn.setObjectName("SecondaryButton")
        up_btn.clicked.connect(lambda: self._move_playlist_track(-1))
        down_btn = QPushButton("↓  Move Down")
        down_btn.setObjectName("SecondaryButton")
        down_btn.clicked.connect(lambda: self._move_playlist_track(1))
        track_actions.addWidget(remove_btn)
        track_actions.addWidget(up_btn)
        track_actions.addWidget(down_btn)
        track_actions.addStretch(1)
        body.addLayout(track_actions)

        return card

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — OVERLAYS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_overlays_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_overlay_customise_card())
        layout.addWidget(self._build_overlay_grid())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_overlay_customise_card(self) -> QFrame:
        card, body = create_card(
            "Appearance",
            "Customise colours and behaviour. URLs update automatically — copy them into OBS or Streamlabs.",
        )
        body.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(20)

        self._accent_edit, accent_swatch = self._make_color_picker(
            "Accent Colour", self._ov_accent, "3f94bf"
        )
        accent_col = QVBoxLayout()
        accent_col.setSpacing(5)
        accent_col.addWidget(_field_label("Accent Colour"))
        accent_col.addLayout(self._color_picker_row(self._accent_edit, accent_swatch))
        row1.addLayout(accent_col)

        self._text_edit, text_swatch = self._make_color_picker(
            "Text Colour", self._ov_text, "eef6ff"
        )
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        text_col.addWidget(_field_label("Text Colour"))
        text_col.addLayout(self._color_picker_row(self._text_edit, text_swatch))
        row1.addLayout(text_col)

        # BG opacity
        bg_col = QVBoxLayout()
        bg_col.setSpacing(5)
        self._bg_opacity_label = _field_label(f"Background Opacity  ({self._ov_bg}%)")
        bg_col.addWidget(self._bg_opacity_label)
        self._bg_slider = QSlider(Qt.Horizontal)
        self._bg_slider.setObjectName("MusicVolumeSlider")
        self._bg_slider.setRange(0, 100)
        self._bg_slider.setValue(self._ov_bg)
        self._bg_slider.setFixedWidth(180)
        self._bg_slider.valueChanged.connect(self._on_bg_opacity_changed)
        bg_col.addWidget(self._bg_slider)
        row1.addLayout(bg_col)

        # Hide when stopped
        hide_col = QVBoxLayout()
        hide_col.setSpacing(5)
        hide_col.addWidget(_field_label("Visibility"))
        self._hide_stopped_cb = QCheckBox("Hide when not playing")
        self._hide_stopped_cb.setObjectName("OverlayCheckBox")
        self._hide_stopped_cb.setChecked(self._ov_hide_stopped)
        self._hide_stopped_cb.toggled.connect(self._on_overlay_param_changed)
        hide_col.addWidget(self._hide_stopped_cb)
        row1.addLayout(hide_col)

        row1.addStretch(1)
        body.addLayout(row1)
        return card

    def _make_color_picker(self, name: str, initial_hex: str, placeholder: str):
        """Return (QLineEdit, swatch QPushButton) wired together."""
        from PySide6.QtGui import QColor
        edit = QLineEdit(initial_hex)
        edit.setObjectName("OverlayTextField")
        edit.setMaximumWidth(90)
        edit.setPlaceholderText(placeholder)

        swatch = QPushButton()
        swatch.setObjectName("ColorSwatch")
        swatch.setFixedSize(32, 32)
        swatch.setToolTip(f"Pick {name}")

        def _apply_hex(hex_str: str) -> None:
            hex_str = hex_str.strip().lstrip("#")
            color = QColor(f"#{hex_str}")
            if color.isValid():
                swatch.setStyleSheet(
                    f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                    f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                    f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
                )

        def _open_picker() -> None:
            from PySide6.QtWidgets import QColorDialog
            from PySide6.QtGui import QColor
            current = QColor(f"#{edit.text().strip().lstrip('#')}")
            color = QColorDialog.getColor(
                current if current.isValid() else QColor(f"#{placeholder}"),
                self,
                f"Choose {name}",
            )
            if color.isValid():
                hex_val = color.name().lstrip("#")
                edit.blockSignals(True)
                edit.setText(hex_val)
                edit.blockSignals(False)
                _apply_hex(hex_val)
                self._on_overlay_param_changed()

        _apply_hex(initial_hex)
        edit.textChanged.connect(lambda t: (_apply_hex(t), self._on_overlay_param_changed()))
        swatch.clicked.connect(_open_picker)
        return edit, swatch

    @staticmethod
    def _color_picker_row(edit: "QLineEdit", swatch: "QPushButton") -> "QHBoxLayout":
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(swatch)
        row.addWidget(edit)
        return row

    def _build_overlay_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        overlays = [
            {
                "name": "Card",
                "path": "/card",
                "desc": "Compact card with album art placeholder, track title, artist, timestamps, and a progress bar. Great for corner placement.",
                "obs_size": "400 × 110 px",
                "preview": self._make_card_preview,
            },
            {
                "name": "Minimal",
                "path": "/minimal",
                "desc": "Slim pill with a pulsing dot, artist name, and track title. Ideal when you want something subtle that never distracts.",
                "obs_size": "360 × 50 px",
                "preview": self._make_minimal_preview,
            },
            {
                "name": "Ticker",
                "path": "/ticker",
                "desc": "Full-width bottom bar with scrolling artist — title text and a compact progress indicator on the right edge.",
                "obs_size": "1920 × 44 px",
                "preview": self._make_ticker_preview,
            },
            {
                "name": "Circle",
                "path": "/circle",
                "desc": "Square canvas centred on a dual-ring circle: the outer ring segments by playlist track count and the inner ring tracks song position.",
                "obs_size": "300 × 300 px",
                "preview": self._make_circle_preview,
            },
            {
                "name": "Corner",
                "path": "/corner",
                "desc": "Tiny pill badge that sits in any corner of the screen. Just a pulsing dot and the scrolling track title — minimum footprint, maximum subtlety.",
                "obs_size": "260 × 56 px",
                "preview": self._make_corner_preview,
            },
            {
                "name": "Banner",
                "path": "/banner",
                "desc": "Full-width top or bottom bar with an accent strip, album art placeholder, scrolling title, artist, timestamp, and a progress line along the bottom edge.",
                "obs_size": "1920 × 72 px",
                "preview": self._make_banner_preview,
            },
            {
                "name": "Equalizer",
                "path": "/equalizer",
                "desc": "Wide card flanked by animated EQ bars that pulse to a decorative visualiser rhythm. The bars pause when playback stops.",
                "obs_size": "520 × 90 px",
                "preview": self._make_equalizer_preview,
            },
            {
                "name": "Vinyl",
                "path": "/vinyl",
                "desc": "A spinning vinyl record disc with the track label at its centre. The disc rotates while playing and a glowing progress arc wraps the outer edge.",
                "obs_size": "440 × 160 px",
                "preview": self._make_vinyl_preview,
            },
            {
                "name": "Cassette",
                "path": "/cassette",
                "desc": "A retro cassette tape with two animated reels. The supply reel winds down and the take-up reel fills as the track plays — spoke rotation speed scales with reel size.",
                "obs_size": "420 × 180 px",
                "preview": self._make_cassette_preview,
            },
            {
                "name": "Prism",
                "path": "/prism",
                "desc": "A wide frosted-glass banner over continuously flowing rainbow-hued bands. The colour spectrum drifts slowly so the background is always in motion.",
                "obs_size": "520 × 88 px",
                "preview": self._make_prism_preview,
            },
            {
                "name": "Nebula",
                "path": "/nebula",
                "desc": "Full-scene ambient overlay with drifting colour blobs on a star field. The glowing nebula breathes slowly behind the track title and progress bar.",
                "obs_size": "1920 × 1080 px",
                "preview": self._make_nebula_preview,
            },
        ]

        for i, ov in enumerate(overlays):
            card = self._make_overlay_card(ov)
            grid.addWidget(card, i // 2, i % 2)

        return container

    def _make_overlay_card(self, ov: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Preview widget
        preview = ov["preview"]()
        layout.addWidget(preview)

        # Name + obs hint
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = QLabel(ov["name"])
        name_lbl.setObjectName("OverlayCardTitle")
        obs_lbl = QLabel(ov["obs_size"])
        obs_lbl.setObjectName("OverlayOBSHint")
        name_row.addWidget(name_lbl)
        name_row.addStretch(1)
        name_row.addWidget(obs_lbl)
        layout.addLayout(name_row)

        # Description
        desc = QLabel(ov["desc"])
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # URL row
        url_lbl = QLabel()
        url_lbl.setObjectName("OverlayURL")
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_lbl.setWordWrap(False)
        url_lbl.setProperty("_path", ov["path"])
        url_lbl.setText(self._overlay_url(ov["path"]))
        self._ov_url_labels.append(url_lbl)
        layout.addWidget(url_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(lambda _=False, lbl=url_lbl: QGuiApplication.clipboard().setText(lbl.text()))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        return card

    # ── Static preview widgets ────────────────────────────────────────────────

    def _make_card_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockCard")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        art = QFrame()
        art.setObjectName("OverlayMockArt")
        art.setFixedSize(48, 48)
        art_inner = QVBoxLayout(art)
        art_inner.setContentsMargins(0, 0, 0, 0)
        art_lbl = QLabel("♪")
        art_lbl.setObjectName("OverlayMockArtLabel")
        art_lbl.setAlignment(Qt.AlignCenter)
        art_inner.addWidget(art_lbl)
        layout.addWidget(art, 0, Qt.AlignVCenter)
        right = QVBoxLayout()
        right.setSpacing(2)
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        bar_wrap = QFrame()
        bar_wrap.setObjectName("OverlayMockBarWrap")
        bar_wrap.setFixedHeight(3)
        bar_inner = QHBoxLayout(bar_wrap)
        bar_inner.setContentsMargins(0, 0, 0, 0)
        bar_fill = QFrame()
        bar_fill.setObjectName("OverlayMockBarFill")
        bar_inner.addWidget(bar_fill, 2)
        bar_empty = QFrame()
        bar_empty.setObjectName("OverlayMockBarEmpty")
        bar_inner.addWidget(bar_empty, 3)
        right.addStretch(1)
        right.addWidget(title)
        right.addWidget(artist)
        right.addSpacing(4)
        right.addWidget(bar_wrap)
        right.addStretch(1)
        layout.addLayout(right, 1)
        return f

    def _make_minimal_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockMinimalWrap")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)
        pill = QFrame()
        pill.setObjectName("OverlayMockMinimal")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(14, 8, 14, 8)
        pill_layout.setSpacing(10)
        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(8, 8)
        sep = QFrame()
        sep.setObjectName("OverlayMockSep")
        sep.setFixedSize(1, 14)
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addWidget(artist)
        pill_layout.addWidget(sep, 0, Qt.AlignVCenter)
        pill_layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        return f

    def _make_ticker_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTicker")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(12)
        badge = QLabel("♪  NOW PLAYING")
        badge.setObjectName("OverlayMockBadge")
        sep = QFrame()
        sep.setObjectName("OverlayMockSep")
        sep.setFixedSize(1, 16)
        scroll = QLabel("Artist Name  —  Track Title  ·  Album")
        scroll.setObjectName("OverlayMockScrollText")
        layout.addWidget(badge, 0, Qt.AlignVCenter)
        layout.addWidget(sep, 0, Qt.AlignVCenter)
        layout.addWidget(scroll, 1, Qt.AlignVCenter)
        return f

    def _make_circle_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockCircleWrap")
        f.setFixedHeight(140)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignCenter)
        # SVG-based preview drawn inline
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            svg_data = self._circle_preview_svg().encode()
            svg = QSvgWidget()
            svg.load(svg_data)
            svg.setFixedSize(120, 120)
            layout.addWidget(svg, 0, Qt.AlignCenter)
        except ImportError:
            # Fallback text if QtSvgWidgets not available
            lbl = QLabel("◎  Dual-ring circle\n(300 × 300 OBS source)")
            lbl.setObjectName("OverlayMockArtist")
            lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl)
        return f

    def _circle_preview_svg(self) -> str:
        accent = "#3f94bf"
        dim = "rgba(63,148,191,0.18)"
        # 8 segments, 3 completed, 1 active, 4 empty
        total = 8
        gap = 4.0
        seg = (360 - total * gap) / total
        import math
        def px(deg, r): return 60 + r * math.cos(math.radians(deg))
        def py(deg, r): return 60 + r * math.sin(math.radians(deg))
        def arc_path(start, sweep, r, w):
            end = start + sweep
            x1, y1 = px(start, r), py(start, r)
            x2, y2 = px(end, r), py(end, r)
            large = 1 if sweep > 180 else 0
            return f"M{x1:.2f},{y1:.2f} A{r},{r} 0 {large},1 {x2:.2f},{y2:.2f}"
        paths = ""
        for i in range(total):
            s = -90 + i * (seg + gap)
            d = arc_path(s, seg, 52, 7)
            if i < 3:
                color = accent
            elif i == 3:
                color = accent
            else:
                color = "#1a3347"
            paths += f'<path d="{d}" stroke="{color}" stroke-width="7" fill="none" stroke-opacity="{"1" if i <= 3 else "1"}"/>\n'
        # inner ring progress ~40%
        inner_d = arc_path(-90, 360 * 0.4, 44, 5)
        inner_bg = arc_path(-90, 359.9, 44, 5)
        return f'''<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
{paths}
<path d="{inner_bg}" stroke="#1a3347" stroke-width="5" fill="none"/>
<path d="{inner_d}" stroke="{accent}" stroke-width="5" fill="none" stroke-linecap="round"/>
<text x="60" y="55" text-anchor="middle" font-size="18" fill="rgba(63,148,191,0.5)">♪</text>
<text x="60" y="69" text-anchor="middle" font-size="8" font-weight="bold" fill="#ddeef8">Track Title</text>
<text x="60" y="79" text-anchor="middle" font-size="7" fill="rgba(63,148,191,0.6)">Artist Name</text>
</svg>'''

    def _make_corner_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockCornerWrap")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)
        pill = QFrame()
        pill.setObjectName("OverlayMockCorner")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(12, 8, 16, 8)
        pill_layout.setSpacing(9)
        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(7, 7)
        body = QVBoxLayout()
        body.setSpacing(1)
        lbl = QLabel("NOW PLAYING")
        lbl.setObjectName("OverlayMockEQLabel")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        body.addWidget(lbl)
        body.addWidget(title)
        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addLayout(body)
        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        return f

    def _make_banner_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockBanner")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Accent strip
        strip = QFrame()
        strip.setObjectName("OverlayMockBannerStrip")
        strip.setFixedWidth(4)
        layout.addWidget(strip)
        # Art square
        art = QFrame()
        art.setObjectName("OverlayMockArt")
        art.setFixedSize(80, 80)
        art_inner = QVBoxLayout(art)
        art_inner.setContentsMargins(0, 0, 0, 0)
        art_lbl = QLabel("♪")
        art_lbl.setObjectName("OverlayMockArtLabel")
        art_lbl.setAlignment(Qt.AlignCenter)
        art_inner.addWidget(art_lbl)
        layout.addWidget(art)
        # Body
        body = QVBoxLayout()
        body.setContentsMargins(14, 10, 14, 10)
        body.setSpacing(2)
        lbl = QLabel("NOW PLAYING")
        lbl.setObjectName("OverlayMockEQLabel")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        body.addWidget(lbl)
        body.addWidget(title)
        body.addWidget(artist)
        body.addStretch(1)
        layout.addLayout(body, 1)
        # Right time col
        right = QVBoxLayout()
        right.setContentsMargins(0, 14, 14, 14)
        right.setSpacing(4)
        right.addStretch(1)
        time_lbl = QLabel("1:23 / 3:45")
        time_lbl.setObjectName("OverlayMockArtist")
        right.addWidget(time_lbl, 0, Qt.AlignRight)
        layout.addLayout(right)
        return f

    def _make_equalizer_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockEqualizer")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        # Left EQ bars
        bars_l = QHBoxLayout()
        bars_l.setSpacing(2)
        heights = [55, 35, 75, 45, 85, 30, 65]
        for h in heights:
            bar = QFrame()
            bar.setObjectName("OverlayMockEQBar")
            bar.setFixedWidth(3)
            bar.setMinimumHeight(4)
            bar.setMaximumHeight(h * 48 // 100)
            bars_l.addWidget(bar, 0, Qt.AlignBottom)
        layout.addLayout(bars_l)

        # Centre body
        body = QVBoxLayout()
        body.setSpacing(2)
        label = QLabel("NOW PLAYING")
        label.setObjectName("OverlayMockEQLabel")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        bar_wrap = QFrame()
        bar_wrap.setObjectName("OverlayMockBarWrap")
        bar_wrap.setFixedHeight(3)
        bar_inner = QHBoxLayout(bar_wrap)
        bar_inner.setContentsMargins(0, 0, 0, 0)
        bar_fill = QFrame()
        bar_fill.setObjectName("OverlayMockBarFill")
        bar_empty = QFrame()
        bar_empty.setObjectName("OverlayMockBarEmpty")
        bar_inner.addWidget(bar_fill, 2)
        bar_inner.addWidget(bar_empty, 3)
        body.addWidget(label)
        body.addWidget(title)
        body.addWidget(artist)
        body.addSpacing(2)
        body.addWidget(bar_wrap)
        layout.addLayout(body, 1)

        # Right EQ bars (dimmer)
        bars_r = QHBoxLayout()
        bars_r.setSpacing(2)
        heights_r = [48, 72, 28, 88, 42, 65, 80]
        for h in heights_r:
            bar = QFrame()
            bar.setObjectName("OverlayMockEQBarDim")
            bar.setFixedWidth(3)
            bar.setMinimumHeight(4)
            bar.setMaximumHeight(h * 48 // 100)
            bars_r.addWidget(bar, 0, Qt.AlignBottom)
        layout.addLayout(bars_r)
        return f

    def _make_vinyl_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockVinylWrap")
        f.setFixedHeight(100)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        # SVG disc
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            svg_data = self._vinyl_preview_svg().encode()
            svg = QSvgWidget()
            svg.load(svg_data)
            svg.setFixedSize(80, 80)
            layout.addWidget(svg, 0, Qt.AlignVCenter)
        except ImportError:
            disc = QLabel("⬤")
            disc.setObjectName("OverlayMockArtist")
            disc.setAlignment(Qt.AlignCenter)
            disc.setFixedSize(80, 80)
            layout.addWidget(disc, 0, Qt.AlignVCenter)

        # Info
        info = QVBoxLayout()
        info.setSpacing(2)
        now_lbl = QLabel("NOW PLAYING")
        now_lbl.setObjectName("OverlayMockEQLabel")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        bar_wrap = QFrame()
        bar_wrap.setObjectName("OverlayMockBarWrap")
        bar_wrap.setFixedHeight(3)
        bar_inner = QHBoxLayout(bar_wrap)
        bar_inner.setContentsMargins(0, 0, 0, 0)
        bar_fill = QFrame()
        bar_fill.setObjectName("OverlayMockBarFill")
        bar_empty = QFrame()
        bar_empty.setObjectName("OverlayMockBarEmpty")
        bar_inner.addWidget(bar_fill, 2)
        bar_inner.addWidget(bar_empty, 3)
        info.addWidget(now_lbl)
        info.addWidget(title)
        info.addWidget(artist)
        info.addSpacing(3)
        info.addWidget(bar_wrap)
        layout.addLayout(info, 1)
        return f

    def _vinyl_preview_svg(self) -> str:
        accent = "#3f94bf"
        import math
        circ = 2 * math.pi * 42 * (80 / 200)  # scaled to 80px viewBox
        pct = 0.42
        offset = circ * (1 - pct)
        return f'''<svg viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg">
<circle cx="40" cy="40" r="38" fill="#0d1820" stroke="#1a2c3d" stroke-width="0.4"/>
<circle cx="40" cy="40" r="34" fill="none" stroke="#1a2c3d" stroke-width="0.4"/>
<circle cx="40" cy="40" r="28" fill="none" stroke="#162434" stroke-width="0.4"/>
<circle cx="40" cy="40" r="22" fill="none" stroke="#1a2c3d" stroke-width="0.3"/>
<circle cx="40" cy="40" r="14" fill="#112030"/>
<circle cx="40" cy="40" r="1.6" fill="#0a0f15"/>
<circle cx="40" cy="40" r="16.8" fill="none" stroke="{accent}" stroke-width="1.8"
  stroke-dasharray="{circ:.2f}" stroke-dashoffset="{offset:.2f}"
  stroke-linecap="round" transform="rotate(-90 40 40)"
  style="filter:drop-shadow(0 0 2px {accent})"/>
<text x="40" y="38" text-anchor="middle" font-size="5.5" font-weight="bold" fill="#ddeef8">Track</text>
<text x="40" y="44" text-anchor="middle" font-size="4.5" fill="rgba(63,148,191,0.65)">Artist</text>
</svg>'''

    def _make_cassette_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockCassette")
        f.setFixedHeight(100)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Label strip
        label_row = QHBoxLayout()
        label_row.setSpacing(6)
        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(6, 6)
        title_lbl = QLabel("Track Title")
        title_lbl.setObjectName("OverlayMockTitle")
        artist_lbl = QLabel("Artist Name")
        artist_lbl.setObjectName("OverlayMockArtist")
        label_row.addWidget(dot, 0, Qt.AlignVCenter)
        label_row.addWidget(title_lbl, 1)
        label_row.addWidget(artist_lbl, 0, Qt.AlignVCenter)
        layout.addLayout(label_row)

        # Reel row (two circles representing the reels)
        reel_row = QHBoxLayout()
        reel_row.setSpacing(0)
        reel_row.addStretch(1)
        for size in (32, 28):   # left reel fuller, right reel partially wound
            reel = QFrame()
            reel.setObjectName("OverlayMockCassetteReel")
            reel.setFixedSize(size, size)
            reel_row.addWidget(reel, 0, Qt.AlignVCenter)
            reel_row.addStretch(1)
        layout.addLayout(reel_row)

        # Progress bar
        bar_wrap = QFrame()
        bar_wrap.setObjectName("OverlayMockBarWrap")
        bar_wrap.setFixedHeight(3)
        bar_inner = QHBoxLayout(bar_wrap)
        bar_inner.setContentsMargins(0, 0, 0, 0)
        bar_fill = QFrame(); bar_fill.setObjectName("OverlayMockBarFill")
        bar_empty = QFrame(); bar_empty.setObjectName("OverlayMockBarEmpty")
        bar_inner.addWidget(bar_fill, 2)
        bar_inner.addWidget(bar_empty, 3)
        layout.addWidget(bar_wrap)

        return f

    def _make_prism_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockPrism")
        f.setFixedHeight(70)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(12)

        rule = QFrame()
        rule.setObjectName("OverlayMockSep")
        rule.setFixedSize(3, 44)
        layout.addWidget(rule, 0, Qt.AlignVCenter)

        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(7, 7)
        layout.addWidget(dot, 0, Qt.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(2)
        now_lbl = QLabel("NOW PLAYING")
        now_lbl.setObjectName("OverlayMockEQLabel")
        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        info.addWidget(now_lbl)
        info.addWidget(title)
        info.addWidget(artist)
        layout.addLayout(info, 1)

        return f

    def _make_nebula_preview(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockNebula")
        f.setFixedHeight(100)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(6)
        pill_row.addStretch(1)
        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(6, 6)
        pill_lbl = QLabel("NOW PLAYING")
        pill_lbl.setObjectName("OverlayMockEQLabel")
        pill_row.addWidget(dot, 0, Qt.AlignVCenter)
        pill_row.addWidget(pill_lbl)
        pill_row.addStretch(1)
        layout.addLayout(pill_row)

        title = QLabel("Track Title")
        title.setObjectName("OverlayMockTitle")
        title.setAlignment(Qt.AlignCenter)
        artist = QLabel("Artist Name")
        artist.setObjectName("OverlayMockArtist")
        artist.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(artist)

        return f

    # ── Overlay URL helpers ───────────────────────────────────────────────────

    def _overlay_url(self, path: str) -> str:
        if not self._overlay_base_url:
            return f"http://localhost:47891{path}  (overlay server not running)"
        params = []
        accent = self._accent_edit.text().strip().lstrip("#") if hasattr(self, "_accent_edit") else self._ov_accent
        text   = self._text_edit.text().strip().lstrip("#")   if hasattr(self, "_text_edit")   else self._ov_text
        if accent and accent != "3f94bf":
            params.append(f"accent={accent}")
        if text and text != "eef6ff":
            params.append(f"text={text}")
        if self._ov_bg != 88:
            params.append(f"bg={self._ov_bg}")
        if self._ov_hide_stopped:
            params.append("hide_stopped=1")
        qs = ("?" + "&".join(params)) if params else ""
        return f"{self._overlay_base_url}{path}{qs}"

    def _on_bg_opacity_changed(self, value: int) -> None:
        self._ov_bg = value
        self._bg_opacity_label.setText(f"Background Opacity  ({value}%)")
        self._push_theme()
        self._refresh_overlay_urls()

    def _on_overlay_param_changed(self) -> None:
        self._ov_accent = self._accent_edit.text().strip().lstrip("#")
        self._ov_text = self._text_edit.text().strip().lstrip("#")
        self._ov_hide_stopped = self._hide_stopped_cb.isChecked()
        self._push_theme()
        self._refresh_overlay_urls()

    def _push_theme(self) -> None:
        if self._overlay_server is None:
            return
        self._overlay_server.push_theme(
            accent=self._ov_accent,
            text=self._ov_text,
            opacity=self._ov_bg,
        )

    def _refresh_overlay_urls(self) -> None:
        for lbl in self._ov_url_labels:
            path = lbl.property("_path")
            if path:
                lbl.setText(self._overlay_url(path))

    # ══════════════════════════════════════════════════════════════════════════
    # REFRESH — called by plugin on every state tick
    # ══════════════════════════════════════════════════════════════════════════

    def refresh(self, state: "PlaybackState") -> None:
        from stream_controller.plugins.music_manager.models import PlaybackStatus

        track = state.current_track
        if track:
            self._track_title_label.setText(track.display_title)
            artist_line = track.display_artist
            if track.album:
                artist_line += f"  ·  {track.album}"
            self._track_artist_label.setText(artist_line)
            self._art_label.setText(track.display_title[:2].upper())
            self._duration_label.setText(track.duration_str)
            if not self._seeking and track.duration > 0:
                self._progress_slider.setValue(int((state.position / track.duration) * 1000))
            self._position_label.setText(_fmt_time(state.position))
        else:
            self._track_title_label.setText("No track playing")
            self._track_artist_label.setText("Add a folder in the library to get started")
            self._art_label.setText("MM")
            self._duration_label.setText("0:00")
            self._position_label.setText("0:00")
            if not self._seeking:
                self._progress_slider.setValue(0)

        is_playing = state.status == PlaybackStatus.PLAYING
        self._play_pause_btn.setText("⏸  Pause" if is_playing else "▶  Play")

        status_labels = {
            PlaybackStatus.PLAYING: "Playing",
            PlaybackStatus.PAUSED: "Paused",
            PlaybackStatus.STOPPED: "Stopped",
        }
        self._status_badge.setText(status_labels.get(state.status, "Stopped"))
        self._loop_badge.setText(f"Loop: {state.loop_mode.value.title()}")
        self._loop_btn.setText(f"↺  Loop: {state.loop_mode.value.title()}")
        self._shuffle_badge.setText("Shuffle: On" if state.shuffle else "Shuffle: Off")
        self._shuffle_btn.setChecked(state.shuffle)
        self._mute_btn.setText("Unmute" if state.muted else "Mute")

        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(int(state.volume * 100))
        self._volume_slider.blockSignals(False)

        self._refresh_queue(state)

    # ══════════════════════════════════════════════════════════════════════════
    # LIBRARY INTERACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if folder:
            self._library.add_folder(Path(folder))
            self._refresh_library_view()

    def _remove_folder(self) -> None:
        item = self._folder_list.currentItem()
        if item:
            self._library.remove_folder(item.data(Qt.UserRole))
            self._refresh_library_view()

    def _rescan_library(self) -> None:
        self._library.rescan()
        self._refresh_library_view()

    def _on_library_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        paths = self._library_tree.selected_paths()
        if not paths:
            # fall back to item under cursor if nothing is selected
            item = self._library_tree.itemAt(pos)
            if item is None:
                return
            path = item.data(0, Qt.UserRole)
            if path is None:
                return
            paths = [path]

        menu = QMenu(self)
        menu.addAction("▶  Play Now", lambda: self._state.play_queue(paths))
        menu.addAction("⏭  Queue Next", lambda: self._state.queue_next(paths))
        menu.addAction("⏬  Queue Last", lambda: self._state.queue_last(paths))
        menu.addSeparator()
        menu.addAction("➕  Add to Playlist", lambda: self._add_selection_to_playlist())
        menu.addSeparator()
        menu.addAction("✏  Edit Metadata", lambda: self._edit_track_metadata(paths[0]))
        menu.exec(self._library_tree.mapToGlobal(pos))

    def _edit_track_metadata(self, path) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        track = self._library.get_track(path)
        if track is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Metadata")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)
        title_edit = QLineEdit(track.title or "")
        title_edit.setObjectName("OverlayTextField")
        artist_edit = QLineEdit(track.artist or "")
        artist_edit.setObjectName("OverlayTextField")
        form.addRow("Title", title_edit)
        form.addRow("Artist", artist_edit)
        layout.addLayout(form)

        note = QLabel("Changes are written to the file's tags immediately.")
        note.setObjectName("MetaText")
        note.setWordWrap(True)
        layout.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        new_title  = title_edit.text().strip()
        new_artist = artist_edit.text().strip()
        if new_title and new_title != track.title:
            self._library.update_title([path], new_title)
        if new_artist != track.artist:
            self._library.update_artist([path], new_artist)
        self._refresh_library_tree()

    def _refresh_library_tree(self) -> None:
        self._library_tree.populate(self._library.tracks)

    def _refresh_library_view(self) -> None:
        self._folder_list.clear()
        for folder in self._library.folders:
            item = QListWidgetItem(str(folder.path))
            item.setData(Qt.UserRole, folder.folder_id)
            self._folder_list.addItem(item)

        tracks = self._library.tracks
        has_folders = bool(self._library.folders)
        self._empty_library_label.setVisible(not has_folders)
        self._library_tree.setVisible(has_folders)
        n = len(tracks)
        self._library_track_count.setText(
            f"{n} track{'s' if n != 1 else ''} indexed" if has_folders else ""
        )
        if has_folders:
            self._library_tree.populate(tracks)

    def _edit_artist_for_selection(self) -> None:
        paths = self._library_tree.selected_paths()
        if not paths:
            return
        current_artist = ""
        if len(paths) == 1:
            track = self._library.get_track(paths[0])
            if track:
                current_artist = track.display_artist
        new_artist, ok = QInputDialog.getText(
            self,
            "Edit Artist",
            f"New artist name for {len(paths)} selected track{'s' if len(paths) != 1 else ''}:",
            text=current_artist,
        )
        if ok and new_artist.strip():
            self._library.update_artist(paths, new_artist.strip())
            self._refresh_library_view()

    def _edit_album_for_selection(self) -> None:
        paths = self._library_tree.selected_paths()
        if not paths:
            return
        current_album = ""
        if len(paths) == 1:
            track = self._library.get_track(paths[0])
            if track:
                current_album = track.album or ""
        new_album, ok = QInputDialog.getText(
            self,
            "Edit Album",
            f"New album name for {len(paths)} selected track{'s' if len(paths) != 1 else ''}:",
            text=current_album,
        )
        if ok:
            self._library.update_album(paths, new_album.strip())
            self._refresh_library_view()

    def _add_selection_to_playlist(self) -> None:
        paths = self._library_tree.selected_paths()
        if not paths or not self._selected_playlist_id:
            return
        for path in paths:
            self._playlists.add_track(self._selected_playlist_id, path)
        self._refresh_playlist_view()   # full refresh so list labels + combo update

    # ══════════════════════════════════════════════════════════════════════════
    # PLAYLIST INTERACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_tracks_dropped_to_playlist(self, paths: list[Path]) -> None:
        if not self._selected_playlist_id:
            if not self._playlists.playlists:
                name, ok = QInputDialog.getText(self, "Create Playlist", "Create a playlist to add tracks to:")
                if ok and name.strip():
                    pl = self._playlists.create(name.strip())
                    self._selected_playlist_id = pl.playlist_id
                else:
                    return
            else:
                return
        for path in paths:
            self._playlists.add_track(self._selected_playlist_id, path)
        self._refresh_playlist_view()   # full refresh so counts update immediately

    def _create_playlist(self) -> None:
        name, ok = QInputDialog.getText(self, "New Playlist", "Playlist name:")
        if ok and name.strip():
            pl = self._playlists.create(name.strip())
            self._selected_playlist_id = pl.playlist_id
            self._refresh_playlist_view()

    def _rename_playlist(self) -> None:
        if not self._selected_playlist_id:
            return
        pl = self._playlists.get(self._selected_playlist_id)
        if pl is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Playlist", "New name:", text=pl.name)
        if ok and name.strip():
            self._playlists.rename(self._selected_playlist_id, name.strip())
            self._refresh_playlist_view()

    def _delete_playlist(self) -> None:
        if not self._selected_playlist_id:
            return
        self._playlists.delete(self._selected_playlist_id)
        self._selected_playlist_id = None
        self._refresh_playlist_view()

    def _play_selected_playlist(self) -> None:
        if not self._selected_playlist_id:
            return
        pl = self._playlists.get(self._selected_playlist_id)
        if pl and pl.tracks:
            self._state.play_queue(pl.tracks, playlist_id=pl.playlist_id)

    def _on_combo_changed(self, index: int) -> None:
        pl_id = self._playlist_combo.itemData(index)
        if not pl_id:
            return
        self._selected_playlist_id = pl_id
        # Sync the list widget selection on the library tab
        for i in range(self._playlist_list.count()):
            item = self._playlist_list.item(i)
            if item and item.data(Qt.UserRole) == pl_id:
                self._playlist_list.blockSignals(True)
                self._playlist_list.setCurrentItem(item)
                self._playlist_list.blockSignals(False)
                break
        # Stage the queue so the Play button works immediately
        pl = self._playlists.get(pl_id)
        if pl and pl.tracks:
            self._state.load_queue(pl.tracks, playlist_id=pl.playlist_id)
        self._refresh_playlist_tracks()

    def _on_playlist_selection_changed(self) -> None:
        item = self._playlist_list.currentItem()
        self._selected_playlist_id = item.data(Qt.UserRole) if item else None
        if self._selected_playlist_id:
            for i in range(self._playlist_combo.count()):
                if self._playlist_combo.itemData(i) == self._selected_playlist_id:
                    self._playlist_combo.blockSignals(True)
                    self._playlist_combo.setCurrentIndex(i)
                    self._playlist_combo.blockSignals(False)
                    break
        self._refresh_playlist_tracks()

    def _refresh_playlist_view(self) -> None:
        """Rebuild both the playlist list and the player combo, then refresh tracks."""
        prev_id = self._selected_playlist_id

        self._playlist_list.blockSignals(True)
        self._playlist_list.clear()
        self._playlist_combo.blockSignals(True)
        self._playlist_combo.clear()

        restore_list_item = None
        for pl in self._playlists.playlists:
            n = pl.track_count
            item = QListWidgetItem(f"{pl.name}  ({n} track{'s' if n != 1 else ''})")
            item.setData(Qt.UserRole, pl.playlist_id)
            self._playlist_list.addItem(item)
            self._playlist_combo.addItem(pl.name, pl.playlist_id)
            if pl.playlist_id == prev_id:
                restore_list_item = item

        self._playlist_list.blockSignals(False)
        self._playlist_combo.blockSignals(False)

        # Restore selection
        if restore_list_item:
            self._playlist_list.setCurrentItem(restore_list_item)
            for i in range(self._playlist_combo.count()):
                if self._playlist_combo.itemData(i) == prev_id:
                    self._playlist_combo.setCurrentIndex(i)
                    break
        elif self._playlist_list.count():
            self._playlist_list.setCurrentRow(0)
            first = self._playlist_list.item(0)
            if first:
                self._selected_playlist_id = first.data(Qt.UserRole)
                self._playlist_combo.setCurrentIndex(0)

        self._refresh_playlist_tracks()

    def _refresh_playlist_tracks(self) -> None:
        self._playlist_track_list.clear()
        if not self._selected_playlist_id:
            self._playlist_track_count_label.setText("Select a playlist above to see its tracks.")
            return
        pl = self._playlists.get(self._selected_playlist_id)
        if pl is None:
            return
        n = pl.track_count
        self._playlist_track_count_label.setText(
            f"{n} track{'s' if n != 1 else ''}" if n else "No tracks yet — drag from the library or use 'Add to Playlist'."
        )
        for i, path in enumerate(pl.tracks):
            track = self._library.get_track(path)
            if track:
                label = f"{i + 1}.  {track.display_artist}  —  {track.display_title}"
            else:
                label = f"{i + 1}.  {path.name}  (file missing)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            self._playlist_track_list.addItem(item)

    def _on_playlist_track_double_clicked(self, item: QListWidgetItem) -> None:
        if not self._selected_playlist_id:
            return
        pl = self._playlists.get(self._selected_playlist_id)
        if pl is None:
            return
        idx = item.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(pl.tracks):
            self._state.play_queue(pl.tracks, playlist_id=pl.playlist_id, start_index=idx)

    def _remove_track_from_playlist(self) -> None:
        item = self._playlist_track_list.currentItem()
        if item and self._selected_playlist_id:
            idx = item.data(Qt.UserRole)
            if idx is not None:
                self._playlists.remove_track(self._selected_playlist_id, idx)
                self._refresh_playlist_view()

    def _move_playlist_track(self, direction: int) -> None:
        item = self._playlist_track_list.currentItem()
        if item and self._selected_playlist_id:
            idx = item.data(Qt.UserRole)
            if idx is not None:
                self._playlists.move_track(self._selected_playlist_id, idx, idx + direction)
                self._refresh_playlist_tracks()

    def _filter_library(self, text: str) -> None:
        q = text.strip().lower()
        tree = self._library_tree
        for i in range(tree.topLevelItemCount()):
            artist_item = tree.topLevelItem(i)
            artist_match = q in artist_item.text(0).lower()
            any_visible_album = False
            for j in range(artist_item.childCount()):
                album_item = artist_item.child(j)
                album_match = q in album_item.text(0).lower()
                any_visible_track = False
                for k in range(album_item.childCount()):
                    track_item = album_item.child(k)
                    track_match = (
                        q in track_item.text(0).lower()
                        or artist_match
                        or album_match
                    )
                    track_item.setHidden(not track_match if q else False)
                    if track_match or not q:
                        any_visible_track = True
                album_item.setHidden(not (album_match or any_visible_track or artist_match) if q else False)
                if album_match or any_visible_track or artist_match or not q:
                    any_visible_album = True
            artist_item.setHidden(not (artist_match or any_visible_album) if q else False)
            if q and (artist_match or any_visible_album):
                artist_item.setExpanded(True)

    def _play_library(self, shuffle: bool = False) -> None:
        import random as _random
        tracks = self._library.tracks
        if not tracks:
            return
        paths = [t.path for t in tracks]
        if shuffle:
            _random.shuffle(paths)
            if not self._state.state.shuffle:
                self._state.toggle_shuffle()  # ensure shuffle mode is on
        self._state.play_queue(paths)

    def _queue_playlist(self) -> None:
        if not self._selected_playlist_id:
            return
        pl = self._playlists.get(self._selected_playlist_id)
        if not pl:
            return
        paths = [Path(p) for p in pl.tracks]
        self._state.queue_last(paths)

    def _refresh_queue(self, state: "PlaybackState") -> None:
        from PySide6.QtGui import QColor
        queue_len = len(state.queue)
        queue_index = state.queue_index
        queue_changed = queue_len != self._last_queue_len
        index_changed = queue_index != self._last_queue_index
        self._last_queue_len = queue_len
        self._last_queue_index = queue_index

        if not queue_changed and not index_changed:
            return

        self._queue_list.blockSignals(True)
        if queue_changed:
            self._queue_list.clear()
            for i, path in enumerate(state.queue):
                track = self._library.get_track(path)
                if track:
                    label = f"{track.display_artist} — {track.display_title}" if track.artist else track.display_title
                else:
                    label = path.stem
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, i)
                self._queue_list.addItem(item)

        # Update highlighting without rebuilding when only index changed
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            font = item.font()
            if i == queue_index:
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor("#a78bfa"))
            else:
                font.setBold(False)
                item.setFont(font)
                item.setForeground(QColor())  # reset to default

        self._queue_list.blockSignals(False)

        # Only scroll when the playing track actually changes
        if index_changed and 0 <= queue_index < self._queue_list.count():
            self._queue_list.scrollToItem(
                self._queue_list.item(queue_index),
                QAbstractItemView.PositionAtCenter,
            )

    def _on_queue_item_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.UserRole)
        state = self._state.state
        self._state.play_queue(state.queue, start_index=idx)

    def _queue_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._queue_list.itemAt(pos)
        if not item:
            return
        idx = item.data(Qt.UserRole)
        state = self._state.state
        menu = QMenu(self)
        menu.addAction("▶  Play Now", lambda: self._state.play_queue(state.queue, start_index=idx))
        menu.addAction("✕  Remove from Queue", lambda: self._remove_from_queue(idx))
        menu.exec(self._queue_list.mapToGlobal(pos))

    def _remove_from_queue(self, idx: int) -> None:
        self._state.remove_from_queue(idx)

    # ── device + seek ─────────────────────────────────────────────────────────

    def _on_device_changed(self, index: int) -> None:
        device_name = self._device_combo.itemData(index)
        self._state.set_output_device(device_name)

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        state = self._state.state
        if state.current_track and state.current_track.duration > 0:
            pct = self._progress_slider.value() / 1000.0
            self._state.seek(pct * state.current_track.duration)
        self._seeking = False


# ── helpers ───────────────────────────────────────────────────────────────────

def _tbtn(text: str, *, primary: bool = False, checkable: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("MusicPlayButton" if primary else "MusicTransportButton")
    if checkable:
        btn.setCheckable(True)
    return btn


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("MusicFieldLabel")
    return lbl


def _fmt_time(seconds: float) -> str:
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"
