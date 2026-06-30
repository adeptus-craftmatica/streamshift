from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.music_manager.models import PlaybackState, PlaybackStatus
    from stream_controller.plugins.music_manager.music_state import MusicState
    from stream_controller.plugins.music_manager.playlist_service import PlaylistService


class MusicPlayerCardTile(QFrame):
    """
    Rich embedded tile showing full music transport controls.
    Registered as a widget_factory so it renders inline on any deck page.
    Subscribe to music_state changes so it refreshes automatically.
    """

    def __init__(
        self,
        music_state: "MusicState",
        playlists: "PlaylistService",
    ) -> None:
        super().__init__()
        self._state = music_state
        self._playlists = playlists
        self._seeking = False

        self.setObjectName("MusicPlayerCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # ── Now Playing ──────────────────────────────────────────────────────
        now_playing = QHBoxLayout()
        now_playing.setSpacing(14)

        art = QFrame()
        art.setObjectName("MusicAlbumArt")
        art.setFixedSize(54, 54)
        art_layout = QVBoxLayout(art)
        art_layout.setContentsMargins(0, 0, 0, 0)
        self._art_label = QLabel("♪")
        self._art_label.setObjectName("MusicAlbumArtLabel")
        self._art_label.setAlignment(Qt.AlignCenter)
        art_layout.addWidget(self._art_label)
        now_playing.addWidget(art, 0, Qt.AlignVCenter)

        track_col = QVBoxLayout()
        track_col.setSpacing(2)
        self._title_label = QLabel("No track playing")
        self._title_label.setObjectName("MusicTrackTitle")
        font = self._title_label.font()
        font.setPointSize(14)
        self._title_label.setFont(font)
        self._title_label.setWordWrap(True)
        self._artist_label = QLabel("—")
        self._artist_label.setObjectName("MusicTrackArtist")
        track_col.addWidget(self._title_label)
        track_col.addWidget(self._artist_label)
        now_playing.addLayout(track_col, 1)

        self._status_label = QLabel("Stopped")
        self._status_label.setObjectName("MetaText")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        now_playing.addWidget(self._status_label, 0, Qt.AlignTop)
        root.addLayout(now_playing)

        # ── Seek bar ─────────────────────────────────────────────────────────
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        self._pos_label = QLabel("0:00")
        self._pos_label.setObjectName("MusicTimeLabel")
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setObjectName("MusicProgressSlider")
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderPressed.connect(self._on_seek_start)
        self._seek_slider.sliderReleased.connect(self._on_seek_end)
        self._dur_label = QLabel("0:00")
        self._dur_label.setObjectName("MusicTimeLabel")
        seek_row.addWidget(self._pos_label)
        seek_row.addWidget(self._seek_slider, 1)
        seek_row.addWidget(self._dur_label)
        root.addLayout(seek_row)

        # ── Transport ────────────────────────────────────────────────────────
        transport = QHBoxLayout()
        transport.setSpacing(6)

        self._prev_btn = _btn("Prev")
        self._prev_btn.clicked.connect(self._state.previous_track)
        self._play_btn = _btn("Play", primary=True)
        self._play_btn.clicked.connect(self._state.play_pause)
        self._next_btn = _btn("Next")
        self._next_btn.clicked.connect(self._state.next_track)
        self._stop_btn = _btn("Stop")
        self._stop_btn.clicked.connect(self._state.stop)
        self._shuffle_btn = _btn("Shuffle", checkable=True)
        self._shuffle_btn.clicked.connect(lambda: self._state.toggle_shuffle())
        self._loop_btn = _btn("Loop: Off")
        self._loop_btn.setMinimumWidth(80)
        self._loop_btn.clicked.connect(lambda: self._state.cycle_loop_mode())

        transport.addWidget(self._prev_btn)
        transport.addWidget(self._play_btn)
        transport.addWidget(self._next_btn)
        transport.addWidget(self._stop_btn)
        transport.addSpacing(8)
        transport.addWidget(self._shuffle_btn)
        transport.addWidget(self._loop_btn)
        transport.addStretch(1)
        root.addLayout(transport)

        # ── Volume + Output ───────────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        bottom.addWidget(_lbl("Vol"))
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setObjectName("MusicVolumeSlider")
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(90)
        self._vol_slider.valueChanged.connect(lambda v: self._state.set_volume(v / 100.0))
        self._mute_btn = _btn("Mute")
        self._mute_btn.clicked.connect(lambda: self._state.toggle_mute())
        bottom.addWidget(self._vol_slider)
        bottom.addWidget(self._mute_btn)

        bottom.addSpacing(12)
        bottom.addWidget(_lbl("Playlist"))
        self._playlist_combo = QComboBox()
        self._playlist_combo.setMinimumWidth(160)
        self._playlist_combo.setMaxVisibleItems(12)
        self._playlist_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._playlist_combo.view().setMinimumWidth(200)
        self._playlist_combo.currentIndexChanged.connect(self._on_playlist_changed)
        bottom.addWidget(self._playlist_combo)

        bottom.addSpacing(12)
        bottom.addWidget(_lbl("Output"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(180)
        self._device_combo.setMaxVisibleItems(12)
        self._device_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._device_combo.view().setMinimumWidth(260)
        self._device_combo.setToolTip(
            "To capture this device in OBS:\n"
            "OBS → Settings → Audio → set a Mic/Auxiliary Audio slot to this device,\n"
            "or add an Audio Input Capture source in your scene."
        )
        self._device_combo.addItem("System Default", None)
        for _i, name in self._state.list_output_devices():
            self._device_combo.addItem(name, name)
        current_dev = self._state.selected_device
        if current_dev:
            idx = self._device_combo.findData(current_dev)
            if idx >= 0:
                self._device_combo.setCurrentIndex(idx)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        bottom.addWidget(self._device_combo)
        bottom.addStretch(1)
        root.addLayout(bottom)

        # Unsubscribe when the C++ object is destroyed (deleteLater doesn't fire closeEvent)
        self.destroyed.connect(self._on_destroyed)
        self._state.subscribe(self._on_state_changed)
        self._refresh_playlists()

    def _refresh_playlists(self) -> None:
        self._playlist_combo.blockSignals(True)
        self._playlist_combo.clear()
        self._playlist_combo.addItem("— No Playlist —", None)
        for pl in self._playlists.playlists:
            self._playlist_combo.addItem(pl.name, pl.playlist_id)
        self._playlist_combo.blockSignals(False)

    # ── state updates ─────────────────────────────────────────────────────────

    def _on_state_changed(self, state: "PlaybackState") -> None:
        from stream_controller.plugins.music_manager.models import PlaybackStatus

        track = state.current_track
        if track:
            self._title_label.setText(track.display_title)
            self._artist_label.setText(track.display_artist)
            self._art_label.setText(track.display_title[:2].upper())
            self._dur_label.setText(track.duration_str)
            if not self._seeking and track.duration > 0:
                self._seek_slider.setValue(int((state.position / track.duration) * 1000))
            self._pos_label.setText(_fmt(state.position))
        else:
            self._title_label.setText("No track playing")
            self._artist_label.setText("—")
            self._art_label.setText("♪")
            self._dur_label.setText("0:00")
            self._pos_label.setText("0:00")
            if not self._seeking:
                self._seek_slider.setValue(0)

        is_playing = state.status == PlaybackStatus.PLAYING
        self._play_btn.setText("Pause" if is_playing else "Play")
        status_map = {
            PlaybackStatus.PLAYING: "Playing",
            PlaybackStatus.PAUSED: "Paused",
            PlaybackStatus.STOPPED: "Stopped",
        }
        self._status_label.setText(status_map.get(state.status, "Stopped"))
        self._loop_btn.setText(f"Loop: {state.loop_mode.value.title()}")
        self._shuffle_btn.setChecked(state.shuffle)
        self._mute_btn.setText("Unmute" if state.muted else "Mute")

        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(int(state.volume * 100))
        self._vol_slider.blockSignals(False)

    def _on_playlist_changed(self, index: int) -> None:
        pl_id = self._playlist_combo.itemData(index)
        if pl_id is None:
            return
        pl = self._playlists.get(pl_id)
        if pl and pl.tracks:
            self._state.load_queue(pl.tracks, playlist_id=pl.playlist_id)

    def _on_device_changed(self, index: int) -> None:
        device_name = self._device_combo.itemData(index)
        self._state.set_output_device(device_name)

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        state = self._state.state
        if state.current_track and state.current_track.duration > 0:
            pct = self._seek_slider.value() / 1000.0
            self._state.seek(pct * state.current_track.duration)
        self._seeking = False

    def _on_destroyed(self) -> None:
        self._state.unsubscribe(self._on_state_changed)

    def closeEvent(self, event) -> None:
        self._state.unsubscribe(self._on_state_changed)
        super().closeEvent(event)


# ── helpers ───────────────────────────────────────────────────────────────────

def _btn(text: str, *, primary: bool = False, checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("MusicPlayButton" if primary else "MusicTransportButton")
    if checkable:
        b.setCheckable(True)
    return b


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setObjectName("MusicFieldLabel")
    return l


def _fmt(seconds: float) -> str:
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"
