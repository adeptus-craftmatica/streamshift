from __future__ import annotations

import math
import uuid
import random
from typing import Callable

from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient, QBrush, QPen, QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFrame, QLabel, QPushButton, QSlider, QLineEdit, QColorDialog,
    QSizePolicy,
)

from stream_controller.plugins.theme_manager.theme_models import (
    AppTheme, _hex_to_hsl, _hsl_to_hex, _hex_to_rgb,
    lighten, darken, alpha, mix,
)

# ── name generation tables ────────────────────────────────────────────────────

_HUE_NAMES = [
    (10, "Scarlet"), (25, "Vermilion"), (40, "Amber"), (55, "Gold"),
    (70, "Yellow"), (85, "Chartreuse"), (105, "Lime"), (135, "Emerald"),
    (155, "Mint"), (170, "Teal"), (185, "Cyan"), (200, "Sky"),
    (225, "Azure"), (250, "Cobalt"), (265, "Indigo"), (280, "Violet"),
    (295, "Purple"), (310, "Magenta"), (325, "Rose"), (345, "Crimson"),
    (360, "Scarlet"),
]

_HARMONY_SUFFIX = {
    "monochromatic": "", "analogous": " Fade", "complementary": " Dual",
    "split-comp": " Split", "triadic": " Trio", "tetradic": " Quad",
}

_MOOD_SUFFIX = {
    "abyss": " Void", "deep-dark": "", "midnight": " Night",
    "ember": " Ember", "slate": " Slate",
}

# Standard status hues (0–1)
_H_GREEN = 0.333
_H_RED = 0.0
_H_AMBER = 0.111
_H_BLUE = 0.583


def _hue_name(hue_01: float) -> str:
    deg = hue_01 * 360
    for upper, name in _HUE_NAMES:
        if deg <= upper:
            return name
    return "Scarlet"


def _auto_name(hue_01: float, harmony: str, mood: str) -> str:
    base = _hue_name(hue_01)
    return base + _HARMONY_SUFFIX.get(harmony, "") + _MOOD_SUFFIX.get(mood, "")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _wrap(v: float) -> float:
    return v % 1.0


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance (0–1)."""
    r, g, b = _hex_to_rgb(hex_color)
    def lin(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(c1: str, c2: str) -> float:
    l1, l2 = _luminance(c1), _luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _ensure_readable(text_hex: str, bg_hex: str, min_ratio: float) -> str:
    """Push text lightness up (or down) until contrast against bg meets min_ratio."""
    h, l, s = _hex_to_hsl(text_hex)
    # Determine direction: if bg is dark, lighten text; if bg is light, darken it
    bg_h, bg_l, bg_s = _hex_to_hsl(bg_hex)
    direction = 1 if bg_l < 0.5 else -1
    step = 0.03
    for _ in range(30):
        if _contrast(text_hex, bg_hex) >= min_ratio:
            break
        l = _clamp(l + direction * step, 0.02, 0.97)
        text_hex = _hsl_to_hex(h, l, s)
    return text_hex


# ── core generation logic ─────────────────────────────────────────────────────

def _status_hues(harmony: str, accent_h: float) -> tuple[float, float, float, float]:
    """Return (h_success, h_error, h_warning, h_info)."""
    if harmony == "monochromatic":
        return _H_GREEN, _H_RED, _H_AMBER, _H_BLUE

    elif harmony == "analogous":
        h_success = _wrap(accent_h + 1 / 12)
        h_info = _wrap(accent_h - 1 / 12)
        return h_success, _H_RED, _H_AMBER, h_info

    elif harmony == "complementary":
        h_info = _wrap(accent_h + 0.5)
        return _H_GREEN, _H_RED, _H_AMBER, h_info

    elif harmony == "split-comp":
        h_success = _wrap(accent_h + 5 / 12)
        h_info = _wrap(accent_h - 5 / 12)
        return h_success, _H_RED, _H_AMBER, h_info

    elif harmony == "triadic":
        h_success = _wrap(accent_h + 1 / 3)
        h_info = _wrap(accent_h + 2 / 3)
        return h_success, _H_RED, _H_AMBER, h_info

    elif harmony == "tetradic":
        h_success = _wrap(accent_h + 1 / 4)
        h_warning = _wrap(accent_h + 1 / 2)
        h_info = _wrap(accent_h + 3 / 4)
        return h_success, _H_RED, h_warning, h_info

    return _H_GREEN, _H_RED, _H_AMBER, _H_BLUE


def _mood_params(mood: str, accent_h: float) -> tuple[float, float, float]:
    """Return (bg_h, bg_s_base, bg_l_base).  bg_l_base is the deepest layer lightness."""
    if mood == "abyss":
        return accent_h, 0.0, 0.05     # pure near-black, no saturation
    elif mood == "deep-dark":
        return accent_h, 0.12, 0.07    # accent-tinted dark
    elif mood == "midnight":
        return _wrap(accent_h - 0.08), 0.08, 0.07   # cool blue-shifted dark
    elif mood == "ember":
        return _wrap(accent_h + 0.04), 0.10, 0.08   # warm-shifted dark
    elif mood == "slate":
        return 0.58, 0.05, 0.08        # neutral blue-grey dark
    return accent_h, 0.08, 0.07


def generate_theme(
    seed_hex: str,
    harmony: str,
    mood: str,
    vibrancy: float,
    depth: float,
    contrast: float,
    name: str = "",
) -> AppTheme:
    seed_h, seed_l, seed_s = _hex_to_hsl(seed_hex)

    # Accent
    accent_s = _clamp(seed_s * (0.5 + vibrancy * 0.7), 0.3, 1.0)
    accent_l = _clamp(seed_l, 0.45, 0.65)
    accent_hex = _hsl_to_hex(seed_h, accent_l, accent_s)

    # Background — _hsl_to_hex(hue, lightness, saturation)
    bg_h, bg_s_base, bg_l_base = _mood_params(mood, seed_h)
    bg_s_base = bg_s_base * (0.6 + vibrancy * 0.4)
    # step controls how distinguishable each layer is; larger = more contrast between layers
    step = 0.032 + (1.0 - depth) * 0.020

    def bghsl(s_mult: float, l_add: float) -> str:
        l = _clamp(bg_l_base + l_add, 0.0, 1.0)
        s = _clamp(bg_s_base * s_mult, 0.0, 1.0)
        return _hsl_to_hex(bg_h, l, s)

    bg_base = bghsl(1.00, 0.0)
    bg_primary = bghsl(0.95, step * 1.0)
    bg_sidebar = bghsl(0.90, step * 1.3)
    bg_card = bghsl(0.85, step * 2.2)
    bg_elevated = bghsl(0.80, step * 3.5)
    bg_input = bghsl(0.92, step * 0.7)
    border = bghsl(1.10, step * 5.0)

    # Text — _hsl_to_hex(hue, lightness, saturation); slight hue tint for warmth
    text_l_base = 0.88 + contrast * 0.09
    text_primary   = _hsl_to_hex(seed_h, _clamp(text_l_base,        0.0, 1.0), 0.06)
    text_secondary = _hsl_to_hex(seed_h, _clamp(text_l_base * 0.65, 0.0, 1.0), 0.10)
    text_muted     = _hsl_to_hex(seed_h, _clamp(text_l_base * 0.40, 0.0, 1.0), 0.08)

    # Guarantee readability — enforce WCAG contrast against the most common text surface
    text_primary   = _ensure_readable(text_primary,   bg_card, min_ratio=7.0)
    text_secondary = _ensure_readable(text_secondary, bg_card, min_ratio=4.5)
    text_muted     = _ensure_readable(text_muted,     bg_card, min_ratio=3.0)

    # Status colors
    h_suc, h_err, h_war, h_inf = _status_hues(harmony, seed_h)
    success = _hsl_to_hex(h_suc, 0.52, 0.58)
    error = _hsl_to_hex(h_err, 0.65, 0.58)
    warning = _hsl_to_hex(h_war, 0.80, 0.58)
    info = _hsl_to_hex(h_inf, 0.58, 0.58)

    final_name = name or _auto_name(seed_h, harmony, mood)

    return AppTheme(
        theme_id=str(uuid.uuid4()),
        name=final_name,
        builtin=False,
        bg_base=bg_base,
        bg_primary=bg_primary,
        bg_sidebar=bg_sidebar,
        bg_card=bg_card,
        bg_elevated=bg_elevated,
        bg_input=bg_input,
        accent=accent_hex,
        text_primary=text_primary,
        text_secondary=text_secondary,
        text_muted=text_muted,
        border=border,
        success=success,
        error=error,
        warning=warning,
        info=info,
    )


# ── color swatch ──────────────────────────────────────────────────────────────

class _ColorSwatch(QWidget):
    clicked = Signal()

    def __init__(self, color: str = "#7c3aed", parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(80, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) - 6

        # Glow ring
        glow = QColor(self._color)
        glow.setAlpha(70)
        pen = QPen(glow, 6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r + 5, r + 5)

        # Fill circle
        path = QPainterPath()
        path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawPath(path)

        # Thin bright rim
        rim = QColor(self._color).lighter(150)
        rim.setAlpha(120)
        p.setPen(QPen(rim, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r - 0.5, r - 0.5)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()


# ── harmony dots ─────────────────────────────────────────────────────────────

class _HarmonyDots(QWidget):
    def __init__(self, harmony: str, accent: str = "#7c3aed", parent: QWidget | None = None):
        super().__init__(parent)
        self._harmony = harmony
        self._accent = accent
        self.setFixedSize(120, 34)

    def set_accent(self, hex_color: str) -> None:
        self._accent = hex_color
        self.update()

    def _dot_colors(self) -> list[str]:
        h, l, s = _hex_to_hsl(self._accent)
        # Ensure lightness is visible against dark backgrounds
        vis_l = _clamp(l, 0.45, 0.70)
        if self._harmony == "monochromatic":
            return [
                _hsl_to_hex(h, 0.38, s), _hsl_to_hex(h, 0.50, s),
                _hsl_to_hex(h, 0.62, s), _hsl_to_hex(h, 0.75, s),
            ]
        elif self._harmony == "analogous":
            return [
                _hsl_to_hex(_wrap(h - 1/12), vis_l, s),
                _hsl_to_hex(h, vis_l, s),
                _hsl_to_hex(_wrap(h + 1/12), vis_l, s),
            ]
        elif self._harmony == "complementary":
            return [
                _hsl_to_hex(h, vis_l, s),
                _hsl_to_hex(_wrap(h + 0.5), vis_l, s),
            ]
        elif self._harmony == "split-comp":
            return [
                _hsl_to_hex(h, vis_l, s),
                _hsl_to_hex(_wrap(h + 5/12), vis_l, s),
                _hsl_to_hex(_wrap(h - 5/12), vis_l, s),
            ]
        elif self._harmony == "triadic":
            return [
                _hsl_to_hex(h, vis_l, s),
                _hsl_to_hex(_wrap(h + 1/3), vis_l, s),
                _hsl_to_hex(_wrap(h + 2/3), vis_l, s),
            ]
        elif self._harmony == "tetradic":
            return [
                _hsl_to_hex(h, vis_l, s),
                _hsl_to_hex(_wrap(h + 0.25), vis_l, s),
                _hsl_to_hex(_wrap(h + 0.5), vis_l, s),
                _hsl_to_hex(_wrap(h + 0.75), vis_l, s),
            ]
        return [self._accent]

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = self._dot_colors()
        n = len(colors)
        r = 11
        gap = 5
        total_w = n * r * 2 + (n - 1) * gap
        x = (self.width() - total_w) / 2
        cy = self.height() / 2
        for c in colors:
            color = QColor(c)
            # Subtle drop shadow / glow
            glow = QColor(color)
            glow.setAlpha(50)
            p.setPen(QPen(glow, 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x + r, cy), r + 2, r + 2)
            # Fill
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(x + r, cy), r, r)
            x += r * 2 + gap


# ── harmony card ─────────────────────────────────────────────────────────────

_HARMONY_INFO = {
    "monochromatic": ("Monochromatic", "One hue, many shades"),
    "analogous": ("Analogous", "Neighboring hues blend"),
    "complementary": ("Complementary", "Opposite hue contrast"),
    "split-comp": ("Split-Comp", "Two near-complements"),
    "triadic": ("Triadic", "Three balanced hues"),
    "tetradic": ("Tetradic", "Four hues at 90°"),
}


class _HarmonyCard(QFrame):
    selected_changed = Signal(str)

    def __init__(self, key: str, accent: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._key = key
        self._accent = accent
        self._selected = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("harmonyCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(96)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(6)

        self._dots = _HarmonyDots(key, accent)
        lay.addWidget(self._dots, 0, Qt.AlignmentFlag.AlignHCenter)

        title, desc = _HARMONY_INFO.get(key, (key, ""))
        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = lbl_title.font()
        font.setBold(True)
        lbl_title.setFont(font)
        lay.addWidget(lbl_title)

        lbl_desc = QLabel(desc)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f2 = lbl_desc.font()
        f2.setPointSize(f2.pointSize() - 1)
        lbl_desc.setFont(f2)
        lbl_desc.setObjectName("mutedLabel")
        lay.addWidget(lbl_desc)

        self._apply_style(accent)

    def set_accent(self, hex_color: str) -> None:
        self._accent = hex_color
        self._dots.set_accent(hex_color)
        self._apply_style(hex_color)

    def set_selected(self, selected: bool, accent: str = "#7c3aed") -> None:
        self._selected = selected
        self._accent = accent
        self._apply_style(accent)

    def _apply_style(self, accent: str) -> None:
        r, g, b = _hex_to_rgb(accent)
        if self._selected:
            self.setStyleSheet(
                f"QFrame#harmonyCard {{"
                f"  border: 2px solid {accent};"
                f"  border-radius: 10px;"
                f"  background: rgba({r},{g},{b},0.12);"
                f"}}"
            )
        else:
            self.setStyleSheet(
                "QFrame#harmonyCard {"
                "  border: 1px solid rgba(255,255,255,0.08);"
                "  border-radius: 10px;"
                "  background: rgba(255,255,255,0.04);"
                "}"
                "QFrame#harmonyCard:hover {"
                "  border-color: rgba(255,255,255,0.18);"
                "  background: rgba(255,255,255,0.07);"
                "}"
            )

    def mousePressEvent(self, event) -> None:
        self.selected_changed.emit(self._key)


# ── mood strip ────────────────────────────────────────────────────────────────

_MOOD_GRADIENTS = {
    "abyss": ("#050505", "#111111"),
    "deep-dark": ("#0d0d1a", "#1a1a2e"),
    "midnight": ("#080d1a", "#101828"),
    "ember": ("#1a0d08", "#2a1510"),
    "slate": ("#0d1017", "#161d27"),
}

_MOOD_INFO = {
    "abyss": ("Abyss", "Pure black drama"),
    "deep-dark": ("Deep Dark", "Accent-tinted depths"),
    "midnight": ("Midnight", "Cool blue shadows"),
    "ember": ("Ember", "Warm dark tones"),
    "slate": ("Slate", "Muted grey-blue"),
}


class _MoodStrip(QWidget):
    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._key = key
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c1, c2 = _MOOD_GRADIENTS.get(self._key, ("#111", "#222"))
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0, QColor(c1))
        grad.setColorAt(1, QColor(c2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(self.rect(), 4, 4)


class _MoodCard(QFrame):
    selected_changed = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._key = key
        self._selected = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("moodCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(106)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self._strip = _MoodStrip(key)
        lay.addWidget(self._strip)

        title, desc = _MOOD_INFO.get(key, (key, ""))
        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = lbl_title.font()
        font.setBold(True)
        lbl_title.setFont(font)
        lay.addWidget(lbl_title)

        lbl_desc = QLabel(desc)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f2 = lbl_desc.font()
        f2.setPointSize(f2.pointSize() - 1)
        lbl_desc.setFont(f2)
        lbl_desc.setObjectName("mutedLabel")
        lay.addWidget(lbl_desc)

        self._apply_style("#7c3aed")  # placeholder; updated when accent is set

    def set_selected(self, selected: bool, accent: str = "#7c3aed") -> None:
        self._selected = selected
        self._apply_style(accent)

    def _apply_style(self, accent: str) -> None:
        r, g, b = _hex_to_rgb(accent)
        if self._selected:
            self.setStyleSheet(
                f"QFrame#moodCard {{"
                f"  border: 2px solid {accent};"
                f"  border-radius: 10px;"
                f"  background: rgba({r},{g},{b},0.10);"
                f"}}"
            )
        else:
            self.setStyleSheet(
                "QFrame#moodCard {"
                "  border: 1px solid rgba(255,255,255,0.08);"
                "  border-radius: 10px;"
                "  background: rgba(255,255,255,0.04);"
                "}"
                "QFrame#moodCard:hover {"
                "  border-color: rgba(255,255,255,0.18);"
                "  background: rgba(255,255,255,0.07);"
                "}"
            )

    def update_accent(self, accent: str) -> None:
        self._apply_style(accent)

    def mousePressEvent(self, event) -> None:
        self.selected_changed.emit(self._key)


# ── palette preview ───────────────────────────────────────────────────────────

_PREVIEW_SWATCHES = [
    ("bg_base", "BG Base"),
    ("bg_card", "BG Card"),
    ("accent", "Accent"),
    ("text_primary", "Text"),
    ("success", "Success"),
    ("warning", "Warning"),
    ("error", "Error"),
    ("info", "Info"),
]


class _SwatchTile(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(56, 64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._color_box = QFrame()
        self._color_box.setFixedSize(56, 42)
        self._color_box.setStyleSheet("border-radius: 6px; background: #111;")
        lay.addWidget(self._color_box)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = lbl.font()
        f.setPointSize(f.pointSize() - 3)
        lbl.setFont(f)
        lbl.setObjectName("mutedLabel")
        lay.addWidget(lbl)

    def set_color(self, hex_color: str) -> None:
        self._color_box.setStyleSheet(f"border-radius: 6px; background: {hex_color};")


class _PalettePreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._tiles: dict[str, _SwatchTile] = {}
        for key, label in _PREVIEW_SWATCHES:
            tile = _SwatchTile(label)
            self._tiles[key] = tile
            lay.addWidget(tile)
        lay.addStretch()

    def update_theme(self, theme: AppTheme) -> None:
        for key, _ in _PREVIEW_SWATCHES:
            color = getattr(theme, key, "#333333")
            self._tiles[key].set_color(color)


# ── slider row ────────────────────────────────────────────────────────────────

class _SliderRow(QWidget):
    value_changed = Signal(float)

    def __init__(self, label: str, default: float = 0.5, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lbl = QLabel(label)
        lbl.setFixedWidth(70)
        lay.addWidget(lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(int(default * 100))
        lay.addWidget(self._slider, 1)

        self._pct = QLabel(f"{int(default * 100)}%")
        self._pct.setFixedWidth(36)
        self._pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._pct)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int) -> None:
        self._pct.setText(f"{v}%")
        self.value_changed.emit(v / 100.0)

    def value(self) -> float:
        return self._slider.value() / 100.0


# ── section header ────────────────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    f = lbl.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
    f.setPointSize(f.pointSize() - 1)
    f.setBold(True)
    lbl.setFont(f)
    lbl.setObjectName("sectionHeader")
    lbl.setStyleSheet("color: rgba(255,255,255,0.35); margin-bottom: 2px;")
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: rgba(255,255,255,0.06);")
    line.setFixedHeight(1)
    return line


# ── main panel ────────────────────────────────────────────────────────────────

class ThemeGeneratorPanel(QWidget):
    """Premium theme generator panel for StreamShift."""

    theme_ready = Signal(AppTheme)

    _HARMONIES = ["monochromatic", "analogous", "complementary", "split-comp", "triadic", "tetradic"]
    _MOODS = ["abyss", "deep-dark", "midnight", "ember", "slate"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._seed_hex = "#7c3aed"
        self._harmony = "analogous"
        self._mood = "deep-dark"
        self._vibrancy = 0.6
        self._depth = 0.5
        self._contrast = 0.5
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._current_theme: AppTheme | None = None

        self._build_ui()
        self._schedule_preview()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(20, 20, 20, 24)
        lay.setSpacing(20)

        # Header
        header = QLabel("Theme Generator")
        hf = header.font()
        hf.setPointSize(hf.pointSize() + 4)
        hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        sub = QLabel("Craft a complete color palette from a single seed color.")
        sub.setObjectName("mutedLabel")
        sub.setStyleSheet("color: rgba(255,255,255,0.45);")
        lay.addWidget(sub)

        lay.addWidget(_divider())

        # Section 1: Seed color
        lay.addWidget(_section_label("Seed Color"))
        lay.addWidget(self._build_seed_section())

        lay.addWidget(_divider())

        # Section 2: Harmony
        lay.addWidget(_section_label("Color Harmony"))
        lay.addWidget(self._build_harmony_section())

        lay.addWidget(_divider())

        # Section 3: Mood
        lay.addWidget(_section_label("Mood"))
        lay.addWidget(self._build_mood_section())

        lay.addWidget(_divider())

        # Section 4: Fine tune
        lay.addWidget(_section_label("Fine Tune"))
        lay.addWidget(self._build_sliders_section())

        lay.addWidget(_divider())

        # Section 5: Palette preview
        lay.addWidget(_section_label("Palette Preview"))
        self._palette_preview = _PalettePreview()
        lay.addWidget(self._palette_preview)

        lay.addWidget(_divider())

        # Section 6: Save
        lay.addWidget(_section_label("Save"))
        lay.addWidget(self._build_save_section())

        lay.addStretch()

    def _build_seed_section(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(6)

        self._swatch = _ColorSwatch(self._seed_hex)
        self._swatch.clicked.connect(self._pick_color)
        col.addWidget(self._swatch, 0, Qt.AlignmentFlag.AlignLeft)

        self._hex_label = QLabel(self._seed_hex.upper())
        f = self._hex_label.font()
        f.setFamily("Courier New")
        f.setPointSize(f.pointSize() + 1)
        self._hex_label.setFont(f)
        col.addWidget(self._hex_label)

        lay.addLayout(col)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignTop)

        rand_btn = QPushButton("⚄  Randomize")
        rand_btn.setFixedWidth(130)
        rand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rand_btn.setStyleSheet(
            "QPushButton { border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; "
            "padding: 6px 12px; background: rgba(255,255,255,0.05); }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); }"
        )
        rand_btn.clicked.connect(self._randomize_color)
        btn_col.addWidget(rand_btn)

        lay.addLayout(btn_col)
        lay.addStretch()
        return w

    def _build_harmony_section(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        self._harmony_cards: dict[str, _HarmonyCard] = {}
        for i, key in enumerate(self._HARMONIES):
            card = _HarmonyCard(key, self._seed_hex)
            card.selected_changed.connect(self._on_harmony_selected)
            self._harmony_cards[key] = card
            grid.addWidget(card, i // 2, i % 2)

        self._harmony_cards[self._harmony].set_selected(True, self._seed_hex)
        return w

    def _build_mood_section(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        self._mood_cards: dict[str, _MoodCard] = {}
        for i, key in enumerate(self._MOODS):
            card = _MoodCard(key)
            card.selected_changed.connect(self._on_mood_selected)
            self._mood_cards[key] = card
            grid.addWidget(card, i // 3, i % 3)

        self._mood_cards[self._mood].set_selected(True, self._seed_hex)
        return w

    def _build_sliders_section(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._sl_vibrancy = _SliderRow("Vibrancy", self._vibrancy)
        self._sl_vibrancy.value_changed.connect(self._on_vibrancy)
        lay.addWidget(self._sl_vibrancy)

        self._sl_depth = _SliderRow("Depth", self._depth)
        self._sl_depth.value_changed.connect(self._on_depth)
        lay.addWidget(self._sl_depth)

        self._sl_contrast = _SliderRow("Contrast", self._contrast)
        self._sl_contrast.value_changed.connect(self._on_contrast)
        lay.addWidget(self._sl_contrast)

        return w

    def _build_save_section(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        name_row = QHBoxLayout()
        name_lbl = QLabel("Name")
        name_lbl.setFixedWidth(50)
        name_row.addWidget(name_lbl)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Auto-generated name…")
        self._name_edit.setStyleSheet(
            "QLineEdit { border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; "
            "padding: 6px 10px; background: rgba(255,255,255,0.04); }"
            "QLineEdit:focus { border-color: rgba(255,255,255,0.3); }"
        )
        name_row.addWidget(self._name_edit)
        lay.addLayout(name_row)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("✦  Save as Theme")
        self._save_btn.setFixedHeight(38)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._update_save_button_style()
        return w

    # ── event handlers ────────────────────────────────────────────────────────

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._seed_hex), self, "Choose Seed Color")
        if color.isValid():
            self._set_seed(color.name())

    def _randomize_color(self) -> None:
        h = random.random()
        s = 0.6 + random.random() * 0.4
        l = 0.45 + random.random() * 0.2
        self._set_seed(_hsl_to_hex(h, l, s))

    def _set_seed(self, hex_color: str) -> None:
        self._seed_hex = hex_color
        self._swatch.set_color(hex_color)
        self._hex_label.setText(hex_color.upper())
        for card in self._harmony_cards.values():
            card.set_accent(hex_color)
        for card in self._mood_cards.values():
            card.update_accent(hex_color)
        # Re-apply selection styling with new accent
        for key, card in self._harmony_cards.items():
            card.set_selected(key == self._harmony, hex_color)
        for key, card in self._mood_cards.items():
            card.set_selected(key == self._mood, hex_color)
        self._update_save_button_style()
        self._schedule_preview()

    def _on_harmony_selected(self, key: str) -> None:
        self._harmony = key
        for k, card in self._harmony_cards.items():
            card.set_selected(k == key, self._seed_hex)
        self._schedule_preview()

    def _on_mood_selected(self, key: str) -> None:
        self._mood = key
        for k, card in self._mood_cards.items():
            card.set_selected(k == key, self._seed_hex)
        self._schedule_preview()

    def _on_vibrancy(self, v: float) -> None:
        self._vibrancy = v
        self._schedule_preview()

    def _on_depth(self, v: float) -> None:
        self._depth = v
        self._schedule_preview()

    def _on_contrast(self, v: float) -> None:
        self._contrast = v
        self._schedule_preview()

    def _on_save(self) -> None:
        theme = self._generate_theme()
        name = self._name_edit.text().strip()
        if name:
            theme = AppTheme(
                theme_id=theme.theme_id,
                name=name,
                builtin=False,
                bg_base=theme.bg_base,
                bg_primary=theme.bg_primary,
                bg_sidebar=theme.bg_sidebar,
                bg_card=theme.bg_card,
                bg_elevated=theme.bg_elevated,
                bg_input=theme.bg_input,
                accent=theme.accent,
                text_primary=theme.text_primary,
                text_secondary=theme.text_secondary,
                text_muted=theme.text_muted,
                border=theme.border,
                success=theme.success,
                error=theme.error,
                warning=theme.warning,
                info=theme.info,
            )
        self.theme_ready.emit(theme)

    # ── generation & preview ──────────────────────────────────────────────────

    def _schedule_preview(self) -> None:
        self._preview_timer.start(80)

    def _refresh_preview(self) -> None:
        theme = self._generate_theme()
        self._current_theme = theme
        self._palette_preview.update_theme(theme)
        auto_name = _auto_name(
            _hex_to_hsl(self._seed_hex)[0], self._harmony, self._mood
        )
        if not self._name_edit.text().strip():
            self._name_edit.setPlaceholderText(auto_name)

    def _generate_theme(self) -> AppTheme:
        name = self._name_edit.text().strip()
        return generate_theme(
            seed_hex=self._seed_hex,
            harmony=self._harmony,
            mood=self._mood,
            vibrancy=self._vibrancy,
            depth=self._depth,
            contrast=self._contrast,
            name=name,
        )

    def _update_save_button_style(self) -> None:
        accent = self._seed_hex
        r, g, b = _hex_to_rgb(accent)
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: white; border: none; "
            f"border-radius: 8px; padding: 8px 20px; font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background: rgba({r},{g},{b},0.85); }}"
            f"QPushButton:pressed {{ background: rgba({r},{g},{b},0.7); }}"
        )
