from __future__ import annotations

import colorsys
import uuid
from dataclasses import dataclass, field
from typing import Any


# ── color math helpers ────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_hsl(h: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(h)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)  # returns (h, l, s)


def _hsl_to_hex(hue: float, lightness: float, saturation: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _rgb_to_hex(round(r * 255), round(g * 255), round(b * 255))


def lighten(hex_color: str, amount: float) -> str:
    h, l, s = _hex_to_hsl(hex_color)
    return _hsl_to_hex(h, min(1.0, l + amount), s)


def darken(hex_color: str, amount: float) -> str:
    h, l, s = _hex_to_hsl(hex_color)
    return _hsl_to_hex(h, max(0.0, l - amount), s)


def alpha(hex_color: str, a: float) -> str:
    """Return rgba(...) string for QSS."""
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{a:.2f})"


def tint(hex_color: str, accent: str, strength: float = 0.15) -> str:
    """Mix hex_color with accent hue at the given strength."""
    h_base, l_base, s_base = _hex_to_hsl(hex_color)
    h_acc, l_acc, s_acc = _hex_to_hsl(accent)
    new_h = h_base + (h_acc - h_base) * strength
    new_s = s_base + (s_acc - s_base) * strength
    return _hsl_to_hex(new_h, l_base, min(1.0, new_s))


def mix(a_hex: str, b_hex: str, t: float = 0.5) -> str:
    """Linear interpolation between two hex colors (t=0 → a, t=1 → b)."""
    ar, ag, ab = _hex_to_rgb(a_hex)
    br, bg, bb = _hex_to_rgb(b_hex)
    return _rgb_to_hex(
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


# ── panel theme ───────────────────────────────────────────────────────────────

@dataclass
class PanelTheme:
    panel_id: str
    accent: str = "#7c3aed"
    bg: str = ""             # empty = use app default
    title_gradient_start: str = ""
    title_gradient_end: str = ""
    border: str = ""
    icon_text: str = ""      # emoji / short text icon shown in title bar
    icon_path: str = ""      # absolute path to uploaded image icon

    def to_dict(self) -> dict:
        return {
            "panel_id": self.panel_id,
            "accent": self.accent,
            "bg": self.bg,
            "title_gradient_start": self.title_gradient_start,
            "title_gradient_end": self.title_gradient_end,
            "border": self.border,
            "icon_text": self.icon_text,
            "icon_path": self.icon_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PanelTheme":
        return cls(**{k: d.get(k, "") for k in [
            "panel_id", "accent", "bg",
            "title_gradient_start", "title_gradient_end",
            "border", "icon_text", "icon_path",
        ]})


# ── app theme ─────────────────────────────────────────────────────────────────

@dataclass
class AppTheme:
    theme_id: str
    name: str
    builtin: bool = False

    # Background levels (darkest → elevated)
    bg_base: str = "#090e14"
    bg_primary: str = "#0b1117"
    bg_sidebar: str = "#0d141c"
    bg_card: str = "#121a23"
    bg_elevated: str = "#141e2c"
    bg_input: str = "#0f1520"

    # Accent / brand
    accent: str = "#7c3aed"

    # Text
    text_primary: str = "#edf2f7"
    text_secondary: str = "#8090b0"
    text_muted: str = "#3b4d7a"

    # Borders
    border: str = "#1f2c38"

    # Status
    success: str = "#22c55e"
    error: str = "#ef4444"
    warning: str = "#f59e0b"
    info: str = "#4aa8d8"

    # Per-panel overrides: panel_id → PanelTheme
    panel_overrides: dict[str, PanelTheme] = field(default_factory=dict)

    # ── derived colors (computed, not stored) ────────────────────────────────

    @property
    def accent_dark(self) -> str:     return darken(self.accent, 0.12)
    @property
    def accent_darker(self) -> str:   return darken(self.accent, 0.25)
    @property
    def accent_light(self) -> str:    return lighten(self.accent, 0.18)
    @property
    def accent_faint(self) -> str:    return tint(self.bg_card, self.accent, 0.25)
    @property
    def accent_bg(self) -> str:       return tint(self.bg_base, self.accent, 0.4)
    @property
    def border_accent(self) -> str:   return tint(self.border, self.accent, 0.5)
    @property
    def border_strong(self) -> str:   return lighten(self.border, 0.05)

    # Gradient helpers (for QSS linearGradient)
    @property
    def bg_card_hi(self) -> str:      return lighten(self.bg_card, 0.02)
    @property
    def bg_card_lo(self) -> str:      return darken(self.bg_card, 0.01)
    @property
    def sidebar_hi(self) -> str:      return lighten(self.bg_sidebar, 0.02)
    @property
    def sidebar_lo(self) -> str:      return darken(self.bg_sidebar, 0.01)
    @property
    def accent_hover(self) -> str:    return lighten(self.accent, 0.06)
    @property
    def accent_pressed(self) -> str:  return darken(self.accent, 0.06)
    @property
    def bg_hover(self) -> str:        return lighten(self.bg_card, 0.04)
    @property
    def bg_selected(self) -> str:     return tint(self.bg_elevated, self.accent, 0.3)
    @property
    def success_bg(self) -> str:      return tint(self.bg_card, self.success, 0.2)
    @property
    def error_bg(self) -> str:        return tint(self.bg_card, self.error, 0.2)
    @property
    def info_bg(self) -> str:         return tint(self.bg_card, self.info, 0.2)

    def to_dict(self) -> dict:
        return {
            "theme_id": self.theme_id,
            "name": self.name,
            "builtin": self.builtin,
            "bg_base": self.bg_base,
            "bg_primary": self.bg_primary,
            "bg_sidebar": self.bg_sidebar,
            "bg_card": self.bg_card,
            "bg_elevated": self.bg_elevated,
            "bg_input": self.bg_input,
            "accent": self.accent,
            "text_primary": self.text_primary,
            "text_secondary": self.text_secondary,
            "text_muted": self.text_muted,
            "border": self.border,
            "success": self.success,
            "error": self.error,
            "warning": self.warning,
            "info": self.info,
            "panel_overrides": {k: v.to_dict() for k, v in self.panel_overrides.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppTheme":
        panel_overrides = {
            k: PanelTheme.from_dict(v)
            for k, v in d.get("panel_overrides", {}).items()
        }
        return cls(
            theme_id=d.get("theme_id", str(uuid.uuid4())),
            name=d.get("name", "Custom"),
            builtin=d.get("builtin", False),
            bg_base=d.get("bg_base", "#090e14"),
            bg_primary=d.get("bg_primary", "#0b1117"),
            bg_sidebar=d.get("bg_sidebar", "#0d141c"),
            bg_card=d.get("bg_card", "#121a23"),
            bg_elevated=d.get("bg_elevated", "#141e2c"),
            bg_input=d.get("bg_input", "#0f1520"),
            accent=d.get("accent", "#7c3aed"),
            text_primary=d.get("text_primary", "#edf2f7"),
            text_secondary=d.get("text_secondary", "#8090b0"),
            text_muted=d.get("text_muted", "#3b4d7a"),
            border=d.get("border", "#1f2c38"),
            success=d.get("success", "#22c55e"),
            error=d.get("error", "#ef4444"),
            warning=d.get("warning", "#f59e0b"),
            info=d.get("info", "#4aa8d8"),
            panel_overrides=panel_overrides,
        )

    @classmethod
    def new_custom(cls, name: str = "My Theme") -> "AppTheme":
        return cls(theme_id=str(uuid.uuid4()), name=name, builtin=False)


# ── built-in themes ───────────────────────────────────────────────────────────

def _builtin(theme_id: str, name: str, **kwargs) -> AppTheme:
    return AppTheme(theme_id=theme_id, name=name, builtin=True, **kwargs)


BUILTIN_THEMES: list[AppTheme] = [
    _builtin("midnight", "Midnight",
        bg_base="#090e14", bg_primary="#0b1117", bg_sidebar="#0d141c",
        bg_card="#121a23", bg_elevated="#141e2c", bg_input="#0f1520",
        accent="#7c3aed", text_primary="#edf2f7", text_secondary="#8090b0",
        border="#1f2c38", success="#22c55e", error="#ef4444", info="#4aa8d8",
    ),
    _builtin("deep-ocean", "Deep Ocean",
        bg_base="#020c12", bg_primary="#041520", bg_sidebar="#061b28",
        bg_card="#081f30", bg_elevated="#0a2638", bg_input="#061624",
        accent="#0ea5e9", text_primary="#e2f4ff", text_secondary="#6a9ab0",
        border="#0d3050", success="#22c55e", error="#ef4444", info="#38bdf8",
    ),
    _builtin("carbon", "Carbon",
        bg_base="#0a0a0a", bg_primary="#111111", bg_sidebar="#161616",
        bg_card="#1c1c1c", bg_elevated="#222222", bg_input="#141414",
        accent="#f97316", text_primary="#f5f5f5", text_secondary="#737373",
        border="#2a2a2a", success="#22c55e", error="#ef4444", info="#60a5fa",
    ),
    _builtin("crimson", "Crimson",
        bg_base="#0e0608", bg_primary="#13080a", bg_sidebar="#180b0e",
        bg_card="#1f0e12", bg_elevated="#261118", bg_input="#160a0d",
        accent="#e11d48", text_primary="#fff1f3", text_secondary="#9b7580",
        border="#3b1320", success="#22c55e", error="#fb7185", info="#60a5fa",
    ),
    _builtin("forest", "Forest",
        bg_base="#060e07", bg_primary="#0a140b", bg_sidebar="#0d1a0e",
        bg_card="#111f12", bg_elevated="#162618", bg_input="#0c1a0d",
        accent="#16a34a", text_primary="#f0fff4", text_secondary="#6b8f72",
        border="#1a3320", success="#4ade80", error="#ef4444", info="#38bdf8",
    ),
    _builtin("cyberpunk", "Cyberpunk",
        bg_base="#030308", bg_primary="#06060f", bg_sidebar="#08081a",
        bg_card="#0c0c20", bg_elevated="#100f28", bg_input="#080812",
        accent="#06b6d4", text_primary="#f0ffff", text_secondary="#5a8090",
        border="#0d1f30", success="#a3e635", error="#f43f5e", info="#818cf8",
        warning="#fbbf24",
    ),
    _builtin("rose-gold", "Rose Gold",
        bg_base="#0e090c", bg_primary="#150d10", bg_sidebar="#1c1016",
        bg_card="#22141c", bg_elevated="#2a1924", bg_input="#180e14",
        accent="#f43f5e", text_primary="#fff0f3", text_secondary="#a0708a",
        border="#3d1a28", success="#34d399", error="#fb7185", info="#818cf8",
        warning="#fbbf24",
    ),
    _builtin("slate", "Slate",
        bg_base="#06080e", bg_primary="#0c1018", bg_sidebar="#101520",
        bg_card="#151c28", bg_elevated="#1c2535", bg_input="#111820",
        accent="#818cf8", text_primary="#f1f5ff", text_secondary="#7080a0",
        border="#1e2840", success="#34d399", error="#f87171", info="#60a5fa",
    ),
    _builtin("aurora", "Aurora",
        bg_base="#040810", bg_primary="#080e1c", bg_sidebar="#0c1428",
        bg_card="#101c34", bg_elevated="#142440", bg_input="#0a1020",
        accent="#10b981", text_primary="#ecfff8", text_secondary="#4a8a70",
        border="#102840", success="#34d399", error="#f87171", info="#38bdf8",
        warning="#fbbf24",
    ),
]

BUILTIN_THEME_MAP: dict[str, AppTheme] = {t.theme_id: t for t in BUILTIN_THEMES}
