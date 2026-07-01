from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from stream_controller.constants import CHAT_OVERLAY_PORT, MUSIC_OVERLAY_PORT, ALERT_OVERLAY_PORT, TIMER_OVERLAY_PORT, PNGTUBER_PORT

# ── source types ──────────────────────────────────────────────────────────────

SOURCE_TYPES: dict[str, dict] = {
    "image": {
        "label": "Image",
        "icon": "🖼",
        "obs_kind_mac": "image_source",
        "obs_kind_win": "image_source",
        "obs_kind_linux": "image_source",
        "default_settings": {"file": "", "unload": False},
    },
    "browser": {
        "label": "Browser Source",
        "icon": "🌐",
        "obs_kind_mac": "browser_source",
        "obs_kind_win": "browser_source",
        "obs_kind_linux": "browser_source",
        "default_settings": {"url": "", "width": 1920, "height": 1080, "css": "", "fps": 30, "reroute_audio": False},
    },
    "text": {
        "label": "Text",
        "icon": "T",
        "obs_kind_mac": "text_ft2_source_v2",
        "obs_kind_win": "text_gdiplus_v2",
        "obs_kind_linux": "text_ft2_source_v2",
        "default_settings": {"text": "Text", "font": {"face": "Arial", "size": 48, "style": "Regular"}, "color": 0xFFFFFFFF, "outline": False, "drop_shadow": False, "align": "left"},
    },
    "color": {
        "label": "Color Block",
        "icon": "■",
        "obs_kind_mac": "color_source_v3",
        "obs_kind_win": "color_source_v3",
        "obs_kind_linux": "color_source_v3",
        "default_settings": {"color": 0xFF1a1a2e, "width": 1920, "height": 1080},
    },
    "media": {
        "label": "Media / Video",
        "icon": "▶",
        "obs_kind_mac": "ffmpeg_source",
        "obs_kind_win": "ffmpeg_source",
        "obs_kind_linux": "ffmpeg_source",
        "default_settings": {"local_file": "", "looping": False, "restart_on_activate": True, "clear_on_media_end": True},
    },
    "audio_input": {
        "label": "Audio Input",
        "icon": "🎙",
        "obs_kind_mac": "coreaudio_input_capture",
        "obs_kind_win": "wasapi_input_capture",
        "obs_kind_linux": "pulse_input_capture",
        "default_settings": {"device_id": "default"},
    },
    "window_capture": {
        "label": "Window Capture",
        "icon": "🪟",
        "obs_kind_mac": "screen_capture",
        "obs_kind_win": "window_capture",
        "obs_kind_linux": "xcomposite_input",
        "default_settings": {"window": "", "capture_cursor": True, "compatibility": False},
    },
    "display_capture": {
        "label": "Display Capture",
        "icon": "🖥",
        "obs_kind_mac": "screen_capture",
        "obs_kind_win": "monitor_capture",
        "obs_kind_linux": "xshm_input",
        "default_settings": {"display": 0, "capture_cursor": True},
    },
    "chat_overlay": {
        "label": "Chat Overlay",
        "icon": "💬",
        "obs_kind_mac": "browser_source",
        "obs_kind_win": "browser_source",
        "obs_kind_linux": "browser_source",
        "default_settings": {"url": f"http://localhost:{CHAT_OVERLAY_PORT}/chat", "width": 400, "height": 800, "css": "", "fps": 30, "reroute_audio": False},
    },
}

TRANSITION_TYPES = {
    "cut":        {"label": "Cut",        "obs_kind": "cut_transition"},
    "fade":       {"label": "Fade",       "obs_kind": "fade_transition"},
    "fade_to_color": {"label": "Fade to Color", "obs_kind": "fade_to_color_transition"},
    "swipe":      {"label": "Swipe",      "obs_kind": "swipe_transition"},
    "slide":      {"label": "Slide",      "obs_kind": "slide_transition"},
    "luma_wipe":  {"label": "Luma Wipe",  "obs_kind": "luma_wipe_transition"},
    "stinger":    {"label": "Stinger",    "obs_kind": "obs_stinger_transition"},
}

CANVAS_W = 1920
CANVAS_H = 1080


# ── data models ───────────────────────────────────────────────────────────────

@dataclass
class SourceConfig:
    source_id: str
    name: str
    source_type: str          # key in SOURCE_TYPES
    x: float = 0.0
    y: float = 0.0
    width: float = 1920.0
    height: float = 1080.0
    rotation: float = 0.0
    visible: bool = True
    locked: bool = False
    muted: bool = False
    volume: float = 1.0       # 0.0–1.0 (linear)
    opacity: float = 1.0      # 0.0–1.0 (applied in canvas preview and OBS sync)
    settings: dict = field(default_factory=dict)
    # z-order determined by list position (index 0 = bottom)

    @classmethod
    def new(cls, source_type: str, name: str = "") -> "SourceConfig":
        info = SOURCE_TYPES.get(source_type, {})
        if not name:
            name = info.get("label", source_type)
        defaults = dict(info.get("default_settings", {}))
        w, h = _default_size(source_type)
        return cls(
            source_id=str(uuid.uuid4()),
            name=name,
            source_type=source_type,
            width=w, height=h,
            settings=defaults,
        )

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "rotation": self.rotation,
            "visible": self.visible,
            "locked": self.locked,
            "muted": self.muted,
            "volume": self.volume,
            "opacity": self.opacity,
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceConfig":
        return cls(
            source_id=d.get("source_id", str(uuid.uuid4())),
            name=d.get("name", "Source"),
            source_type=d.get("source_type", "color"),
            x=float(d.get("x", 0)), y=float(d.get("y", 0)),
            width=float(d.get("width", 1920)), height=float(d.get("height", 1080)),
            rotation=float(d.get("rotation", 0)),
            visible=bool(d.get("visible", True)),
            locked=bool(d.get("locked", False)),
            muted=bool(d.get("muted", False)),
            volume=float(d.get("volume", 1.0)),
            opacity=float(d.get("opacity", 1.0)),
            settings=dict(d.get("settings", {})),
        )


@dataclass
class DesignerScene:
    scene_id: str
    name: str
    sources: list[SourceConfig] = field(default_factory=list)
    transition_type: str = "fade"
    transition_duration_ms: int = 300
    bg_color: str = "#0d0d1a"   # canvas background colour (hex)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def new(cls, name: str) -> "DesignerScene":
        return cls(scene_id=str(uuid.uuid4()), name=name)

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "sources": [s.to_dict() for s in self.sources],
            "transition_type": self.transition_type,
            "transition_duration_ms": self.transition_duration_ms,
            "bg_color": self.bg_color,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DesignerScene":
        return cls(
            scene_id=d.get("scene_id", str(uuid.uuid4())),
            name=d.get("name", "Scene"),
            sources=[SourceConfig.from_dict(s) for s in d.get("sources", [])],
            transition_type=d.get("transition_type", "fade"),
            transition_duration_ms=int(d.get("transition_duration_ms", 300)),
            bg_color=d.get("bg_color", "#0d0d1a"),
            created_at=float(d.get("created_at", time.time())),
        )


def _default_size(source_type: str) -> tuple[float, float]:
    return {
        "image":         (400, 300),
        "browser":       (1920, 1080),
        "text":          (600, 100),
        "color":         (1920, 1080),
        "media":         (1920, 1080),
        "audio_input":   (1920, 1080),
        "window_capture":(1920, 1080),
        "display_capture":(1920, 1080),
        "chat_overlay":  (400, 800),
    }.get(source_type, (400, 300))
