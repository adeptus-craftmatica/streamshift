from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from stream_controller.ui.ui_utils import copy_with_feedback
from stream_controller.constants import ALERT_OVERLAY_PORT

if TYPE_CHECKING:
    from stream_controller.plugins.alert_manager.alert_models import AlertConfig, AlertEvent, AlertType
    from stream_controller.plugins.alert_manager.alert_queue import AlertQueue

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".streamshift" / "alert_manager" / "config.json"

_TYPE_LABELS = {
    "follower":   "Follower",
    "subscriber": "Subscriber",
    "gift_sub":   "Gift Sub",
    "bits":       "Bits",
    "raid":       "Raid",
    "donation":   "Donation",
}

_STYLE_OPTIONS = [
    ("Card (Glassmorphism)", "card"),
    ("Neon (Cyberpunk)", "neon"),
    ("Banner (Full-Width)", "banner"),
    ("Minimal (Toast)", "minimal"),
    ("Fire (Impact)", "fire"),
    ("Gear (Mechanical)", "gear"),
    ("Hologram (Sci-Fi)", "hologram"),
    ("Scroll (Fantasy)", "scroll"),
    ("Pixel (Retro 8-bit)", "pixel"),
    ("Blueprint (Technical)", "blueprint"),
]

_BASE_URL = f"http://localhost:{ALERT_OVERLAY_PORT}"


class AlertManagerPage(QWidget):
    def __init__(
        self,
        queue: AlertQueue,
        get_config: Callable[[str], AlertConfig],
        configs: dict[str, AlertConfig],
        overlay_url: str,
        on_style_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._queue = queue
        self._get_config = get_config
        self._configs = configs
        self._overlay_url = overlay_url
        self._on_style_change = on_style_change

        _s = QSettings("StreamShift", "StreamController")
        self._ov_accent: str = _s.value("alerts/accent", "b87820")

        # Per-row widget references: key = alert_type value string
        self._row_widgets: dict[str, dict] = {}
        # URL label references for live updates when accent changes
        self._url_label_refs: list[tuple[QLabel, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── Header ──────────────────────────────────────────────────────────
        title = QLabel("Alert Manager")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        desc = QLabel(
            "Show animated follower, subscriber, bits, raid, and donation alerts "
            "as OBS browser-source overlays. Each alert type has its own URL and "
            "selectable visual style."
        )
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # ── Tabs ─────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(self._build_settings_tab(), "Alert Settings")
        tabs.addTab(self._build_styles_tab(), "Overlay Styles")
        tabs.addTab(self._build_about_tab(), "About")
        root.addWidget(tabs, 1)

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(10)

        for type_key, label in _TYPE_LABELS.items():
            config = self._configs.get(type_key)
            row_widget = self._build_alert_row(type_key, label, config)
            layout.addWidget(row_widget)

        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _build_alert_row(self, type_key: str, label: str, config: AlertConfig | None) -> QGroupBox:
        box = QGroupBox()
        main = QVBoxLayout(box)
        main.setContentsMargins(12, 10, 12, 12)
        main.setSpacing(8)

        # Row 1: Title + Enabled + Test
        title_row = QHBoxLayout()
        title_lbl = QLabel(label)
        title_lbl.setObjectName("CardTitle")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)

        enabled_cb = QCheckBox("Enabled")
        enabled_cb.setChecked(config.enabled if config else True)
        title_row.addWidget(enabled_cb)

        test_btn = QPushButton("Test")
        test_btn.setFixedWidth(60)
        def _on_test(_, k=type_key, b=test_btn):
            self._test_alert(k)
            b.setText("✓")
            b.setEnabled(False)
            QTimer.singleShot(1500, lambda: (b.setText("Test"), b.setEnabled(True)))
        test_btn.clicked.connect(_on_test)
        title_row.addWidget(test_btn)

        main.addLayout(title_row)

        # Row 2: Style selector
        style_row = QHBoxLayout()
        style_lbl = QLabel("Overlay style:")
        style_lbl.setFixedWidth(100)
        style_row.addWidget(style_lbl)

        style_combo = QComboBox()
        for display_name, value in _STYLE_OPTIONS:
            style_combo.addItem(display_name, value)

        current_style = config.overlay_style if config else "card"
        for i in range(style_combo.count()):
            if style_combo.itemData(i) == current_style:
                style_combo.setCurrentIndex(i)
                break

        style_row.addWidget(style_combo, 1)
        main.addLayout(style_row)

        # Row 3: Browser Source URL
        url_row = QHBoxLayout()
        url_lbl = QLabel("Browser Source URL:")
        url_lbl.setFixedWidth(140)
        url_row.addWidget(url_lbl)

        type_url = f"{_BASE_URL}/overlay/{type_key}"
        url_edit = QLineEdit(type_url)
        url_edit.setReadOnly(True)
        url_edit.setObjectName("MonoInput")
        url_row.addWidget(url_edit, 1)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(lambda _, u=type_url, btn=copy_btn: copy_with_feedback(btn, u))
        url_row.addWidget(copy_btn)
        main.addLayout(url_row)

        # Row 4: Message template + Duration
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        template_edit = QLineEdit()
        template_edit.setPlaceholderText(
            config.default_template() if config else ""
        )
        template_edit.setText(config.message_template if config else "")
        form.addRow("Message template:", template_edit)

        duration_spin = QSpinBox()
        duration_spin.setRange(1000, 30000)
        duration_spin.setSingleStep(500)
        duration_spin.setSuffix(" ms")
        duration_spin.setValue(config.duration_ms if config else 5000)
        form.addRow("Duration:", duration_spin)

        main.addLayout(form)

        # Wire save on change
        enabled_cb.toggled.connect(lambda v, k=type_key: self._on_field_changed(k))
        style_combo.currentIndexChanged.connect(lambda v, k=type_key: self._on_style_combo_changed(k))
        template_edit.textChanged.connect(lambda v, k=type_key: self._on_field_changed(k))
        duration_spin.valueChanged.connect(lambda v, k=type_key: self._on_field_changed(k))

        self._row_widgets[type_key] = {
            "enabled": enabled_cb,
            "style": style_combo,
            "template": template_edit,
            "duration": duration_spin,
        }

        return box

    def _on_field_changed(self, type_key: str) -> None:
        self._update_config(type_key)
        self.save_config()

    def _on_style_combo_changed(self, type_key: str) -> None:
        self._update_config(type_key)
        self.save_config()
        if self._on_style_change:
            self._on_style_change(type_key)

    def _update_config(self, type_key: str) -> None:
        widgets = self._row_widgets.get(type_key)
        if not widgets:
            return
        config = self._configs.get(type_key)
        if config is None:
            return
        config.enabled = widgets["enabled"].isChecked()
        config.overlay_style = widgets["style"].currentData()
        config.message_template = widgets["template"].text()
        config.duration_ms = widgets["duration"].value()

    def _test_alert(self, type_key: str) -> None:
        from stream_controller.plugins.alert_manager.alert_models import AlertEvent, AlertType
        try:
            alert_type = AlertType(type_key)
        except ValueError:
            return
        event = AlertEvent(
            alert_type=alert_type,
            name="TestUser",
            tier="Tier 1",
            count=5,
            amount=9.99,
            message="This is a test alert!",
            is_test=True,
        )
        self._queue.enqueue(event)

    def _copy_text(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    # ── Styles tab ────────────────────────────────────────────────────────────

    def _build_styles_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_overlay_appearance_card())
        layout.addWidget(self._build_alert_url_grid())
        layout.addWidget(self._build_style_preview_grid())
        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _build_overlay_appearance_card(self) -> QGroupBox:
        box = QGroupBox("Overlay Appearance")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 10, 16, 14)
        layout.setSpacing(10)

        desc = QLabel(
            "Accent colour applied to the Gear, Hologram, Scroll, Pixel, and Blueprint styles. "
            "The URL automatically includes this colour — just paste it into OBS as-is."
        )
        desc.setWordWrap(True)
        desc.setObjectName("CardDescription")
        layout.addWidget(desc)

        row = QHBoxLayout()
        row.setSpacing(10)

        lbl = QLabel("Accent Colour")
        lbl.setObjectName("MusicFieldLabel")
        row.addWidget(lbl)

        self._accent_swatch = QPushButton()
        self._accent_swatch.setObjectName("ColorSwatch")
        self._accent_swatch.setFixedSize(32, 32)
        self._accent_swatch.setToolTip("Click to pick an accent colour")
        self._accent_swatch.clicked.connect(self._open_accent_picker)

        self._accent_edit = QLineEdit(self._ov_accent)
        self._accent_edit.setObjectName("OverlayTextField")
        self._accent_edit.setMaximumWidth(90)
        self._accent_edit.setPlaceholderText("b87820")
        self._accent_edit.textChanged.connect(self._on_accent_changed)

        self._apply_swatch(self._ov_accent)
        row.addWidget(self._accent_swatch)
        row.addWidget(self._accent_edit)
        row.addStretch(1)
        layout.addLayout(row)

        return box

    def _apply_swatch(self, hex_str: str) -> None:
        color = QColor(f"#{hex_str.strip().lstrip('#')}")
        if color.isValid():
            self._accent_swatch.setStyleSheet(
                f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
            )

    def _open_accent_picker(self) -> None:
        current = QColor(f"#{self._ov_accent}")
        color = QColorDialog.getColor(
            current if current.isValid() else QColor("#b87820"),
            self,
            "Choose Overlay Accent Colour",
        )
        if color.isValid():
            hex_val = color.name().lstrip("#")
            self._accent_edit.blockSignals(True)
            self._accent_edit.setText(hex_val)
            self._accent_edit.blockSignals(False)
            self._ov_accent = hex_val
            self._apply_swatch(hex_val)
            self._save_accent()
            self._refresh_overlay_urls()

    def _on_accent_changed(self, text: str) -> None:
        clean = text.strip().lstrip("#")
        self._ov_accent = clean
        self._apply_swatch(clean)
        self._save_accent()
        self._refresh_overlay_urls()

    def _save_accent(self) -> None:
        QSettings("StreamShift", "StreamController").setValue("alerts/accent", self._ov_accent)

    def _build_url_for_type(self, type_key: str) -> str:
        base = self._overlay_url.rstrip("/") if self._overlay_url else _BASE_URL
        url = f"{base}/overlay/{type_key}"
        if self._ov_accent:
            url += f"?accent={self._ov_accent}"
        return url

    def _refresh_overlay_urls(self) -> None:
        for lbl, type_key in self._url_label_refs:
            url = self._build_url_for_type(type_key)
            lbl.setText(url)
            lbl.setProperty("_current_url", url)

    def _build_alert_url_grid(self) -> QFrame:
        """Grid of alert-type browser-source URL cards (one per type)."""
        self._url_label_refs.clear()
        container = QFrame()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        type_icons = {
            "follower":   "👤",
            "subscriber": "⭐",
            "gift_sub":   "🎁",
            "bits":       "💎",
            "raid":       "⚔️",
            "donation":   "💰",
        }

        items = list(_TYPE_LABELS.items())
        for idx, (type_key, label) in enumerate(items):
            url = self._build_url_for_type(type_key)
            card = self._make_url_card(type_icons.get(type_key, "🎉"), label, type_key, url)
            grid.addWidget(card, idx // 3, idx % 3)

        return container

    def _make_url_card(self, icon: str, label: str, type_key: str, url: str) -> QFrame:
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("OverlayCardTitle")
        name_lbl = QLabel(label)
        name_lbl.setObjectName("OverlayCardTitle")
        header.addWidget(icon_lbl)
        header.addWidget(name_lbl, 1)
        layout.addLayout(header)

        obs_lbl = QLabel("1920 × 1080 px")
        obs_lbl.setObjectName("OverlayOBSHint")
        layout.addWidget(obs_lbl)

        url_lbl = QLabel(url)
        url_lbl.setObjectName("OverlayURL")
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_lbl.setWordWrap(False)
        url_lbl.setProperty("_current_url", url)
        layout.addWidget(url_lbl)
        self._url_label_refs.append((url_lbl, type_key))

        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(lambda _=False, lbl=url_lbl, btn=copy_btn: copy_with_feedback(btn, lbl.property("_current_url") or ""))
        layout.addWidget(copy_btn)

        return card

    def _build_style_preview_grid(self) -> QWidget:
        """2-column grid of style preview cards with visual mocks."""
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        styles = [
            {
                "name": "Card",
                "value": "card",
                "obs_size": "1920 × 1080 px",
                "desc": "Frosted-glass card centred at the bottom with an animated rotating gradient border (purple → pink → cyan) and a slide-up entrance. Best for: general purpose, clean streams.",
                "preview": self._make_preview_card_style,
            },
            {
                "name": "Neon",
                "value": "neon",
                "obs_size": "1920 × 1080 px",
                "desc": "Dark panel in the bottom-right with a neon glow border, monospace font, and a scan-line sweep animation. Border colour changes per event type. Best for: gaming streams, cyberpunk themes.",
                "preview": self._make_preview_neon_style,
            },
            {
                "name": "Banner",
                "value": "banner",
                "obs_size": "1920 × 1080 px",
                "desc": "Full-width ribbon pinned to the bottom edge, ~90 px tall. Slides up from below with a coloured accent strip, icon, name, and shimmer sweep. Best for: high-visibility alerts, talk shows.",
                "preview": self._make_preview_banner_style,
            },
            {
                "name": "Minimal",
                "value": "minimal",
                "obs_size": "1920 × 1080 px",
                "desc": "Compact pill-shaped toast in the top-right corner with a coloured dot and a progress bar that shrinks over the alert duration. Best for: busy layouts where screen real estate matters.",
                "preview": self._make_preview_minimal_style,
            },
            {
                "name": "Fire",
                "value": "fire",
                "obs_size": "1920 × 1080 px",
                "desc": "Dramatic card at the bottom with animated canvas fire particles rising above it. Gradient name text and spring scale-in animation. Best for: raids, large gift-sub bombs, hype moments.",
                "preview": self._make_preview_fire_style,
            },
            {
                "name": "Gear",
                "value": "gear",
                "obs_size": "1920 × 1080 px",
                "desc": "Mechanical riveted-plate card centred at the bottom with animated rotating gears above it. Brass/gold accent colour. Customise the accent in Overlay Appearance. Best for: crafting, engineering, maker streams.",
                "preview": self._make_preview_gear_style,
            },
            {
                "name": "Hologram",
                "value": "hologram",
                "obs_size": "1920 × 1080 px",
                "desc": "Sci-fi holographic projection on the right side of the screen. Scan-line texture, glitch entrance, and a blinking signal indicator. Customise accent colour. Best for: sci-fi, tech, futuristic streams.",
                "preview": self._make_preview_hologram_style,
            },
            {
                "name": "Scroll",
                "value": "scroll",
                "obs_size": "1920 × 1080 px",
                "desc": "Fantasy parchment scroll that unfurls in the centre of the screen. Warm sepia tones, wooden scroll rods, serif text. Best for: fantasy, RPG, storytelling, and lore-heavy streams.",
                "preview": self._make_preview_scroll_style,
            },
            {
                "name": "Pixel",
                "value": "pixel",
                "obs_size": "1920 × 1080 px",
                "desc": "8-bit retro achievement notification that slides in from the bottom-left with chunky pixel-art borders and arcade-style text. Customise accent colour. Best for: retro gaming, pixel-art streams.",
                "preview": self._make_preview_pixel_style,
            },
            {
                "name": "Blueprint",
                "value": "blueprint",
                "obs_size": "1920 × 1080 px",
                "desc": "Technical engineering blueprint card in the top-left corner. Graph-paper grid background, monospace annotation text, typed name reveal, and a blinking status dot. Best for: maker, engineering, DIY streams.",
                "preview": self._make_preview_blueprint_style,
            },
        ]

        for i, s in enumerate(styles):
            card = self._make_style_card(s)
            grid.addWidget(card, i // 2, i % 2)

        return container

    def _make_style_card(self, s: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        preview = s["preview"]()
        layout.addWidget(preview)

        name_row = QHBoxLayout()
        name_lbl = QLabel(s["name"])
        name_lbl.setObjectName("OverlayCardTitle")
        obs_lbl = QLabel(s["obs_size"])
        obs_lbl.setObjectName("OverlayOBSHint")
        name_row.addWidget(name_lbl)
        name_row.addStretch(1)
        name_row.addWidget(obs_lbl)
        layout.addLayout(name_row)

        desc_lbl = QLabel(s["desc"])
        desc_lbl.setObjectName("CardDescription")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        return card

    # ── Alert style preview mocks ─────────────────────────────────────────────

    def _make_preview_card_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        row = QHBoxLayout()
        row.setSpacing(10)
        icon_lbl = QLabel("⭐")
        icon_lbl.setObjectName("OverlayMockTitle")
        row.addWidget(icon_lbl, 0, Qt.AlignVCenter)

        body = QVBoxLayout()
        body.setSpacing(2)
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        msg_lbl = QLabel("just subscribed!")
        msg_lbl.setObjectName("OverlayMockArtist")
        body.addWidget(name_lbl)
        body.addWidget(msg_lbl)
        row.addLayout(body, 1)
        layout.addLayout(row)
        return f

    def _make_preview_neon_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerNeon")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        badge = QLabel("NEW FOLLOWER")
        badge.setObjectName("OverlayMockEQLabel")
        name_lbl = QLabel("STREAMUSER")
        name_lbl.setObjectName("OverlayMockTitle")
        name_lbl.setStyleSheet("QLabel { color: #00ff88; font-family: 'Courier New', monospace; font-weight: bold; letter-spacing: 2px; }")
        msg_lbl = QLabel("Welcome to the stream!")
        msg_lbl.setObjectName("OverlayMockArtist")

        layout.addWidget(badge)
        layout.addWidget(name_lbl)
        layout.addWidget(msg_lbl)
        return f

    def _make_preview_banner_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerSplit")
        f.setFixedHeight(90)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        accent = QFrame()
        accent.setObjectName("OverlayMockBannerStrip")
        accent.setFixedWidth(6)
        layout.addWidget(accent)

        icon_lbl = QLabel("👤")
        icon_lbl.setObjectName("OverlayMockTitle")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFixedWidth(50)
        layout.addWidget(icon_lbl)

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(3)
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        msg_lbl = QLabel("just followed!")
        msg_lbl.setObjectName("OverlayMockArtist")
        body.addWidget(name_lbl)
        body.addWidget(msg_lbl)
        layout.addLayout(body, 1)

        badge_lbl = QLabel("New Follower")
        badge_lbl.setObjectName("OverlayMockBadge")
        badge_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(badge_lbl)
        return f

    def _make_preview_minimal_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerMinimal")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)

        pill = QFrame()
        pill.setObjectName("OverlayMockMinimal")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(14, 8, 14, 8)
        pill_layout.setSpacing(10)

        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(8, 8)
        text_lbl = QLabel("StreamUser  ·  just subscribed!")
        text_lbl.setObjectName("OverlayMockArtist")
        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addWidget(text_lbl)

        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        return f

    def _make_preview_fire_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerFullscreen")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        fire_lbl = QLabel("🔥🔥🔥")
        fire_lbl.setAlignment(Qt.AlignCenter)
        fire_lbl.setObjectName("OverlayMockTitle")
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet("QLabel { color: #ff6600; font-weight: bold; }")
        msg_lbl = QLabel("is raiding with 50 viewers!")
        msg_lbl.setObjectName("OverlayMockArtist")
        msg_lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(fire_lbl)
        layout.addWidget(name_lbl)
        layout.addWidget(msg_lbl)
        return f

    def _make_preview_gear_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        f.setStyleSheet("QFrame#OverlayMockTimerCard { background: linear-gradient(160deg,#1c1208,#2d1a08); border: 1px solid #b87820; }")
        layout = QHBoxLayout(f)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        gear_lbl = QLabel("⚙️")
        gear_lbl.setObjectName("OverlayMockTitle")
        layout.addWidget(gear_lbl, 0, Qt.AlignVCenter)

        body = QVBoxLayout()
        body.setSpacing(2)
        badge = QLabel("NEW FOLLOWER")
        badge.setObjectName("OverlayMockEQLabel")
        badge.setStyleSheet("QLabel { color: #b87820; font-size: 9px; letter-spacing: 2px; }")
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        name_lbl.setStyleSheet("QLabel { color: #f0d090; font-weight: bold; }")
        msg_lbl = QLabel("just followed!")
        msg_lbl.setObjectName("OverlayMockArtist")
        msg_lbl.setStyleSheet("QLabel { color: rgba(210,175,100,0.75); }")
        body.addWidget(badge)
        body.addWidget(name_lbl)
        body.addWidget(msg_lbl)
        layout.addLayout(body, 1)
        return f

    def _make_preview_hologram_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerNeon")
        f.setFixedHeight(90)
        f.setStyleSheet("QFrame#OverlayMockTimerNeon { background: rgba(0,20,30,0.9); border: 1px solid #00d4ff; }")
        layout = QVBoxLayout(f)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        badge = QLabel("SUBSCRIBER")
        badge.setObjectName("OverlayMockEQLabel")
        badge.setStyleSheet("QLabel { color: #00d4ff; font-family: 'Courier New'; font-size: 9px; letter-spacing: 3px; }")
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        name_lbl.setStyleSheet("QLabel { color: #fff; font-family: 'Courier New'; font-weight: bold; }")
        msg_lbl = QLabel("just subscribed!")
        msg_lbl.setObjectName("OverlayMockArtist")
        msg_lbl.setStyleSheet("QLabel { color: rgba(180,230,240,0.7); font-family: 'Courier New'; font-size: 11px; }")

        layout.addWidget(badge)
        layout.addWidget(name_lbl)
        layout.addWidget(msg_lbl)
        return f

    def _make_preview_scroll_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        f.setStyleSheet(
            "QFrame#OverlayMockTimerCard { "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #f4e4c0, stop:0.5 #ede0b0, stop:1 #e8d89a); "
            "border: 2px solid #8b5e2a; }"
        )
        layout = QVBoxLayout(f)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(2)

        badge = QLabel("📜  New Follower")
        badge.setObjectName("OverlayMockEQLabel")
        badge.setStyleSheet("QLabel { color: #6b3a1f; font-style: italic; font-size: 10px; }")
        name_lbl = QLabel("StreamUser")
        name_lbl.setObjectName("OverlayMockTitle")
        name_lbl.setStyleSheet("QLabel { color: #1a0a00; font-family: Georgia, serif; font-weight: bold; }")
        msg_lbl = QLabel("just followed the scroll.")
        msg_lbl.setObjectName("OverlayMockArtist")
        msg_lbl.setStyleSheet("QLabel { color: #3a2010; font-family: Georgia, serif; font-style: italic; font-size: 11px; }")

        layout.addWidget(badge)
        layout.addWidget(name_lbl)
        layout.addWidget(msg_lbl)
        return f

    def _make_preview_pixel_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        f.setStyleSheet(
            "QFrame#OverlayMockTimerCard { background: #0a0a0a; border: none; "
            "border-radius: 0px; "
            "outline: 4px solid #22dd44; }"
        )
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(26)
        header.setStyleSheet("QFrame { background: #22dd44; }")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)
        icon_lbl = QLabel("🕹️  NEW FOLLOWER")
        icon_lbl.setStyleSheet("QLabel { color: #000; font-family: 'Courier New'; font-size: 11px; font-weight: bold; }")
        score_lbl = QLabel("+1 UP")
        score_lbl.setStyleSheet("QLabel { color: #000; font-family: 'Courier New'; font-size: 11px; font-weight: bold; }")
        h_layout.addWidget(icon_lbl, 1)
        h_layout.addWidget(score_lbl)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 6, 10, 6)
        body_layout.setSpacing(2)
        name_lbl = QLabel("▶  STREAMUSER")
        name_lbl.setStyleSheet("QLabel { color: #22dd44; font-family: 'Courier New'; font-weight: bold; font-size: 13px; }")
        msg_lbl = QLabel("just followed!")
        msg_lbl.setStyleSheet("QLabel { color: rgba(150,220,160,0.8); font-family: 'Courier New'; font-size: 11px; }")
        body_layout.addWidget(name_lbl)
        body_layout.addWidget(msg_lbl)
        layout.addWidget(body, 1)
        return f

    def _make_preview_blueprint_style(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        f.setStyleSheet(
            "QFrame#OverlayMockTimerCard { "
            "background: rgba(10,20,45,0.95); "
            "border: 1px solid rgba(100,180,255,0.4); }"
        )
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QFrame()
        title_bar.setFixedHeight(24)
        title_bar.setStyleSheet("QFrame { background: rgba(100,160,255,0.12); border-bottom: 1px solid rgba(100,180,255,0.2); }")
        t_layout = QHBoxLayout(title_bar)
        t_layout.setContentsMargins(10, 0, 10, 0)
        doc_id = QLabel("DOC-FLW")
        doc_id.setStyleSheet("QLabel { color: rgba(120,180,255,0.5); font-family: 'Courier New'; font-size: 9px; letter-spacing: 2px; }")
        type_lbl = QLabel("FOLLOWER ALERT")
        type_lbl.setStyleSheet("QLabel { color: rgba(100,180,255,0.7); font-family: 'Courier New'; font-size: 9px; letter-spacing: 2px; }")
        dot = QLabel("●")
        dot.setStyleSheet("QLabel { color: #4fc3f7; font-size: 10px; }")
        t_layout.addWidget(doc_id)
        t_layout.addWidget(type_lbl, 1)
        t_layout.addWidget(dot)
        layout.addWidget(title_bar)

        body = QWidget()
        b_layout = QVBoxLayout(body)
        b_layout.setContentsMargins(12, 6, 12, 6)
        b_layout.setSpacing(1)
        subj_lbl = QLabel("SUBJECT")
        subj_lbl.setStyleSheet("QLabel { color: rgba(100,180,255,0.5); font-family: 'Courier New'; font-size: 8px; letter-spacing: 2px; }")
        name_lbl = QLabel("StreamUser_")
        name_lbl.setStyleSheet("QLabel { color: #c8e4ff; font-family: 'Courier New'; font-weight: bold; font-size: 14px; }")
        b_layout.addWidget(subj_lbl)
        b_layout.addWidget(name_lbl)
        layout.addWidget(body, 1)
        return f

    # ── About tab ─────────────────────────────────────────────────────────────

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml("""
        <h3>Adding Alerts to OBS</h3>
        <p>Each alert type has its own browser-source URL. Add a separate Browser source
        in OBS for each alert type you want to show:</p>
        <ul>
          <li><code>http://localhost:47898/overlay/follower</code></li>
          <li><code>http://localhost:47898/overlay/subscriber</code></li>
          <li><code>http://localhost:47898/overlay/gift_sub</code></li>
          <li><code>http://localhost:47898/overlay/bits</code></li>
          <li><code>http://localhost:47898/overlay/raid</code></li>
          <li><code>http://localhost:47898/overlay/donation</code></li>
        </ul>
        <ol>
          <li>Copy the Browser Source URL for the alert type from the Alert Settings tab.</li>
          <li>In OBS, click the <b>+</b> button in the Sources panel and choose <b>Browser</b>.</li>
          <li>Paste the URL into the URL field.</li>
          <li>Set the width to <b>1920</b> and height to <b>1080</b> (or match your canvas size).</li>
          <li>Check <b>Shutdown source when not visible</b> and <b>Refresh browser when scene becomes active</b>.</li>
          <li>Click OK. Alerts will appear on screen when events fire.</li>
        </ol>
        <h3>Customising Alerts</h3>
        <p>Use the <b>Alert Settings</b> tab to:</p>
        <ul>
          <li>Enable or disable individual alert types.</li>
          <li>Choose the visual style per alert type (Card, Neon, Banner, Minimal, Fire).</li>
          <li>Change the message template (use <code>{name}</code>, <code>{tier}</code>,
              <code>{count}</code>, <code>{amount}</code> as placeholders).</li>
          <li>Adjust how long each alert stays on screen.</li>
          <li>Click <b>Test</b> to preview any alert type live.</li>
        </ul>
        <h3>Event Sources</h3>
        <p>Alert Manager listens for events fired by other StreamShift plugins
        (e.g. Stream Stats for Twitch events). No additional credentials are required here.</p>
        """)
        layout.addWidget(browser)
        return w

    # ── Config persistence ─────────────────────────────────────────────────────

    def save_config(self) -> None:
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for type_key, config in self._configs.items():
                data[type_key] = {
                    "enabled": config.enabled,
                    "message_template": config.message_template,
                    "duration_ms": config.duration_ms,
                    "sound_file": config.sound_file,
                    "overlay_style": config.overlay_style,
                }
            _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save alert config")

    @staticmethod
    def load_config() -> dict:
        try:
            if _CONFIG_PATH.exists():
                return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load alert config")
        return {}
