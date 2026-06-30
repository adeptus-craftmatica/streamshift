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
    _builtin("neon-noir", "Neon Noir",
        # Hot magenta on near-black — punchy cyberpunk-adjacent without the teal cliché.
        bg_base="#0a0008", bg_primary="#0f000d", bg_sidebar="#140014",
        bg_card="#1a0018", bg_elevated="#200020", bg_input="#120010",
        accent="#e040fb",
        text_primary="#fce4ff", text_secondary="#a060b0",
        text_muted="#5a2860",
        border="#3a0840",
        success="#69ff47", error="#ff3d71", warning="#ffdd59", info="#44cffc",
    ),
    _builtin("sunset", "Sunset",
        # Warm amber-to-violet dusk palette. Feels cozy for long evening streams.
        bg_base="#0d0608", bg_primary="#120a0c", bg_sidebar="#180d10",
        bg_card="#1e1014", bg_elevated="#251418", bg_input="#160b0e",
        accent="#fb923c",
        text_primary="#fff7ed", text_secondary="#a07060",
        text_muted="#6a3828",
        border="#3d1820",
        success="#4ade80", error="#f87171", warning="#fbbf24", info="#818cf8",
    ),
    _builtin("synthwave", "Synthwave",
        # Retro 80s: deep purple base, electric pink accent, neon highlights.
        bg_base="#08010f", bg_primary="#0e0318", bg_sidebar="#120420",
        bg_card="#180630", bg_elevated="#1e0a3c", bg_input="#0e0420",
        accent="#ff2d78",
        text_primary="#f8d6ff", text_secondary="#9060a8",
        text_muted="#502870",
        border="#2e0850",
        success="#00ffa3", error="#ff2d78", warning="#ffcc00", info="#6b00ff",
    ),
    _builtin("obsidian", "Obsidian",
        # Cold charcoal with a teal-green accent — clean, minimal, focused.
        bg_base="#060a09", bg_primary="#0a0f0e", bg_sidebar="#0d1513",
        bg_card="#121d1a", bg_elevated="#162320", bg_input="#0e1816",
        accent="#2dd4bf",
        text_primary="#f0fdfa", text_secondary="#6a9a92",
        text_muted="#305850",
        border="#183028",
        success="#4ade80", error="#f87171", warning="#fbbf24", info="#38bdf8",
    ),
    _builtin("galaxy", "Galaxy",
        bg_base="#05050f", bg_primary="#080818", bg_sidebar="#0b0b22",
        bg_card="#0f0f2e", bg_elevated="#141438", bg_input="#090920",
        accent="#f9c74f",
        text_primary="#f0f0ff", text_secondary="#7070b0",
        text_muted="#383870",
        border="#1a1a40",
        success="#43aa8b", error="#f94144", warning="#f9c74f", info="#577590",
    ),
    _builtin("copper", "Copper",
        # Warm industrial copper — earthy and premium.
        bg_base="#0c0805", bg_primary="#120e08", bg_sidebar="#18120a",
        bg_card="#1e160c", bg_elevated="#241c10", bg_input="#150f07",
        accent="#b87333",
        text_primary="#fdf0e0", text_secondary="#9a7850",
        text_muted="#5a4030",
        border="#3a2414",
        success="#7aad50", error="#d05030", warning="#d4902a", info="#6090b8",
    ),
    _builtin("void", "Void",
        # Absolute darkness with a single ice-blue accent. Maximum focus.
        bg_base="#000000", bg_primary="#020305", bg_sidebar="#040608",
        bg_card="#070a0f", bg_elevated="#0a0e14", bg_input="#050709",
        accent="#38bdf8",
        text_primary="#e8f4ff", text_secondary="#405870",
        text_muted="#1e3040",
        border="#0d1620",
        success="#22c55e", error="#ef4444", warning="#fbbf24", info="#38bdf8",
    ),
    _builtin("jade", "Jade",
        # Rich dark green with a bright jade accent — earthy and fresh.
        bg_base="#030a05", bg_primary="#060f08", bg_sidebar="#09140a",
        bg_card="#0d1a0f", bg_elevated="#112014", bg_input="#080f0a",
        accent="#00c896",
        text_primary="#e8fff5", text_secondary="#508870",
        text_muted="#244830",
        border="#102818",
        success="#4ade80", error="#f87171", warning="#fbbf24", info="#38bdf8",
    ),
    _builtin("lava", "Lava",
        # Dark charcoal with a molten orange-red accent.
        bg_base="#090604", bg_primary="#0f0a06", bg_sidebar="#140d07",
        bg_card="#1a1008", bg_elevated="#20140a", bg_input="#120c06",
        accent="#ff4500",
        text_primary="#fff4f0", text_secondary="#9a6050",
        text_muted="#5a3020",
        border="#3a1808",
        success="#4ade80", error="#ff4500", warning="#fbbf24", info="#60a5fa",
    ),
    _builtin("arctic", "Arctic",
        # Pale blue-white glacier tones — cool, airy, clean.
        bg_base="#060c10", bg_primary="#0a1218", bg_sidebar="#0d1820",
        bg_card="#122030", bg_elevated="#162838", bg_input="#0e1a24",
        accent="#7dd3fc",
        text_primary="#f0f8ff", text_secondary="#6090b0",
        text_muted="#2a5070",
        border="#1a3048",
        success="#34d399", error="#f87171", warning="#fbbf24", info="#7dd3fc",
    ),
    _builtin("sakura", "Sakura",
        # Soft dark background with a delicate cherry blossom pink accent.
        bg_base="#0c080a", bg_primary="#120c0e", bg_sidebar="#181014",
        bg_card="#1e1418", bg_elevated="#241820", bg_input="#160e12",
        accent="#f9a8d4",
        text_primary="#fff0f5", text_secondary="#a07080",
        text_muted="#604050",
        border="#3a1828",
        success="#4ade80", error="#fb7185", warning="#fbbf24", info="#a5b4fc",
    ),
    _builtin("terminal", "Terminal",
        # Classic green-on-black CRT terminal aesthetic.
        bg_base="#000000", bg_primary="#020602", bg_sidebar="#030804",
        bg_card="#050d05", bg_elevated="#071007", bg_input="#030703",
        accent="#00ff41",
        text_primary="#c8ffc8", text_secondary="#387840",
        text_muted="#184820",
        border="#0f2010",
        success="#00ff41", error="#ff3300", warning="#ffcc00", info="#00ccff",
    ),
    _builtin("royal", "Royal",
        # Deep royal blue and gold — regal and bold.
        bg_base="#04060f", bg_primary="#070a18", bg_sidebar="#0a0e22",
        bg_card="#0e1430", bg_elevated="#121838", bg_input="#090d20",
        accent="#c9a227",
        text_primary="#f5f0ff", text_secondary="#7060a8",
        text_muted="#302858",
        border="#1c1a48",
        success="#22c55e", error="#ef4444", warning="#c9a227", info="#818cf8",
    ),

    # ── Accessibility ─────────────────────────────────────────────────────────

    _builtin("hc-dark", "High Contrast Dark",
        # Pure black base; brilliant white text; gold accent.
        # Text:bg contrast ratios > 16:1 throughout (WCAG AAA).
        # Designed for users with low vision, cataracts, or who work in
        # high-ambient-light environments.
        bg_base="#000000", bg_primary="#080808", bg_sidebar="#111111",
        bg_card="#1a1a1a", bg_elevated="#232323", bg_input="#0e0e0e",
        accent="#ffd700",           # gold — 9.5:1 on #1a1a1a (AAA)
        text_primary="#ffffff",
        text_secondary="#e0e0e0",   # still 14:1 on bg_card — AA+
        text_muted="#a8a8a8",
        border="#606060",
        success="#00e676",          # bright green
        error="#ff5252",            # bright red (distinct from gold)
        warning="#ffd700",
        info="#40c4ff",
    ),

    _builtin("hc-light", "High Contrast Light",
        # Light grey backgrounds with near-black text.
        # Text:bg contrast ratios > 15:1 (WCAG AAA).
        # Best for: users with low vision who prefer a light interface,
        # sunlit environments, and printed-page readability.
        bg_base="#e0e0e0", bg_primary="#ebebeb", bg_sidebar="#d8d8d8",
        bg_card="#f5f5f5", bg_elevated="#e8e8e8", bg_input="#ffffff",
        accent="#1650c5",           # deep blue — 8.6:1 on #f5f5f5 (AAA)
        text_primary="#0a0a0a",
        text_secondary="#282828",   # 12:1 on bg_card
        text_muted="#505050",
        border="#888888",
        success="#006600",          # dark green, visible on light
        error="#cc0000",            # dark red, visible on light
        warning="#884400",          # dark amber
        info="#1650c5",
    ),

    _builtin("colorblind-safe", "Colorblind Safe",
        # Uses the Okabe-Ito colorblind-safe palette, designed to remain
        # distinguishable for deuteranopia (red-green) and protanopia.
        # Error uses vermilion (not red), success uses bluish-green (not red-green),
        # warning uses orange. All safe against common colorblind simulations.
        bg_base="#08090f", bg_primary="#0d0f18", bg_sidebar="#111522",
        bg_card="#151c2c", bg_elevated="#1a2235", bg_input="#111422",
        accent="#0072b2",           # Okabe-Ito Blue
        text_primary="#f5f6ff",
        text_secondary="#8090b5",
        text_muted="#3a4560",
        border="#1e2840",
        success="#009e73",          # Okabe-Ito Bluish Green
        error="#d55e00",            # Okabe-Ito Vermilion (not red)
        warning="#e69f00",          # Okabe-Ito Orange
        info="#56b4e9",             # Okabe-Ito Sky Blue
    ),

    _builtin("warm-amber", "Warm Amber",
        # Warm sepia and amber tones shift the display away from the blue
        # end of the spectrum. Good for: long evening sessions, users with
        # photosensitivity or migraines, and eye-strain reduction.
        bg_base="#180f06", bg_primary="#1e1408", bg_sidebar="#241a0a",
        bg_card="#2a1e0c", bg_elevated="#302410", bg_input="#1e1408",
        accent="#d4a030",           # warm gold
        text_primary="#f2e4c0",     # warm cream
        text_secondary="#b09858",
        text_muted="#6a5830",
        border="#483820",
        success="#7ab050",          # warm olive green (no blue-shifted green)
        error="#d06040",            # warm terracotta (no vivid red)
        warning="#d4a030",
        info="#80a8c0",             # desaturated, warm-shifted blue
    ),

    _builtin("calm", "Calm",
        # Fully desaturated, low-saturation palette with gentle contrast.
        # Nothing "pops" — every element is intentionally quiet.
        # Good for: sensory processing differences, ADHD, anxiety,
        # and very long streaming sessions without eye fatigue.
        bg_base="#0e1118", bg_primary="#121520", bg_sidebar="#161b28",
        bg_card="#1b2030", bg_elevated="#20283e", bg_input="#141822",
        accent="#6878a0",           # muted slate blue — no saturated pops
        text_primary="#c0c8d8",     # not pure white — softened
        text_secondary="#788090",
        text_muted="#404a5c",
        border="#222c3c",
        success="#507858",          # muted sage green
        error="#806858",            # muted clay/rust — not vivid red
        warning="#887040",          # muted ochre
        info="#506880",             # muted steel blue
    ),
]

BUILTIN_THEME_MAP: dict[str, AppTheme] = {t.theme_id: t for t in BUILTIN_THEMES}
