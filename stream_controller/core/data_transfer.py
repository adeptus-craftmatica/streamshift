"""
Export / import all StreamShift user data.

Export produces a .ssbackup file (a ZIP) containing:
  manifest.json   — format version + timestamp
  configs/        — JSON and DB files from ~/.streamshift and ~/.stream_controller
  secrets.enc     — AES-256-GCM encrypted JSON of every keyring secret

The passphrase is stretched with PBKDF2-HMAC-SHA256 (600 000 iterations) into a
256-bit key.  Each export gets a fresh random salt + nonce so encrypting twice
with the same passphrase produces different bytes.

Import unpacks the ZIP, restores config files, decrypts secrets.enc, and writes
each secret back into the system keychain (macOS Keychain / Windows Credential
Locker / Linux Secret Service).
"""
from __future__ import annotations

import json
import logging
import os
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

_BACKUP_VERSION = "1"
_MAX_FILE_BYTES = 50 * 1024 * 1024  # skip files larger than 50 MB


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


# ── File collection ──────────────────────────────────────────────────────────

def _collect_config_files() -> list[tuple[Path, str]]:
    """
    Return (absolute_path, archive_path) pairs for every config file to include.
    Files larger than 50 MB are skipped.
    """
    results: list[tuple[Path, str]] = []

    if _STREAMSHIFT_DIR.exists():
        for fpath in sorted(_STREAMSHIFT_DIR.rglob("*")):
            if not fpath.is_file():
                continue
            try:
                if fpath.stat().st_size > _MAX_FILE_BYTES:
                    logger.info("Skipping large file from backup: %s", fpath)
                    continue
            except OSError:
                continue
            rel = fpath.relative_to(_STREAMSHIFT_DIR)
            results.append((fpath, f"configs/streamshift/{rel}"))

    sc_settings = _STREAM_CONTROLLER_DIR / "settings.json"
    if sc_settings.exists():
        results.append((sc_settings, "configs/stream_controller/settings.json"))

    return results


# ── Public API ───────────────────────────────────────────────────────────────

def export_backup(dest_path: Path, passphrase: str) -> tuple[int, int]:
    """
    Write a .ssbackup archive to *dest_path*.
    Returns (file_count, secret_count).
    Raises on any fatal error.
    """
    config_files = _collect_config_files()
    secrets = _collect_secrets()

    manifest = {
        "version": _BACKUP_VERSION,
        "file_count": len(config_files),
        "has_secrets": bool(secrets),
    }

    secrets_enc = _encrypt(
        json.dumps(secrets, ensure_ascii=False).encode("utf-8"),
        passphrase,
    )

    with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("secrets.enc", secrets_enc)
        for fpath, arc_path in config_files:
            try:
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
        if manifest.get("version") != _BACKUP_VERSION:
            raise ValueError(
                f"Unsupported backup version '{manifest.get('version')}'. "
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
