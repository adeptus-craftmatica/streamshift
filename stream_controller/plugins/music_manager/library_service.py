from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.plugins.music_manager.metadata_service import read_track, write_album, write_artist, write_title, write_track_number
from stream_controller.plugins.music_manager.models import (
    MusicLibraryFolder,
    SUPPORTED_EXTENSIONS,
    Track,
)
from stream_controller.plugins.music_manager.music_repository import MusicRepository

logger = logging.getLogger(__name__)


class LibraryService:
    """Manages music library folders and their in-memory track index."""

    def __init__(self, repository: MusicRepository) -> None:
        self._repo = repository
        self._folders: list[MusicLibraryFolder] = []
        self._tracks: dict[Path, Track] = {}

    def load(self) -> None:
        self._folders = self._repo.get_folders()
        self._tracks = {}
        for folder in self._folders:
            self._scan_folder(folder.path)

    @property
    def folders(self) -> list[MusicLibraryFolder]:
        return list(self._folders)

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    def add_folder(self, path: Path) -> MusicLibraryFolder | None:
        path = path.resolve()
        if not path.is_dir():
            logger.warning("add_folder: %s is not a directory", path)
            return None
        for f in self._folders:
            if f.path == path:
                return f
        folder = MusicLibraryFolder(path=path)
        self._repo.add_folder(folder)
        self._folders.append(folder)
        self._scan_folder(path)
        return folder

    def remove_folder(self, folder_id: str) -> None:
        folder = next((f for f in self._folders if f.folder_id == folder_id), None)
        if folder is None:
            return
        self._repo.remove_folder(folder_id)
        self._folders = [f for f in self._folders if f.folder_id != folder_id]
        self._tracks = {p: t for p, t in self._tracks.items() if not _is_under(p, folder.path)}

    def rescan(self) -> None:
        self._tracks = {}
        for folder in self._folders:
            self._scan_folder(folder.path)

    def get_track(self, path: Path) -> Track | None:
        return self._tracks.get(path.resolve())

    def update_artist(self, paths: list[Path], new_artist: str) -> tuple[int, list[Path]]:
        """Update the artist tag for a list of tracks. Returns (success_count, failed_paths)."""
        updated, failed = 0, []
        for path in paths:
            rp = path.resolve()
            track = self._tracks.get(rp)
            if track is None:
                continue
            old = track.artist
            track.artist = new_artist
            if write_artist(rp, new_artist):
                updated += 1
            else:
                track.artist = old
                failed.append(rp)
        return updated, failed

    def update_title(self, paths: list[Path], new_title: str) -> tuple[int, list[Path]]:
        """Update the title tag for a list of tracks. Returns (success_count, failed_paths)."""
        updated, failed = 0, []
        for path in paths:
            rp = path.resolve()
            track = self._tracks.get(rp)
            if track is None:
                continue
            old = track.title
            track.title = new_title
            if write_title(rp, new_title):
                updated += 1
            else:
                track.title = old
                failed.append(rp)
        return updated, failed

    def update_album(self, paths: list[Path], new_album: str) -> tuple[int, list[Path]]:
        """Update the album tag for a list of tracks. Returns (success_count, failed_paths)."""
        updated, failed = 0, []
        for path in paths:
            rp = path.resolve()
            track = self._tracks.get(rp)
            if track is None:
                continue
            old = track.album
            track.album = new_album
            if write_album(rp, new_album):
                updated += 1
            else:
                track.album = old
                failed.append(rp)
        return updated, failed

    def update_track_number(self, paths: list[Path], track_number: int) -> tuple[int, list[Path]]:
        """Update the track number tag for a list of tracks. Returns (success_count, failed_paths)."""
        updated, failed = 0, []
        for path in paths:
            rp = path.resolve()
            track = self._tracks.get(rp)
            if track is None:
                continue
            old = track.track_number
            track.track_number = track_number
            if write_track_number(rp, track_number):
                updated += 1
            else:
                track.track_number = old
                failed.append(rp)
        return updated, failed

    def _scan_folder(self, folder_path: Path) -> None:
        if not folder_path.exists():
            logger.warning("Library folder does not exist: %s", folder_path)
            return
        found = 0
        for p in folder_path.rglob("*"):
            if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file():
                rp = p.resolve()
                if rp not in self._tracks:
                    track = read_track(rp)
                    self._tracks[rp] = track
                    found += 1
        logger.info("Scanned %s — found %d new track(s)", folder_path, found)


def _is_under(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False
