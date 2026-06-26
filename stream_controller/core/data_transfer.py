"""
Export / import all StreamShift user data.

Export produces a .ssbackup file (a ZIP) containing:
  manifest.json   — format version + timestamp + inventory of what was captured
  configs/        — JSON and DB files from ~/.streamshift and ~/.stream_controller
  secrets.enc     — AES-256-GCM encrypted JSON of every keyring secret

SQLite (.db) files are exported via SQLite's own backup API into a temp file so
the snapshot is always consistent, even while the app is running.

The passphrase is stretched with PBKDF2-HMAC-SHA256 (600 000 iterations) into a
256-bit key.  Each export gets a fresh random salt + nonce so encrypting twice
with the same passphrase produces different bytes.

Import unpacks the ZIP, restores config files, decrypts secrets.enc, and writes
each secret back into the system keychain (macOS Keychain / Windows Credential
Locker / Linux Secret Service).  A restart is required to apply everything.
"""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_STREAMSHIFT_DIR = Path.home() / ".streamshift"
_STREAM_CONTROLLER_DIR = Path.home() / ".stream_controller"

_STATIC_SECRETS: dict[str, set[str]] = {
    "stream_info":    {"oauth_token", "obs_password"},
    "chat_manager":   {"oauth_token"},
    "scene_manager":  {"password"},
    "social_manager": {"bluesky_app_password"},
    "stream_stats":   {"oauth_token"},
}

_BOT_SENSITIVE = {"twitch_oauth_token", "discord_bot_token", "twitch_broadcaster_token"}

_BACKUP_VERSION = "2"  # bumped: added safe SQLite export + connection hints
_COMPAT_VERSIONS = {"1", "2"}  # versions this build can import
_MAX_FILE_BYTES = 50 * 1024 * 1024  # skip files larger than 50 MB

# Human-readable labels shown in the post-import checklist
_CONNECTION_HINTS: list[dict] = [
    {"label": "Twitch (main account)",   "detail": "Open Stream Info → Twitch Setup and re-authorise if the token does not work."},
    {"label": "Twitch Bot",              "detail": "Open Bot Manager → each bot → re-enter the OAuth token if chat commands stop working."},
    {"label": "OBS WebSocket",           "detail": "Open Scene Manager → Settings. The host/port/password were restored — just click Connect."},
    {"label": "Discord Bot",             "detail": "Open Bot Manager → General tab → verify the Discord Bot Token is still valid."},
    {"label": "Bluesky",                 "detail": "Open Social Manager → verify the App Password if posting fails."},
    {"label": "Stream Stats",            "detail": "Open Stream Stats → re-authorise Twitch if follower/sub counts stop updating."},
]


# ── Encryption ──────────────────────────────────────────────────────────────

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000, dklen=32)


def _encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """Return salt(16) || nonce(12) || ciphertext+tag from AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return salt + nonce + ct


def _decrypt(data: bytes, passphrase: str) -> bytes:
    """Inverse of _encrypt.  Raises ValueError on wrong passphrase or tampered data."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    if len(data) < 44:
        raise ValueError("Encrypted block is too short — the file may be corrupt.")
    salt, nonce, ct = data[:16], data[16:28], data[28:]
    key = _derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except InvalidTag:
        raise ValueError("Incorrect passphrase or the backup has been tampered with.")


# ── Keyring helpers ──────────────────────────────────────────────────────────

def _collect_secrets() -> dict[str, str]:
    """Return {namespace/field: value} for every non-empty keyring secret."""
    from stream_controller.core.keyring_helper import load as _kr_load
    secrets: dict[str, str] = {}

    for ns, fields in _STATIC_SECRETS.items():
        for field in fields:
            val = _kr_load(ns, field)
            if val:
                secrets[f"{ns}/{field}"] = val

    bots_json = _STREAMSHIFT_DIR / "bot_manager" / "bots.json"
    if bots_json.exists():
        try:
            for bot in json.loads(bots_json.read_text(encoding="utf-8")):
                bot_id = bot.get("bot_id", "")
                if not bot_id:
                    continue
                ns = f"bot/{bot_id}"
                for field in _BOT_SENSITIVE:
                    val = _kr_load(ns, field)
                    if val:
                        secrets[f"{ns}/{field}"] = val
        except Exception as exc:
            logger.warning("collect_secrets: could not read bots.json: %s", exc)

    return secrets


def _restore_secrets(secrets: dict[str, str]) -> None:
    """Write secrets back into the system keychain."""
    from stream_controller.core.keyring_helper import store as _kr_store
    for compound_key, value in secrets.items():
        # compound_key is either "namespace/field" or "bot/<uuid>/field"
        # Split on the LAST slash to separate namespace from field.
        slash = compound_key.rfind("/")
        if slash == -1:
            logger.warning("restore_secrets: unexpected key %r, skipping", compound_key)
            continue
        ns, field = compound_key[:slash], compound_key[slash + 1:]
        _kr_store(ns, field, value)


# ── SQLite safe copy ─────────────────────────────────────────────────────────

def _sqlite_backup_bytes(src_path: Path) -> bytes | None:
    """
    Use SQLite's built-in online backup API to produce a consistent snapshot of
    *src_path* even while another connection has the database open.  Returns the
    raw bytes of the snapshot, or None on error.
    """
    import sqlite3
    try:
        buf = io.BytesIO()
        src_conn = sqlite3.connect(str(src_path))
        dst_conn = sqlite3.connect(":memory:")
        src_conn.backup(dst_conn)
        src_conn.close()
        # Serialize the in-memory copy to raw bytes via a temp file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tmp_path = Path(tf.name)
        try:
            dst_conn.backup(sqlite3.connect(str(tmp_path)))
            dst_conn.close()
            return tmp_path.read_bytes()
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    except Exception as exc:
        logger.warning("sqlite_backup_bytes(%s): %s", src_path, exc)
        return None


# ── File collection ──────────────────────────────────────────────────────────

# Files/directories to skip even if they live under ~/.streamshift
_SKIP_SUFFIXES = {".log", ".tmp", ".lock", ".pyc"}
_SKIP_DIRS = {"__pycache__", ".DS_Store"}

def _collect_config_files() -> list[tuple[Path, str, bytes | None]]:
    """
    Return (absolute_path, archive_path, override_bytes) triples.
    - override_bytes is non-None only for SQLite files — it's the safe backup snapshot.
    - Files larger than 50 MB are skipped.
    """
    results: list[tuple[Path, str, bytes | None]] = []

    def _add_dir(base: Path, prefix: str) -> None:
        if not base.exists():
            return
        for fpath in sorted(base.rglob("*")):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if any(part in _SKIP_DIRS for part in fpath.parts):
                continue
            try:
                size = fpath.stat().st_size
                if size > _MAX_FILE_BYTES:
                    logger.info("Skipping large file from backup: %s", fpath)
                    continue
            except OSError:
                continue
            rel = fpath.relative_to(base)
            arc = f"{prefix}/{rel}"
            if fpath.suffix.lower() == ".db":
                snap = _sqlite_backup_bytes(fpath)
                results.append((fpath, arc, snap))
            else:
                results.append((fpath, arc, None))

    _add_dir(_STREAMSHIFT_DIR, "configs/streamshift")

    sc_settings = _STREAM_CONTROLLER_DIR / "settings.json"
    if sc_settings.exists():
        results.append((sc_settings, "configs/stream_controller/settings.json", None))

    return results


# ── Public API ───────────────────────────────────────────────────────────────

def export_backup(dest_path: Path, passphrase: str) -> tuple[int, int]:
    """
    Write a .ssbackup archive to *dest_path*.
    Returns (file_count, secret_count).
    SQLite databases are safely snapshotted via the backup API.
    Raises on any fatal error.
    """
    config_files = _collect_config_files()
    secrets = _collect_secrets()

    manifest = {
        "version": _BACKUP_VERSION,
        "file_count": len(config_files),
        "has_secrets": bool(secrets),
        "connection_hints": _CONNECTION_HINTS,
    }

    secrets_enc = _encrypt(
        json.dumps(secrets, ensure_ascii=False).encode("utf-8"),
        passphrase,
    )

    with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("secrets.enc", secrets_enc)
        for fpath, arc_path, snap_bytes in config_files:
            try:
                if snap_bytes is not None:
                    # SQLite backup snapshot — use the pre-captured bytes
                    zf.writestr(arc_path, snap_bytes)
                else:
                    zf.write(fpath, arc_path)
            except Exception as exc:
                logger.warning("export: skipping %s: %s", fpath, exc)

    logger.info("Exported %d files + %d secrets → %s", len(config_files), len(secrets), dest_path)
    return len(config_files), len(secrets)


def import_backup(src_path: Path, passphrase: str) -> tuple[int, int]:
    """
    Restore from a .ssbackup archive.
    Returns (file_count, secret_count).
    Raises ValueError on wrong passphrase; raises zipfile.BadZipFile on corrupt archive.
    """
    with zipfile.ZipFile(src_path, "r") as zf:
        names = zf.namelist()

        if "manifest.json" not in names:
            raise ValueError("This file does not look like a StreamShift backup.")

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        version = manifest.get("version")
        if version not in _COMPAT_VERSIONS:
            raise ValueError(
                f"Unsupported backup version '{version}'. "
                "Update StreamShift to the latest version and try again."
            )

        # Decrypt first — validates passphrase before touching any files.
        if "secrets.enc" in names:
            raw = _decrypt(zf.read("secrets.enc"), passphrase)
            secrets: dict[str, str] = json.loads(raw.decode("utf-8"))
        else:
            secrets = {}

        # Restore config files.
        restored_files = 0
        for arc_path in names:
            if not arc_path.startswith("configs/"):
                continue
            rel = arc_path[len("configs/"):]
            if rel.startswith("streamshift/"):
                dest = _STREAMSHIFT_DIR / rel[len("streamshift/"):]
            elif rel.startswith("stream_controller/"):
                dest = _STREAM_CONTROLLER_DIR / rel[len("stream_controller/"):]
            else:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(arc_path))
            restored_files += 1

        # Restore keyring secrets.
        _restore_secrets(secrets)

    logger.info("Import complete: %d files, %d secrets restored", restored_files, len(secrets))
    return restored_files, len(secrets)


def get_connection_hints() -> list[dict]:
    """Return the list of connection areas a user should verify after importing."""
    return list(_CONNECTION_HINTS)
