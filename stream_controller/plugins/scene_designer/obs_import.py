"""
Import OBS scenes into the Scene Designer.

Connects via WebSocket, fetches scene item lists and input settings,
then maps OBS's data model back to DesignerScene / SourceConfig objects.
All work runs on the calling thread — call from a background thread.
"""

from __future__ import annotations

import logging
from typing import Callable

from stream_controller.plugins.scene_designer.designer_models import (
    DesignerScene, SourceConfig,
)
from stream_controller.plugins.scene_designer.obs_sync import ObsSyncError, connect_obs

logger = logging.getLogger(__name__)

# ── OBS input kind → designer source_type ────────────────────────────────────

_KIND_TO_TYPE: dict[str, str] = {
    "image_source":             "image",
    "browser_source":           "browser",
    "text_ft2_source_v2":       "text",
    "text_gdiplus_v2":          "text",
    "text_gdiplus":             "text",
    "text_pango_source":        "text",
    "color_source_v3":          "color",
    "color_source_v2":          "color",
    "color_source":             "color",
    "ffmpeg_source":            "media",
    "vlc_source":               "media",
    "coreaudio_input_capture":  "audio_input",
    "wasapi_input_capture":     "audio_input",
    "pulse_input_capture":      "audio_input",
    "alsa_input_capture":       "audio_input",
    "coreaudio_output_capture": "audio_input",
    "wasapi_output_capture":    "audio_input",
    "pulse_output_capture":     "audio_input",
    "window_capture":           "window_capture",
    "xcomposite_input":         "window_capture",
    "monitor_capture":          "display_capture",
    "xshm_input":               "display_capture",
    "screen_capture":           "display_capture",
}

_TRANSITION_MAP: dict[str, str] = {
    "cut_transition":            "cut",
    "fade_transition":           "fade",
    "fade_to_color_transition":  "fade_to_color",
    "swipe_transition":          "swipe",
    "slide_transition":          "slide",
    "luma_wipe_transition":      "luma_wipe",
    "obs_stinger_transition":    "stinger",
}


def _abgr_to_hex(abgr: int) -> str:
    """Convert OBS ABGR int (e.g. 4294967295) to RGB hex string (e.g. 'ffffff')."""
    b = (abgr >> 0)  & 0xFF
    g = (abgr >> 8)  & 0xFF
    r = (abgr >> 16) & 0xFF
    return f"{r:02x}{g:02x}{b:02x}"


def _map_settings(kind: str, obs_settings: dict) -> dict:
    """Convert OBS input settings dict → SourceConfig.settings dict."""
    t = _KIND_TO_TYPE.get(kind, "")

    if t == "image":
        return {"file": obs_settings.get("file", "")}

    if t == "browser":
        return {
            "url":           obs_settings.get("url", ""),
            "width":         obs_settings.get("width",  1920),
            "height":        obs_settings.get("height", 1080),
            "css":           obs_settings.get("css", ""),
            "fps":           obs_settings.get("fps", 30),
            "reroute_audio": bool(obs_settings.get("reroute_audio", False)),
        }

    if t == "text":
        font_obj  = obs_settings.get("font") or {}
        color_raw = obs_settings.get("color1") or obs_settings.get("color", 0xFFFFFFFF)
        flags     = font_obj.get("flags", 0) if isinstance(font_obj, dict) else 0
        return {
            "content":   obs_settings.get("text", ""),
            "font_size": font_obj.get("size", 36) if isinstance(font_obj, dict) else 36,
            "color_hex": _abgr_to_hex(int(color_raw)),
            "bold":      bool(flags & 1),
            "italic":    bool(flags & 2),
            "outline":   bool(obs_settings.get("outline", False)),
            "shadow":    bool(obs_settings.get("drop_shadow", False)),
        }

    if t == "color":
        color_raw = obs_settings.get("color", 0xFF000000)
        return {"color_hex": _abgr_to_hex(int(color_raw))}

    if t == "media":
        return {
            "file":                obs_settings.get("local_file", ""),
            "loop":                bool(obs_settings.get("looping", False)),
            "restart_on_activate": bool(obs_settings.get("restart_on_activate", True)),
            "clear_on_end":        bool(obs_settings.get("clear_on_media_end", False)),
        }

    if t == "audio_input":
        return {"device_id": obs_settings.get("device_id", "")}

    if t in ("window_capture", "display_capture"):
        return {
            "window":         obs_settings.get("window", obs_settings.get("owner_name", "")),
            "capture_cursor": bool(obs_settings.get("show_cursor", True)),
        }

    return dict(obs_settings)


def _parse_transform(tf: dict, source_w: int, source_h: int) -> tuple[float, float, float, float, float]:
    """Return (x, y, width, height, rotation) from an OBS sceneItemTransform dict."""
    x   = float(tf.get("positionX", 0))
    y   = float(tf.get("positionY", 0))
    rot = float(tf.get("rotation",  0))

    bounds_type = tf.get("boundsType", "OBS_BOUNDS_NONE")
    if bounds_type and bounds_type != "OBS_BOUNDS_NONE":
        w = float(tf.get("boundsWidth",  source_w or 1920))
        h = float(tf.get("boundsHeight", source_h or 1080))
    else:
        sx = float(tf.get("scaleX", 1.0))
        sy = float(tf.get("scaleY", 1.0))
        w  = (source_w or 1920) * sx
        h  = (source_h or 1080) * sy

    return x, y, w, h, rot


def _item_attr(item, camel: str, snake: str, default=None):
    """Read from a dict or obsws_python response object, preferring dict."""
    if isinstance(item, dict):
        return item.get(camel, default)
    return getattr(item, snake, default)


# ── public API ────────────────────────────────────────────────────────────────

def fetch_obs_scenes(host: str, port: int, password: str) -> list[str]:
    """Return a list of OBS scene names. Raises ObsSyncError on failure."""
    req = connect_obs(host, port, password)
    result = req.get_scene_list()
    scenes_raw = getattr(result, "scenes", None) or []
    names = []
    for s in reversed(scenes_raw):      # OBS returns bottom→top; reverse for natural order
        if isinstance(s, dict):
            name     = s.get("sceneName", "")
            is_group = s.get("isGroup", False)
        else:
            name     = getattr(s, "scene_name", "")
            is_group = getattr(s, "is_group", False)
        if name and not is_group:
            names.append(name)
    return names


def import_scene(
    host: str,
    port: int,
    password: str,
    obs_scene_name: str,
    on_progress: Callable[[str], None] | None = None,
) -> DesignerScene:
    """
    Import a single OBS scene as a DesignerScene.
    Raises ObsSyncError on connection or API failure.
    """
    def prog(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    req = connect_obs(host, port, password)
    prog(f"Connected — importing '{obs_scene_name}'…")

    try:
        result = req.get_scene_item_list(obs_scene_name)
        items_raw = getattr(result, "scene_items", None) or []
    except Exception as exc:
        raise ObsSyncError(f"get_scene_item_list failed: {exc}") from exc

    # Try to read the current transition (non-fatal)
    transition_type = "fade"
    transition_ms   = 300
    try:
        tr = req.get_current_scene_transition()
        tr_kind = getattr(tr, "transition_kind", "") or ""
        transition_type = _TRANSITION_MAP.get(tr_kind, "fade")
        transition_ms   = int(getattr(tr, "transition_duration", 300) or 300)
    except Exception:
        pass

    sources: list[SourceConfig] = []
    # OBS returns items top→bottom visually; reverse so index 0 is rearmost
    items_ordered = list(reversed(items_raw)) if isinstance(items_raw, list) else []

    for item in items_ordered:
        source_type_obs = _item_attr(item, "sourceType",       "source_type",        "")
        input_kind      = _item_attr(item, "inputKind",        "input_kind",         "")
        source_name     = _item_attr(item, "sourceName",       "source_name",        "")
        visible         = bool(_item_attr(item, "sceneItemEnabled", "scene_item_enabled", True))
        locked          = bool(_item_attr(item, "sceneItemLocked",  "scene_item_locked",  False))
        tf_dict         = _item_attr(item, "sceneItemTransform",   "scene_item_transform", {}) or {}

        # Skip scene/group sources and anything we can't map
        if source_type_obs in ("OBS_SOURCE_TYPE_SCENE", "OBS_SOURCE_TYPE_TRANSITION"):
            continue
        if not input_kind:
            continue

        designer_type = _KIND_TO_TYPE.get(input_kind, "")
        if not designer_type:
            logger.debug("import: skipping unknown kind %r (%r)", input_kind, source_name)
            continue

        prog(f"  Importing: {source_name} ({designer_type})")

        # Fetch input settings
        obs_settings: dict = {}
        try:
            sr = req.get_input_settings(source_name)
            raw = getattr(sr, "input_settings", {})
            obs_settings = raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.debug("import: get_input_settings(%r) failed: %s", source_name, exc)

        # Intrinsic dimensions for scale-based sizing fallback
        tf = tf_dict if isinstance(tf_dict, dict) else {}
        source_w = int(tf.get("sourceWidth",  0))
        source_h = int(tf.get("sourceHeight", 0))

        # Volume / mute for audio sources (non-fatal)
        volume = 1.0
        muted  = False
        if designer_type == "audio_input":
            try:
                vr = req.get_input_volume(source_name)
                volume = float(getattr(vr, "input_volume_mul", 1.0) or 1.0)
            except Exception:
                pass
            try:
                mr = req.get_input_mute(source_name)
                muted = bool(getattr(mr, "input_muted", False))
            except Exception:
                pass

        x, y, w, h, rot = _parse_transform(tf, source_w, source_h)
        designer_settings = _map_settings(input_kind, obs_settings)

        sc = SourceConfig.new(designer_type, source_name)
        sc.x        = x
        sc.y        = y
        sc.width    = max(w, 1.0)
        sc.height   = max(h, 1.0)
        sc.rotation = rot
        sc.visible  = visible
        sc.locked   = locked
        sc.volume   = min(max(volume, 0.0), 1.0)
        sc.muted    = muted
        sc.settings = designer_settings
        sources.append(sc)

    scene = DesignerScene.new(obs_scene_name)
    scene.sources              = sources
    scene.transition_type      = transition_type
    scene.transition_duration_ms = transition_ms

    prog(f"✓ Imported {len(sources)} source(s) from '{obs_scene_name}'")
    return scene
