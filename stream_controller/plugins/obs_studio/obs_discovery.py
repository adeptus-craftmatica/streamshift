"""Auto-discover the local OBS WebSocket configuration.

Reads OBS's own config file so users never need to manually enter
host/port/password — StreamShift picks them up automatically.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_OBS_WS_CONFIG_PATHS = {
    "darwin": Path.home() / "Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json",
    "win32":  Path.home() / "AppData/Roaming/obs-studio/plugin_config/obs-websocket/config.json",
    "linux":  Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json",
}


def discover_obs_websocket() -> tuple[str, int, str] | None:
    """Return (host, port, password) from OBS's own config, or None if unavailable."""
    cfg_path = _OBS_WS_CONFIG_PATHS.get(sys.platform)
    if cfg_path is None or not cfg_path.exists():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not data.get("server_enabled", False):
            logger.debug("OBS WebSocket server is disabled in OBS config")
            return None
        port = int(data.get("server_port", 4455))
        password = str(data.get("server_password", "") or "")
        if not data.get("auth_required", True):
            password = ""
        logger.debug("OBS WebSocket auto-discovered: localhost:%d auth=%s", port, bool(password))
        return "localhost", port, password
    except Exception as exc:
        logger.debug("Could not read OBS WebSocket config: %s", exc)
        return None
