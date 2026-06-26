from __future__ import annotations

"""
Secure credential storage backed by the system keychain (macOS Keychain,
Windows Credential Locker, Linux Secret Service / kwallet).

All secrets are stored under the service name "StreamShift" so they appear
grouped in the Keychain Access app. Keys follow the pattern:
    <namespace>/<field>
e.g.  "stream_stats/oauth_token", "bot/abc123/discord_bot_token"
"""

import logging

logger = logging.getLogger(__name__)

_SERVICE = "StreamShift"


def store(namespace: str, field: str, value: str) -> None:
    """Write *value* to the system keychain.  Empty string deletes the entry."""
    key = f"{namespace}/{field}"
    try:
        import keyring
        if value:
            keyring.set_password(_SERVICE, key, value)
        else:
            _delete_silent(namespace, field)
    except Exception as exc:
        logger.error("keyring store failed for %s: %s", key, exc)


def load(namespace: str, field: str) -> str:
    """Return the stored secret, or '' if not found."""
    key = f"{namespace}/{field}"
    try:
        import keyring
        return keyring.get_password(_SERVICE, key) or ""
    except Exception as exc:
        logger.warning("keyring load failed for %s: %s", key, exc)
        return ""


def delete(namespace: str, field: str) -> None:
    _delete_silent(namespace, field)


def _delete_silent(namespace: str, field: str) -> None:
    key = f"{namespace}/{field}"
    try:
        import keyring
        import keyring.errors
        keyring.delete_password(_SERVICE, key)
    except Exception:
        pass


def migrate_from_dict(data: dict, namespace: str, sensitive_keys: set[str]) -> dict:
    """
    One-time migration helper.  Moves any sensitive values that still exist in
    *data* into the keychain and returns a cleaned copy with those keys set to "".
    """
    cleaned = dict(data)
    for key in sensitive_keys:
        if cleaned.get(key):
            store(namespace, key, str(cleaned[key]))
            cleaned[key] = ""
    return cleaned
