from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.plugins.music_manager.models import Track

logger = logging.getLogger(__name__)

try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    _MUTAGEN_AVAILABLE = True
except ImportError:
    _MUTAGEN_AVAILABLE = False
    logger.warning("mutagen not installed — metadata will use filenames only. Run: pip install mutagen")


def read_track(path: Path) -> Track:
    """Read a Track from the given audio file path, populating metadata if mutagen is available."""
    track = Track(path=path, title=path.stem)
    if not _MUTAGEN_AVAILABLE:
        return track

    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            _read_mp3(path, track)
        elif ext == ".flac":
            _read_flac(path, track)
        elif ext in {".m4a", ".mp4"}:
            _read_mp4(path, track)
        elif ext == ".ogg":
            _read_ogg(path, track)
        elif ext == ".wav":
            import wave
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                track.duration = frames / float(rate)
    except Exception as exc:
        logger.debug("Could not read metadata for %s: %s", path, exc)

    return track


def _read_mp3(path: Path, track: Track) -> None:
    try:
        audio = MP3(str(path))
        track.duration = audio.info.length
    except Exception:
        pass
    try:
        from mutagen.easyid3 import EasyID3
        tags = EasyID3(str(path))
        track.title = _first(tags.get("title")) or path.stem
        track.artist = _first(tags.get("artist")) or ""
        track.album = _first(tags.get("album")) or ""
        tn = _first(tags.get("tracknumber"))
        if tn:
            track.track_number = int(str(tn).split("/")[0])
    except Exception:
        pass


def _read_flac(path: Path, track: Track) -> None:
    audio = FLAC(str(path))
    track.duration = audio.info.length
    track.title = _first(audio.get("title")) or path.stem
    track.artist = _first(audio.get("artist")) or ""
    track.album = _first(audio.get("album")) or ""
    tn = _first(audio.get("tracknumber"))
    if tn:
        track.track_number = int(str(tn).split("/")[0])


def _read_mp4(path: Path, track: Track) -> None:
    audio = MP4(str(path))
    track.duration = audio.info.length
    track.title = _first(audio.get("\xa9nam")) or path.stem
    track.artist = _first(audio.get("\xa9ART")) or ""
    track.album = _first(audio.get("\xa9alb")) or ""


def _read_ogg(path: Path, track: Track) -> None:
    audio = OggVorbis(str(path))
    track.duration = audio.info.length
    track.title = _first(audio.get("title")) or path.stem
    track.artist = _first(audio.get("artist")) or ""
    track.album = _first(audio.get("album")) or ""


def write_artist(path: Path, artist: str) -> bool:
    """Write the artist tag back to the file. Returns True on success."""
    if not _MUTAGEN_AVAILABLE:
        return False
    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            try:
                tags = EasyID3(str(path))
            except Exception:
                from mutagen.id3 import ID3, TPE1
                tags = ID3(str(path))
                tags["TPE1"] = TPE1(encoding=3, text=artist)
                tags.save(str(path))
                return True
            tags["artist"] = [artist]
            tags.save(str(path))
        elif ext == ".flac":
            audio = FLAC(str(path))
            audio["artist"] = [artist]
            audio.save()
        elif ext in {".m4a", ".mp4"}:
            audio = MP4(str(path))
            audio["\xa9ART"] = [artist]
            audio.save()
        elif ext == ".ogg":
            audio = OggVorbis(str(path))
            audio["artist"] = [artist]
            audio.save()
        else:
            return False
        return True
    except Exception as exc:
        logger.warning("Could not write artist tag to %s: %s", path, exc)
        return False


def write_title(path: Path, title: str) -> bool:
    """Write the title tag back to the file. Returns True on success."""
    if not _MUTAGEN_AVAILABLE:
        return False
    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            try:
                tags = EasyID3(str(path))
            except Exception:
                from mutagen.id3 import ID3, TIT2
                tags = ID3(str(path))
                tags["TIT2"] = TIT2(encoding=3, text=title)
                tags.save(str(path))
                return True
            tags["title"] = [title]
            tags.save(str(path))
        elif ext == ".flac":
            audio = FLAC(str(path))
            audio["title"] = [title]
            audio.save()
        elif ext in {".m4a", ".mp4"}:
            audio = MP4(str(path))
            audio["\xa9nam"] = [title]
            audio.save()
        elif ext == ".ogg":
            audio = OggVorbis(str(path))
            audio["title"] = [title]
            audio.save()
        else:
            return False
        return True
    except Exception as exc:
        logger.warning("Could not write title tag to %s: %s", path, exc)
        return False


def write_album(path: Path, album: str) -> bool:
    """Write the album tag back to the file. Returns True on success."""
    if not _MUTAGEN_AVAILABLE:
        return False
    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            try:
                tags = EasyID3(str(path))
            except Exception:
                from mutagen.id3 import ID3, TALB
                tags = ID3(str(path))
                tags["TALB"] = TALB(encoding=3, text=album)
                tags.save(str(path))
                return True
            tags["album"] = [album]
            tags.save(str(path))
        elif ext == ".flac":
            audio = FLAC(str(path))
            audio["album"] = [album]
            audio.save()
        elif ext in {".m4a", ".mp4"}:
            audio = MP4(str(path))
            audio["\xa9alb"] = [album]
            audio.save()
        elif ext == ".ogg":
            audio = OggVorbis(str(path))
            audio["album"] = [album]
            audio.save()
        else:
            return False
        return True
    except Exception as exc:
        logger.warning("Could not write album tag to %s: %s", path, exc)
        return False


def _first(values: list | None) -> str:
    if values:
        return str(values[0])
    return ""
