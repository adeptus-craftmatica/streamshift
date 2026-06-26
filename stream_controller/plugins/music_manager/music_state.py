from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Callable

from stream_controller.plugins.music_manager.audio_backend import AudioBackend
from stream_controller.plugins.music_manager.library_service import LibraryService
from stream_controller.plugins.music_manager.metadata_service import read_track
from stream_controller.plugins.music_manager.models import (
    LoopMode,
    PlaybackState,
    PlaybackStatus,
    Track,
)

logger = logging.getLogger(__name__)

StateChangeCallback = Callable[[PlaybackState], None]


class MusicState:
    """
    Coordinates the audio backend and playback queue.
    All public methods are safe to call from the UI thread.
    """

    def __init__(self, backend: AudioBackend, library: LibraryService) -> None:
        self._backend = backend
        self._library = library
        self._state = PlaybackState()
        self._listeners: list[StateChangeCallback] = []

    # ── listener management ──────────────────────────────────────────────────

    def subscribe(self, callback: StateChangeCallback) -> None:
        self._listeners.append(callback)

    def unsubscribe(self, callback: StateChangeCallback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify(self) -> None:
        dead = []
        for cb in list(self._listeners):
            try:
                cb(self._state)
            except RuntimeError as exc:
                # shiboken "C++ object already deleted" — widget was destroyed
                # before it could unsubscribe; remove it automatically
                dead.append(cb)
                logger.debug("Auto-removing dead state listener: %s", exc)
            except Exception as exc:
                logger.warning("State listener raised: %s", exc)
        for cb in dead:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

    # ── state access ─────────────────────────────────────────────────────────

    @property
    def state(self) -> PlaybackState:
        return self._state

    # ── queue management ─────────────────────────────────────────────────────

    def play_queue(self, paths: list[Path], playlist_id: str | None = None, start_index: int = 0) -> None:
        self._state.queue = list(paths)
        self._state.current_playlist_id = playlist_id
        self._state.queue_index = max(0, min(start_index, len(paths) - 1))
        self._play_current()

    def load_queue(self, paths: list[Path], playlist_id: str | None = None, start_index: int = 0) -> None:
        """Stage a queue without starting playback. Press play to begin."""
        self._backend.stop()
        self._state.queue = list(paths)
        self._state.current_playlist_id = playlist_id
        self._state.queue_index = max(0, min(start_index, len(paths) - 1))
        self._state.status = PlaybackStatus.STOPPED
        self._state.current_track = None
        self._state.position = 0.0
        self._notify()

    def play_track(self, path: Path) -> None:
        self._state.queue = [path]
        self._state.queue_index = 0
        self._state.current_playlist_id = None
        self._play_current()

    def _play_current(self) -> None:
        if not self._state.queue:
            return
        idx = self._state.queue_index
        if idx < 0 or idx >= len(self._state.queue):
            return
        path = self._state.queue[idx]
        if not path.exists():
            logger.warning("Track file missing: %s", path)
            self._notify()
            return

        track = self._library.get_track(path) or read_track(path)
        self._state.current_track = track
        self._state.position = 0.0

        if self._backend.load(path) and self._backend.play():
            self._backend.set_volume(self._state.volume if not self._state.muted else 0.0)
            self._state.status = PlaybackStatus.PLAYING
        else:
            self._state.status = PlaybackStatus.STOPPED
        self._notify()

    # ── transport ────────────────────────────────────────────────────────────

    def play_pause(self) -> None:
        if self._state.status == PlaybackStatus.PLAYING:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self._state.status == PlaybackStatus.PAUSED:
            self._backend.unpause()
            self._state.status = PlaybackStatus.PLAYING
            self._notify()
        elif self._state.status == PlaybackStatus.STOPPED and self._state.queue:
            self._play_current()
        elif self._state.current_track is None and not self._state.queue:
            pass

    def pause(self) -> None:
        if self._state.status == PlaybackStatus.PLAYING:
            self._backend.pause()
            self._state.status = PlaybackStatus.PAUSED
            self._notify()

    def stop(self) -> None:
        self._backend.stop()
        self._state.status = PlaybackStatus.STOPPED
        self._state.current_track = None
        self._state.position = 0.0
        self._notify()

    def next_track(self) -> None:
        if not self._state.queue:
            return
        if self._state.shuffle:
            self._state.queue_index = random.randint(0, len(self._state.queue) - 1)
        elif self._state.queue_index < len(self._state.queue) - 1:
            self._state.queue_index += 1
        elif self._state.loop_mode in {LoopMode.PLAYLIST, LoopMode.RANDOM}:
            self._state.queue_index = 0
        else:
            self.stop()
            return
        self._play_current()

    def previous_track(self) -> None:
        if not self._state.queue:
            return
        if self._state.queue_index > 0:
            self._state.queue_index -= 1
        elif self._state.loop_mode in {LoopMode.PLAYLIST, LoopMode.RANDOM}:
            self._state.queue_index = len(self._state.queue) - 1
        else:
            return
        self._play_current()

    def seek(self, seconds: float) -> None:
        self._backend.seek(seconds)
        self._state.position = seconds
        self._notify()

    def set_volume(self, volume: float) -> None:
        self._state.volume = max(0.0, min(1.0, volume))
        if not self._state.muted:
            self._backend.set_volume(self._state.volume)
        self._notify()

    def volume_up(self, step: float = 0.1) -> None:
        self.set_volume(self._state.volume + step)

    def volume_down(self, step: float = 0.1) -> None:
        self.set_volume(self._state.volume - step)

    def toggle_mute(self) -> None:
        self._state.muted = not self._state.muted
        self._backend.set_volume(0.0 if self._state.muted else self._state.volume)
        self._notify()

    def toggle_shuffle(self) -> None:
        self._state.shuffle = not self._state.shuffle
        self._notify()

    def cycle_loop_mode(self) -> None:
        modes = list(LoopMode)
        current_index = modes.index(self._state.loop_mode)
        self._state.loop_mode = modes[(current_index + 1) % len(modes)]
        self._notify()

    def set_loop_mode(self, mode: LoopMode) -> None:
        self._state.loop_mode = mode
        self._notify()

    # ── device selection ─────────────────────────────────────────────────────

    def list_output_devices(self) -> list[tuple[int, str]]:
        return self._backend.list_output_devices()

    def set_output_device(self, device_name: str | None) -> None:
        self._backend.set_output_device(device_name)
        self._notify()

    @property
    def selected_device(self) -> str | None:
        return self._backend.selected_device

    # ── tick (called by timer) ────────────────────────────────────────────────

    def tick(self) -> None:
        """Poll audio backend state; call from a QTimer every ~500ms."""
        self._backend.pump_events()

        if self._state.status == PlaybackStatus.PLAYING:
            # If pygame is no longer busy, the track ended naturally
            if not self._backend.is_playing():
                self._backend.consume_end_event()  # clear any pending event
                self._on_track_ended()
                return
            self._state.position = self._backend.get_position()
            self._notify()

        # Belt-and-suspenders: also catch the end event if is_playing() races
        if self._backend.check_end_event():
            self._backend.consume_end_event()
            if self._state.status == PlaybackStatus.PLAYING:
                self._on_track_ended()

    def _on_track_ended(self) -> None:
        loop = self._state.loop_mode
        if loop == LoopMode.TRACK:
            self._play_current()
        elif loop == LoopMode.ONCE:
            self._state.status = PlaybackStatus.STOPPED
            self._notify()
        elif loop == LoopMode.OFF:
            if self._state.queue_index < len(self._state.queue) - 1:
                self._state.queue_index += 1
                self._play_current()
            else:
                self._state.status = PlaybackStatus.STOPPED
                self._notify()
        elif loop in {LoopMode.PLAYLIST, LoopMode.RANDOM}:
            if self._state.shuffle:
                self._state.queue_index = random.randint(0, len(self._state.queue) - 1)
            else:
                self._state.queue_index = (self._state.queue_index + 1) % len(self._state.queue)
            self._play_current()
