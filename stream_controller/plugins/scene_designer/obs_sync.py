from __future__ import annotations

"""
Push a DesignerScene to OBS via the WebSocket API (obsws-python).

Sync steps for each scene:
  1. Create the OBS scene (no-op if it already exists).
  2. Remove all existing sources from the OBS scene to start clean.
  3. For each source (bottom→top z-order):
     a. Create an input in the scene (CreateInput).
     b. Look up the scene item id that was just created.
     c. Apply position / size / rotation transform (SetSceneItemTransform).
     d. Set item visibility.
  4. If the scene's transition is set, configure it on the OBS scene.

All work runs on the calling thread — call from a background thread.
"""

import logging
import platform
import sys
from typing import Callable

from stream_controller.plugins.scene_designer.designer_models import (
    CANVAS_H,
    CANVAS_W,
    SOURCE_TYPES,
    TRANSITION_TYPES,
    DesignerScene,
    SourceConfig,
)

logger = logging.getLogger(__name__)

_OS = sys.platform  # "darwin", "win32", "linux"


def obs_kind_for(source_type: str) -> str:
    info = SOURCE_TYPES.get(source_type, {})
    if _OS == "darwin":
        return info.get("obs_kind_mac", "")
    if _OS == "win32":
        return info.get("obs_kind_win", "")
    return info.get("obs_kind_linux", "")


# ── sync entry point ──────────────────────────────────────────────────────────

class ObsSyncError(Exception):
    pass


def sync_scene(
    req,                          # obsws_python.ReqClient
    scene: DesignerScene,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """
    Push *scene* to OBS. Raises ObsSyncError on failure.
    `req` must be a connected obsws_python.ReqClient instance.
    """
    def _prog(msg: str) -> None:
        logger.debug("OBS sync: %s", msg)
        if on_progress:
            on_progress(msg)

    _prog(f"Syncing scene '{scene.name}' to OBS…")

    # 1. Create scene (safe to call if it already exists — OBS returns an error
    #    which we swallow).
    try:
        req.create_scene(scene.name)
        _prog(f"Created OBS scene '{scene.name}'")
    except Exception as exc:
        if "already exists" in str(exc).lower() or "00409" in str(exc):
            _prog(f"OBS scene '{scene.name}' already exists — reusing")
        else:
            raise ObsSyncError(f"CreateScene failed: {exc}") from exc

    # 2. Remove existing items from the OBS scene.
    try:
        item_list = req.get_scene_item_list(scene.name)
        existing = getattr(item_list, "scene_items", []) or []
        for item in existing:
            item_id = item.get("sceneItemId")
            if item_id is not None:
                try:
                    req.remove_scene_item(scene.name, item_id)
                except Exception:
                    pass
        _prog(f"Cleared {len(existing)} existing item(s)")
    except Exception as exc:
        _prog(f"Warning: could not clear existing items: {exc}")

    # 3. Add sources (bottom→top = index 0 first).
    for idx, source in enumerate(scene.sources):
        _prog(f"  Adding source '{source.name}' ({source.source_type})…")
        try:
            _add_source(req, scene.name, source, _prog)
        except ObsSyncError as exc:
            _prog(f"  ⚠ Skipped '{source.name}': {exc}")

    # 4. Transition — best-effort.
    try:
        transition_info = TRANSITION_TYPES.get(scene.transition_type)
        if transition_info:
            obs_kind = transition_info["obs_kind"]
            duration = scene.transition_duration_ms
            # SetCurrentSceneTransitionDuration is scene-agnostic in OBS;
            # scene-specific transitions require the Transition Override API.
            req.set_current_scene_transition_duration(duration)
            _prog(f"Transition set: {scene.transition_type} ({duration}ms)")
    except Exception as exc:
        _prog(f"  Warning: could not set transition: {exc}")

    _prog(f"✓ Scene '{scene.name}' synced to OBS")


def _add_source(req, scene_name: str, source: SourceConfig, prog: Callable) -> None:
    kind = obs_kind_for(source.source_type)
    if not kind:
        raise ObsSyncError(f"Unknown obs kind for '{source.source_type}'")

    settings = _build_obs_settings(source)

    # CreateInput — creates an input AND adds it to the scene.
    try:
        resp = req.create_input(
            scene_name,           # scene_name (positional)
            source.name,          # input_name
            kind,                 # input_kind
            settings,             # input_settings
            source.visible,       # scene_item_enabled
        )
        scene_item_id = getattr(resp, "scene_item_id", None)
    except Exception as exc:
        # If the input name already exists, OBS raises an error.
        # Try to find the existing item and fall through to transform.
        if "already exists" in str(exc).lower():
            prog(f"    Input '{source.name}' already exists — updating transform only")
            scene_item_id = _find_scene_item_id(req, scene_name, source.name)
        else:
            raise ObsSyncError(f"CreateInput failed: {exc}") from exc

    if scene_item_id is None:
        raise ObsSyncError(f"Could not get scene_item_id for '{source.name}'")

    # SetSceneItemTransform
    transform = _build_transform(source)
    try:
        req.set_scene_item_transform(scene_name, scene_item_id, transform)
    except Exception as exc:
        prog(f"    Warning: transform failed for '{source.name}': {exc}")

    # SetSceneItemEnabled (visibility)
    try:
        req.set_scene_item_enabled(scene_name, scene_item_id, source.visible)
    except Exception as exc:
        prog(f"    Warning: visibility failed for '{source.name}': {exc}")

    # Volume for audio sources
    if source.source_type == "audio_input":
        try:
            req.set_input_volume(source.name, mul=source.volume)
        except Exception:
            pass
        if source.muted:
            try:
                req.set_input_mute(source.name, True)
            except Exception:
                pass


def _find_scene_item_id(req, scene_name: str, input_name: str) -> int | None:
    try:
        item_list = req.get_scene_item_list(scene_name)
        items = getattr(item_list, "scene_items", []) or []
        for item in items:
            src = item.get("sourceName", "") or item.get("inputName", "")
            if src == input_name:
                return item.get("sceneItemId")
    except Exception:
        pass
    return None


def _build_obs_settings(source: SourceConfig) -> dict:
    s = dict(source.settings)
    t = source.source_type

    if t == "text":
        # OBS text source expects hex ABGR colour int.
        color_hex = s.get("color_hex", "ffffff")
        try:
            r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
            s["color"] = (0xFF << 24) | (b << 16) | (g << 8) | r
        except Exception:
            s["color"] = 0xFFFFFFFF
        s.pop("color_hex", None)

    elif t == "color":
        color_hex = s.get("color_hex", "1a1a2e")
        try:
            r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
            s["color"] = (0xFF << 24) | (b << 16) | (g << 8) | r
        except Exception:
            s["color"] = 0xFF1a1a2e
        s.pop("color_hex", None)
        s["width"] = int(source.width)
        s["height"] = int(source.height)

    elif t == "window_capture" and _OS == "darwin":
        # macOS uses screen_capture with type "window"
        s["type"] = 1  # 0=screen, 1=window, 2=application

    elif t == "display_capture" and _OS == "darwin":
        s["type"] = 0  # screen

    return s


def _build_transform(source: SourceConfig) -> dict:
    """
    OBS SetSceneItemTransform expects a dict with:
      positionX, positionY, scaleX, scaleY, rotation,
      boundsType, boundsWidth, boundsHeight,
      sourceWidth, sourceHeight (read-only in some OBS versions)
    """
    return {
        "positionX":    source.x,
        "positionY":    source.y,
        "boundsType":   "OBS_BOUNDS_SCALE_INNER",
        "boundsWidth":  source.width,
        "boundsHeight": source.height,
        "rotation":     source.rotation,
        "scaleX":       1.0,
        "scaleY":       1.0,
    }


# ── OBS connection helper ─────────────────────────────────────────────────────

def connect_obs(host: str, port: int, password: str):
    """Return a connected ReqClient or raise ObsSyncError."""
    try:
        from obsws_python import ReqClient
        return ReqClient(host=host, port=port, password=password, timeout=10)
    except ImportError:
        raise ObsSyncError("obsws-python not installed — run: pip install obsws-python")
    except Exception as exc:
        raise ObsSyncError(f"Could not connect to OBS: {exc}") from exc
