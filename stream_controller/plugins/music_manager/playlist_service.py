from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.plugins.music_manager.models import Playlist
from stream_controller.plugins.music_manager.music_repository import MusicRepository

logger = logging.getLogger(__name__)


class PlaylistService:
    """CRUD and in-memory management for playlists."""

    def __init__(self, repository: MusicRepository) -> None:
        self._repo = repository
        self._playlists: dict[str, Playlist] = {}

    def load(self) -> None:
        self._playlists = {p.playlist_id: p for p in self._repo.get_playlists()}

    @property
    def playlists(self) -> list[Playlist]:
        return list(self._playlists.values())

    def get(self, playlist_id: str) -> Playlist | None:
        return self._playlists.get(playlist_id)

    def create(self, name: str) -> Playlist:
        pl = Playlist(name=name)
        self._playlists[pl.playlist_id] = pl
        self._repo.save_playlist(pl)
        return pl

    def rename(self, playlist_id: str, new_name: str) -> None:
        pl = self._playlists.get(playlist_id)
        if pl:
            pl.name = new_name
            self._repo.save_playlist(pl)

    def delete(self, playlist_id: str) -> None:
        self._playlists.pop(playlist_id, None)
        self._repo.delete_playlist(playlist_id)

    def add_track(self, playlist_id: str, path: Path) -> None:
        pl = self._playlists.get(playlist_id)
        if pl:
            pl.tracks.append(path)
            self._repo.save_playlist(pl)

    def remove_track(self, playlist_id: str, index: int) -> None:
        pl = self._playlists.get(playlist_id)
        if pl and 0 <= index < len(pl.tracks):
            pl.tracks.pop(index)
            self._repo.save_playlist(pl)

    def move_track(self, playlist_id: str, from_index: int, to_index: int) -> None:
        pl = self._playlists.get(playlist_id)
        if pl is None:
            return
        if not (0 <= from_index < len(pl.tracks) and 0 <= to_index < len(pl.tracks)):
            return
        track = pl.tracks.pop(from_index)
        pl.tracks.insert(to_index, track)
        self._repo.save_playlist(pl)
