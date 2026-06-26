from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False
    logger.warning("pygame not installed — audio playback unavailable. Run: pip install pygame")

try:
    import sounddevice as _sd
    _SOUNDDEVICE_AVAILABLE = True
except ImportError:
    _SOUNDDEVICE_AVAILABLE = False
    logger.info("sounddevice not installed — output device selection unavailable. Run: pip install sounddevice")


def list_output_devices() -> list[tuple[int, str]]:
    """
    Return (index, name) pairs for all output devices reported by PortAudio.
    Returns an empty list if sounddevice is not installed.
    """
    if not _SOUNDDEVICE_AVAILABLE:
        return []
    try:
        devices = _sd.query_devices()
        return [
            (i, d["name"])
            for i, d in enumerate(devices)
            if d["max_output_channels"] > 0
        ]
    except Exception as exc:
        logger.warning("Could not query audio devices: %s", exc)
        return []


class AudioBackend:
    """
    Thin wrapper around pygame.mixer providing play/pause/stop/seek/volume.

    Output device routing is done via SDL2's SDL_AUDIODEVICE environment
    variable, which is set before pygame.mixer is (re)initialised.
    Device names are sourced from sounddevice (PortAudio).
    """

    def __init__(self) -> None:
        self._initialised = False
        self._current_path: Path | None = None
        self._lock = threading.Lock()
        self._end_event_id: int | None = None
        self._selected_device: str | None = None   # SDL device name, None = system default
        self._seek_offset: float = 0.0             # seconds seeked to; added to get_pos()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def initialise(self) -> bool:
        if not _PYGAME_AVAILABLE:
            return False
        if self._initialised:
            return True
        return self._init_mixer()

    def _init_mixer(self) -> bool:
        try:
            if self._selected_device:
                os.environ["SDL_AUDIODEVICE"] = self._selected_device
            else:
                os.environ.pop("SDL_AUDIODEVICE", None)
            pygame.mixer.pre_init(44100, -16, 2, 2048)
            pygame.mixer.init()
            self._end_event_id = pygame.USEREVENT + 1
            pygame.mixer.music.set_endevent(self._end_event_id)
            self._initialised = True
            device_label = self._selected_device or "system default"
            logger.info("pygame.mixer initialised — output: %s", device_label)
            return True
        except Exception as exc:
            logger.error("Failed to initialise pygame.mixer: %s", exc)
            return False

    def shutdown(self) -> None:
        if self._initialised and _PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception:
                pass
        self._initialised = False

    # ── device selection ─────────────────────────────────────────────────────

    @staticmethod
    def list_output_devices() -> list[tuple[int, str]]:
        return list_output_devices()

    def set_output_device(self, device_name: str | None) -> bool:
        """
        Switch output to the named device (or system default if None).
        Stops any active playback, reinitialises pygame.mixer with the new device.
        Returns True if initialisation succeeded.
        """
        was_playing = self.is_playing()
        current_path = self._current_path
        pos = self.get_position() if was_playing else 0.0

        self.shutdown()
        self._selected_device = device_name or None
        ok = self._init_mixer()

        # Resume on the same track at the same position if we were playing
        if ok and current_path is not None:
            self.load(current_path)
            if was_playing:
                self.seek(pos)
                self.play()

        return ok

    @property
    def selected_device(self) -> str | None:
        return self._selected_device

    # ── playback ─────────────────────────────────────────────────────────────

    def load(self, path: Path) -> bool:
        if not self._initialised:
            return False
        try:
            pygame.mixer.music.load(str(path))
            self._current_path = path
            self._seek_offset = 0.0
            return True
        except Exception as exc:
            logger.error("Failed to load %s: %s", path, exc)
            return False

    def play(self) -> bool:
        if not self._initialised:
            return False
        try:
            pygame.mixer.music.play()
            self._seek_offset = 0.0
            return True
        except Exception as exc:
            logger.error("Playback error: %s", exc)
            return False

    def pause(self) -> None:
        if self._initialised:
            pygame.mixer.music.pause()

    def unpause(self) -> None:
        if self._initialised:
            pygame.mixer.music.unpause()

    def stop(self) -> None:
        if self._initialised:
            pygame.mixer.music.stop()
            self._current_path = None

    def set_volume(self, volume: float) -> None:
        if self._initialised:
            pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))

    def get_position(self) -> float:
        if not self._initialised:
            return 0.0
        try:
            ms = pygame.mixer.music.get_pos()
            return self._seek_offset + max(0.0, ms / 1000.0)
        except Exception:
            return 0.0

    def seek(self, seconds: float) -> None:
        if not self._initialised or self._current_path is None:
            return
        try:
            pygame.mixer.music.play(start=seconds)
            self._seek_offset = seconds
        except Exception as exc:
            logger.warning("Seek failed: %s", exc)

    def pump_events(self) -> None:
        if self._initialised:
            try:
                pygame.event.pump()
            except Exception:
                pass

    def is_playing(self) -> bool:
        if not self._initialised:
            return False
        return pygame.mixer.music.get_busy()

    def check_end_event(self) -> bool:
        if not self._initialised or self._end_event_id is None:
            return False
        try:
            return bool(pygame.event.peek(self._end_event_id))
        except Exception:
            return False

    def consume_end_event(self) -> None:
        if self._initialised and self._end_event_id is not None:
            try:
                pygame.event.clear(self._end_event_id)
            except Exception:
                pass

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def available(self) -> bool:
        return _PYGAME_AVAILABLE and self._initialised
