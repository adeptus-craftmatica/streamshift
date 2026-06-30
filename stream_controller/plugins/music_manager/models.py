from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LoopMode(str, Enum):
    OFF = "off"
    TRACK = "track"
    PLAYLIST = "playlist"
    ONCE = "once"
    RANDOM = "random"


class PlaybackStatus(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


SUPPORTED_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a"})


@dataclass(slots=True)
class Track:
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0  # seconds
    track_number: int = 0

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.path.stem

    @property
    def display_title(self) -> str:
        return self.title or self.path.stem

    @property
    def display_artist(self) -> str:
        return self.artist or "Unknown Artist"

    @property
    def duration_str(self) -> str:
        total = int(self.duration)
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


@dataclass
class Playlist:
    name: str
    tracks: list[Path] = field(default_factory=list)
    playlist_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def track_count(self) -> int:
        return len(self.tracks)


@dataclass
class MusicLibraryFolder:
    path: Path
    folder_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PlaybackState:
    status: PlaybackStatus = PlaybackStatus.STOPPED
    current_track: Track | None = None
    current_playlist_id: str | None = None
    queue: list[Path] = field(default_factory=list)
    queue_index: int = 0
    position: float = 0.0  # seconds
    volume: float = 0.8
    muted: bool = False
    shuffle: bool = False
    loop_mode: LoopMode = LoopMode.OFF
