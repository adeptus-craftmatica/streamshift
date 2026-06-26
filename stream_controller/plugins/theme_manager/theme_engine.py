from __future__ import annotations

"""
Generates and applies QSS theme overrides to the running QApplication.
The base app.qss is loaded once; a theme-specific overlay is appended to it
whenever the active theme changes. The overlay uses high-specificity selectors
so it wins the cascade over the base stylesheet.

Stage-panel per-panel theming is applied via widget.setStyleSheet() on each
live StagePanel instance, which scopes the rules to that widget subtree only.
"""

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QApplication

from stream_controller.plugins.theme_manager.theme_models import AppTheme, PanelTheme, alpha

logger = logging.getLogger(__name__)

_listeners: list[Callable[[AppTheme], None]] = []
_current_theme: AppTheme | None = None
_repo = None  # ThemeRepository, set by plugin via register_repo()


def register_repo(repo) -> None:
    global _repo
    _repo = repo


def save_panel_theme(panel_id: str, panel_theme: "PanelTheme") -> None:
    """Update the active theme's panel override and persist it."""
    if _repo is not None:
        _repo.save_panel_override_to_active(panel_id, panel_theme)
    if _current_theme is not None:
        _current_theme.panel_overrides[panel_id] = panel_theme


def add_listener(cb: Callable[[AppTheme], None]) -> None:
    if cb not in _listeners:
        _listeners.append(cb)


def remove_listener(cb: Callable[[AppTheme], None]) -> None:
    _listeners[:] = [l for l in _listeners if l is not cb]


def current_theme() -> AppTheme | None:
    return _current_theme


def apply_theme(theme: AppTheme) -> None:
    global _current_theme
    _current_theme = theme

    app = QApplication.instance()
    if app is None:
        return

    base_qss = _load_base_qss()
    overlay = _generate_overlay(theme)
    app.setStyleSheet(base_qss + "\n\n/* ── Active Theme: " + theme.name + " ── */\n" + overlay)

    _apply_panel_overrides(theme)

    for cb in list(_listeners):
        try:
            cb(theme)
        except Exception as exc:
            logger.warning("Theme listener error: %s", exc)


def apply_panel_theme(panel_widget, panel_theme: PanelTheme | None) -> None:
    """Apply per-panel QSS to a live StagePanel widget."""
    if panel_widget is None:
        return
    if panel_theme is None:
        panel_widget.setStyleSheet("")
        return
    panel_widget.setStyleSheet(_panel_qss(panel_theme))


def _apply_panel_overrides(theme: AppTheme) -> None:
    """Find all live StagePanel instances and re-apply per-panel styles."""
    from stream_controller.ui.stage_view.stage_panel import StagePanel
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.allWidgets():
        if isinstance(widget, StagePanel):
            pt = theme.panel_overrides.get(widget.panel_id)
            apply_panel_theme(widget, pt)


def _load_base_qss() -> str:
    from stream_controller.ui.theme import stylesheet_path
    try:
        return stylesheet_path().read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Could not load base QSS: %s", exc)
        return ""


# ── overlay generator ─────────────────────────────────────────────────────────

def _generate_overlay(t: AppTheme) -> str:
    a = alpha  # shorthand

    return f"""
/* ════════════════════════════════════════════════
   StreamShift Theme Overlay
   Applied on top of app.qss — overrides cascade
   ════════════════════════════════════════════════ */

/* ── Global window background ── */
QMainWindow,
QWidget#RootWindow,
QWidget#AppCanvas,
QWidget#ContentSurface {{
    background-color: {t.bg_primary};
}}

QDialog {{
    background-color: {t.bg_primary};
}}

/* ── Sidebar ── */
QWidget#Sidebar {{
    background-color: {t.bg_sidebar};
    border-right: 1px solid {t.border};
}}
QScrollArea#SidebarScroll,
QScrollArea#SidebarScroll > QWidget,
QScrollArea#SidebarScroll > QWidget > QWidget,
QWidget#SidebarInner {{
    background: transparent;
    border: none;
}}
QScrollArea#SidebarScroll QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    border-radius: 2px;
}}
QScrollArea#SidebarScroll QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 2px;
    min-height: 20px;
}}
QScrollArea#SidebarScroll QScrollBar::handle:vertical:hover {{
    background: {t.accent};
}}
QScrollArea#SidebarScroll QScrollBar::add-line:vertical,
QScrollArea#SidebarScroll QScrollBar::sub-line:vertical {{
    height: 0;
}}

QPushButton[navItem="true"] {{
    color: {t.text_secondary};
    background: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton[navItem="true"]:hover {{
    background: {a(t.accent, 0.10)};
    color: {t.text_primary};
}}
QPushButton[navItem="true"]:checked {{
    background: {a(t.accent, 0.18)};
    color: {t.accent_light};
    border-left: 3px solid {t.accent};
}}

/* ── Cards ── */
QFrame#Card {{
    background-color: {t.bg_card};
    border: 1px solid {t.border};
    border-radius: 18px;
}}

QFrame#HeaderCard {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {t.bg_elevated},
        stop:0.55 {t.bg_card},
        stop:1 {t.bg_sidebar}
    );
    border: 1px solid {t.border_strong};
    border-radius: 22px;
}}

QFrame#BrandBlock {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {t.bg_elevated},
        stop:1 {t.bg_card}
    );
    border: 1px solid {t.border_accent};
    border-radius: 20px;
}}

/* ── Action tiles ── */
QFrame#ActionTile {{
    background-color: {t.bg_card};
    border: 1px solid {t.border};
    border-radius: 20px;
}}
QFrame#ActionTile[actionEnabled="true"]:hover {{
    background-color: {t.bg_hover};
    border-color: {a(t.accent, 0.6)};
}}
QFrame#ActionTile[selected="true"] {{
    background-color: {t.bg_selected};
    border-color: {t.accent};
}}
QFrame#ActionTile[actionEnabled="false"] {{
    background-color: {t.bg_input};
    border: 1px solid {t.border};
    opacity: 0.5;
}}

/* ── Inputs ── */
QLineEdit,
QComboBox,
QKeySequenceEdit,
QAbstractSpinBox,
QTextEdit,
QPlainTextEdit {{
    background-color: {t.bg_input};
    color: {t.text_primary};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {a(t.accent, 0.4)};
}}
QLineEdit:focus,
QComboBox:focus,
QAbstractSpinBox:focus,
QTextEdit:focus {{
    border: 1px solid {a(t.accent, 0.7)};
    background-color: {t.bg_elevated};
}}
QLineEdit#OverlayTextField,
QTextEdit#OverlayTextField {{
    background-color: {t.bg_input};
    border: 1px solid {t.border};
    color: {t.text_primary};
    border-radius: 8px;
    padding: 6px 10px;
}}
QLineEdit#OverlayTextField:focus,
QTextEdit#OverlayTextField:focus {{
    border: 1px solid {a(t.accent, 0.7)};
}}

/* ── Buttons ── */
QPushButton {{
    color: {t.text_secondary};
    background: {t.bg_elevated};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {t.bg_hover};
    color: {t.text_primary};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{
    background: {t.bg_card};
}}
QPushButton:disabled {{
    color: {t.text_muted};
    background: {t.bg_input};
    border-color: {t.border};
}}

QPushButton#PrimaryButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.accent_hover},
        stop:1 {t.accent}
    );
    color: {t.text_primary};
    border: 1px solid {a(t.accent, 0.6)};
    border-radius: 8px;
    font-weight: 600;
    padding: 7px 18px;
}}
QPushButton#PrimaryButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.accent_light},
        stop:1 {t.accent_hover}
    );
}}
QPushButton#PrimaryButton:pressed {{
    background: {t.accent_dark};
}}
QPushButton#PrimaryButton:disabled {{
    background: {a(t.accent, 0.25)};
    color: {a(t.text_primary, 0.4)};
    border: 1px solid {a(t.accent, 0.2)};
}}

QPushButton#SecondaryButton {{
    background: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton#SecondaryButton:hover {{
    background: {t.bg_hover};
    color: {t.text_primary};
    border-color: {t.border_strong};
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: {t.bg_primary};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.accent};
}}
QScrollBar:horizontal {{
    background: {t.bg_primary};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t.border_strong};
    border-radius: 4px;
}}

/* ── Menus ── */
QMenu {{
    background: {t.bg_elevated};
    border: 1px solid {t.border_strong};
    border-radius: 10px;
    color: {t.text_primary};
}}
QMenu::item:selected {{
    background: {a(t.accent, 0.18)};
    color: {t.accent_light};
    border-radius: 6px;
}}

/* ── Tabs (MusicTab / BotTab pattern) ── */
QWidget#MusicTabBar,
QWidget#BotTabBar {{
    background: {t.bg_sidebar};
    border-bottom: 1px solid {t.border};
}}
QPushButton#MusicTab {{
    background: transparent;
    color: {t.text_secondary};
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 6px 16px;
    font-size: 13px;
}}
QPushButton#MusicTab:checked {{
    color: {t.accent_light};
    border-bottom: 2px solid {t.accent};
    background: transparent;
}}
QPushButton#MusicTab:hover {{
    color: {t.text_primary};
    background: {a(t.accent, 0.06)};
}}

/* ── Labels ── */
QLabel#PageTitle {{
    color: {t.text_primary};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#CardTitle {{
    color: {t.text_primary};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#CardDescription,
QLabel#EmptyState,
QLabel#MetaText,
QLabel#MetricLabel {{
    color: {t.text_secondary};
}}
QLabel#SidebarSectionTitle,
QLabel#SectionTitle {{
    color: {t.text_muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

/* ── Checkboxes ── */
QCheckBox#OverlayCheckBox {{
    color: {t.text_primary};
    spacing: 8px;
}}
QCheckBox#OverlayCheckBox::indicator:unchecked {{
    background: {t.bg_input};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
}}
QCheckBox#OverlayCheckBox::indicator:checked {{
    background: {t.accent};
    border: 1px solid {t.accent};
    border-radius: 4px;
}}

/* ── Combo box dropdown ── */
QComboBox::drop-down {{
    border: none;
    background: transparent;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {t.text_secondary};
    width: 0;
    height: 0;
}}
QComboBox QAbstractItemView {{
    background: {t.bg_elevated};
    border: 1px solid {t.border_strong};
    selection-background-color: {a(t.accent, 0.25)};
    color: {t.text_primary};
    border-radius: 8px;
}}

/* ── List widgets ── */
QListWidget {{
    background: {t.bg_input};
    border: 1px solid {t.border};
    color: {t.text_primary};
    border-radius: 8px;
    outline: none;
}}
QListWidget::item:selected {{
    background: {a(t.accent, 0.25)};
    color: {t.accent_light};
    border-radius: 6px;
}}
QListWidget::item:hover:!selected {{
    background: {a(t.accent, 0.08)};
    border-radius: 6px;
}}

/* ── Stage View ── */
QWidget#StageToolbar {{
    background: {t.bg_sidebar};
    border-bottom: 1px solid {t.border};
}}
QWidget#StageCanvas {{
    background: {t.bg_base};
}}
QFrame#StagePanel {{
    background: {t.bg_card};
    border: 1px solid {t.border_strong};
    border-radius: 12px;
}}
QFrame#StagePanelView {{
    background: {t.bg_card};
    border: 1px solid {a(t.border, 0.4)};
    border-radius: 10px;
}}
/* Default scroll/tile theming for un-customised panels */
QScrollArea#StagePanelScroll,
QScrollArea#StagePanelScroll > QWidget,
QScrollArea#StagePanelScroll > QWidget > QWidget {{
    background: {t.bg_card};
    border: none;
}}
QScrollArea#StagePanelScroll QFrame#Card,
QScrollArea#StagePanelScroll QFrame#InfoTile,
QScrollArea#StagePanelScroll QFrame#ChatTile,
QScrollArea#StagePanelScroll QFrame#SceneTile,
QScrollArea#StagePanelScroll QFrame#StatsTile,
QScrollArea#StagePanelScroll QFrame#TimerTile,
QScrollArea#StagePanelScroll QFrame#MusicPlayerCard {{
    background: transparent;
    border: none;
    border-radius: 0;
}}
QFrame#StagePanelTitleBar {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {t.accent_darker},
        stop:1 {t.accent_dark}
    );
    border-bottom: 1px solid {a(t.accent, 0.4)};
    border-radius: 10px 10px 0 0;
}}

/* ── Stage toolbar buttons ── */
QPushButton#StageToolbarBtn {{
    background: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border};
    border-radius: 7px;
}}
QPushButton#StageToolbarBtn:hover {{
    background: {t.bg_hover};
    color: {t.text_primary};
}}
QPushButton#StageToolbarBtn:checked {{
    background: {a(t.accent, 0.18)};
    color: {t.accent_light};
    border-color: {a(t.accent, 0.5)};
}}
QPushButton#StagePrimaryBtn {{
    background: {t.accent};
    color: {t.text_primary};
    border: 1px solid {a(t.accent, 0.6)};
    border-radius: 7px;
    font-weight: 600;
}}
QPushButton#StagePrimaryBtn:hover {{
    background: {t.accent_hover};
}}

/* ── Music player ── */
QFrame#MusicPlayerCard {{
    background: {t.bg_card};
    border: 1px solid {t.border};
    border-radius: 18px;
}}
QSlider#MusicVolumeSlider::groove:horizontal,
QSlider#MusicProgressSlider::groove:horizontal {{
    background: {t.bg_elevated};
    border-radius: 3px;
    height: 6px;
}}
QSlider#MusicVolumeSlider::sub-page:horizontal,
QSlider#MusicProgressSlider::sub-page:horizontal {{
    background: {t.accent};
    border-radius: 3px;
}}
QSlider#MusicVolumeSlider::handle:horizontal,
QSlider#MusicProgressSlider::handle:horizontal {{
    background: {t.text_primary};
    border: 2px solid {t.accent};
    border-radius: 6px;
    width: 12px;
    height: 12px;
    margin: -3px 0;
}}

/* ── Scene Designer ── */
QWidget#SidebarPanel {{
    background: {t.bg_sidebar};
}}
QWidget#SidebarHeader {{
    background: {t.bg_sidebar};
    border-bottom: 1px solid {t.border};
}}
QListWidget#SidebarList::item:selected {{
    background: {a(t.accent, 0.18)};
    color: {t.accent_light};
    border-left: 3px solid {t.accent};
}}
QWidget#DesignerToolbar {{
    background: {t.bg_sidebar};
    border-bottom: 1px solid {t.border};
}}

/* ── Bot/sidebar lists ── */
QListWidget#SidebarList {{
    background: transparent;
    border: none;
}}

/* ── Separator ── */
QFrame#Separator[frameShape="4"],
QFrame#Separator[frameShape="5"] {{
    color: {t.border};
    background: {t.border};
}}

/* ── Page tabs (Deck page chips) ── */
QPushButton[deckPageChip="true"] {{
    background: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border};
    border-radius: 14px;
}}
QPushButton[deckPageChip="true"]:hover {{
    background: {t.bg_hover};
    color: {t.text_primary};
    border-color: {t.border_strong};
}}
QPushButton[deckPageChip="true"]:checked {{
    background: {a(t.accent, 0.2)};
    color: {t.accent_light};
    border-color: {a(t.accent, 0.5)};
}}

/* ── Status dots ── */
QLabel#SceneStatusDot {{
    border-radius: 5px;
}}

/* ── MusicFieldLabel ── */
QLabel#MusicFieldLabel {{
    color: {t.text_secondary};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
"""


def _panel_qss(pt: PanelTheme) -> str:
    """Per-panel stylesheet applied directly to a StagePanel widget."""
    from stream_controller.plugins.theme_manager.theme_models import alpha as a
    from stream_controller.plugins.theme_manager.theme_models import darken, lighten
    accent = pt.accent or "#7c3aed"
    bg     = pt.bg     or "#111827"   # fallback so content bg is always explicit
    border = pt.border or ""

    grad_start = pt.title_gradient_start or darken(accent, 0.25)
    grad_end   = pt.title_gradient_end   or darken(accent, 0.12)
    border_rule = f"border: 1px solid {border};" if border else f"border: 1px solid {a(accent, 0.4)};"

    # Tile root objectNames that need their own background overridden
    _tile_selectors = ", ".join([
        "QFrame#Card",
        "QFrame#InfoTile",
        "QFrame#ChatTile",
        "QFrame#SceneTile",
        "QFrame#StatsTile",
        "QFrame#TimerTile",
        "QFrame#MusicPlayerCard",
    ])

    return f"""
/* ── Panel frame ── */
QFrame#StagePanel, QFrame#StagePanelView {{
    background: {bg};
    {border_rule}
    border-radius: 12px;
}}

/* ── Accent stripe ── */
QFrame#StagePanelAccent {{
    background: {accent};
    border: none;
    border-radius: 6px 6px 0 0;
}}

/* ── Title bar ── */
QFrame#StagePanelTitleBar {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {grad_start},
        stop:1 {grad_end}
    );
    border-bottom: 1px solid {a(accent, 0.35)};
    border-radius: 0;
}}
QLabel#StagePanelTitle {{
    color: {a("#ffffff", 0.92)};
    font-weight: 600;
}}
QLabel#StagePanelDragIcon {{
    color: {a(accent, 0.7)};
}}

/* ── Scroll area — use panel bg so content area matches ── */
QScrollArea#StagePanelScroll,
QScrollArea#StagePanelScroll > QWidget,
QScrollArea#StagePanelScroll > QWidget > QWidget {{
    background: {bg};
    border: none;
}}

/* ── Tile root frames — transparent so panel bg shows ── */
{_tile_selectors} {{
    background: transparent;
    border: none;
    border-radius: 0;
}}
"""
