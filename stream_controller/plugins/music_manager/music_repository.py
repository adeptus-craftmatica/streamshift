from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from stream_controller.plugins.music_manager.models import (
    MusicLibraryFolder,
    Playlist,
)

logger = logging.getLogger(__name__)


class MusicRepository:
    """SQLite-backed persistence for the Music Manager plugin."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    # ── schema ───────────────────────────────────────────────────────────────

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS library_folders (
                id   TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS playlists (
                id     TEXT PRIMARY KEY,
                name   TEXT NOT NULL,
                tracks TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── library folders ──────────────────────────────────────────────────────

    def get_folders(self) -> list[MusicLibraryFolder]:
        rows = self._conn.execute("SELECT id, path FROM library_folders ORDER BY path").fetchall()
        return [MusicLibraryFolder(path=Path(r["path"]), folder_id=r["id"]) for r in rows]

    def add_folder(self, folder: MusicLibraryFolder) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO library_folders (id, path) VALUES (?, ?)",
            (folder.folder_id, str(folder.path)),
        )
        self._conn.commit()

    def remove_folder(self, folder_id: str) -> None:
        self._conn.execute("DELETE FROM library_folders WHERE id = ?", (folder_id,))
        self._conn.commit()

    # ── playlists ────────────────────────────────────────────────────────────

    def get_playlists(self) -> list[Playlist]:
        rows = self._conn.execute("SELECT id, name, tracks FROM playlists ORDER BY name").fetchall()
        result = []
        for r in rows:
            try:
                tracks = [Path(p) for p in json.loads(r["tracks"])]
            except (json.JSONDecodeError, TypeError):
                tracks = []
            result.append(Playlist(name=r["name"], tracks=tracks, playlist_id=r["id"]))
        return result

    def save_playlist(self, playlist: Playlist) -> None:
        tracks_json = json.dumps([str(p) for p in playlist.tracks])
        self._conn.execute(
            "INSERT OR REPLACE INTO playlists (id, name, tracks) VALUES (?, ?, ?)",
            (playlist.playlist_id, playlist.name, tracks_json),
        )
        self._conn.commit()

    def delete_playlist(self, playlist_id: str) -> None:
        self._conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        self._conn.commit()

    # ── preferences ──────────────────────────────────────────────────────────

    def get_pref(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def set_pref(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
