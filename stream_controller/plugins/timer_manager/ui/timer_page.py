from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from stream_controller.ui.theme import create_card
from stream_controller.constants import TIMER_OVERLAY_PORT

if TYPE_CHECKING:
    from stream_controller.plugins.timer_manager.timer_engine import TimerEngine
    from stream_controller.plugins.timer_manager.timer_models import Timer


# ══════════════════════════════════════════════════════════════════════════════
# TIMER PAGE — tabbed: Timers | Overlays
# ══════════════════════════════════════════════════════════════════════════════

class TimerPage(QWidget):
    def __init__(
        self,
        engine: "TimerEngine",
        overlay_base_url: str = "",
        overlay_server=None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._overlay_base_url = overlay_base_url
        self._overlay_server = overlay_server

        # overlay customisation state
        self._ov_accent = "7c3aed"
        self._ov_text = "f0e6ff"
        self._ov_bg = 88
        self._ov_hide_after = 5  # seconds; 0 = never
        self._ov_url_labels: list[QLabel] = []

        # card widgets keyed by timer_id
        self._timer_cards: dict[str, _TimerCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_tab_bar())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_timers_tab())
        self._stack.addWidget(self._build_overlays_tab())
        saved_tab = int(QSettings("StreamShift", "StreamController").value("timer/tab", 0))
        self._stack.setCurrentIndex(saved_tab if 0 <= saved_tab < 2 else 0)
        root.addWidget(self._stack, 1)

        self._engine.subscribe(self._on_engine_updated)
        self._on_engine_updated(self._engine.timers)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("MusicTabBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 0)
        layout.setSpacing(4)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)

        saved_tab = int(QSettings("StreamShift", "StreamController").value("timer/tab", 0))
        for i, label in enumerate(["Timers", "Overlays"]):
            btn = QPushButton(label)
            btn.setObjectName("MusicTab")
            btn.setCheckable(True)
            btn.setChecked(i == saved_tab)
            btn.clicked.connect(lambda _=False, idx=i: (
                self._stack.setCurrentIndex(idx),
                QSettings("StreamShift", "StreamController").setValue("timer/tab", idx),
            ))
            self._tab_group.addButton(btn, i)
            layout.addWidget(btn)

        layout.addStretch(1)
        return bar

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 0 — TIMERS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_timers_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(20, 16, 20, 16)
        outer_layout.setSpacing(12)

        # Top bar: heading + New Timer button
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        heading = QLabel("Timers")
        heading.setObjectName("CardTitle")
        new_btn = QPushButton("+ New Timer")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._open_new_timer_dialog)
        top_row.addWidget(heading, 1)
        top_row.addWidget(new_btn)
        outer_layout.addLayout(top_row)

        # Scrollable list of timer cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch(1)

        self._empty_label = QLabel("No timers yet.\nClick '+ New Timer' to create one.")
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._cards_layout.insertWidget(0, self._empty_label)

        scroll.setWidget(self._cards_container)
        outer_layout.addWidget(scroll, 1)

        return outer

    def _open_new_timer_dialog(self) -> None:
        dlg = _TimerDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        result = dlg.result_data()
        self._engine.add_timer(
            label=result["label"],
            mode=result["mode"],
            duration=result["duration"],
            color=result["color"],
            end_message=result["end_message"],
            loop=result["loop"],
        )

    def _open_edit_timer_dialog(self, timer: "Timer") -> None:
        dlg = _TimerDialog(self, timer=timer)
        if dlg.exec() != QDialog.Accepted:
            return
        result = dlg.result_data()
        self._engine.update_timer(
            timer.timer_id,
            label=result["label"],
            mode=result["mode"],
            duration=result["duration"],
            color=result["color"],
            end_message=result["end_message"],
            loop=result["loop"],
        )

    # ── Engine subscription ───────────────────────────────────────────────────

    def _on_engine_updated(self, timers: list) -> None:
        timer_ids = [t.timer_id for t in timers]
        existing_ids = set(self._timer_cards.keys())

        # Remove cards for deleted timers
        for tid in list(existing_ids):
            if tid not in timer_ids:
                card = self._timer_cards.pop(tid)
                self._cards_layout.removeWidget(card)
                card.deleteLater()

        # Add cards for new timers, update existing
        for t in timers:
            if t.timer_id not in self._timer_cards:
                card = _TimerCard(t, self._engine, self._open_edit_timer_dialog)
                self._timer_cards[t.timer_id] = card
                # Insert before the trailing stretch
                insert_pos = self._cards_layout.count() - 1
                self._cards_layout.insertWidget(insert_pos, card)
            else:
                self._timer_cards[t.timer_id].refresh(t)

        has_timers = bool(timers)
        self._empty_label.setVisible(not has_timers)

        # Refresh overlay URLs when timer list changes (first timer id may change)
        self._refresh_overlay_urls()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — OVERLAYS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_overlays_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_overlay_appearance_card())
        layout.addWidget(self._build_overlay_grid())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_overlay_appearance_card(self) -> QFrame:
        card, body = create_card(
            "Appearance",
            "Customise colours and opacity. URLs update automatically — copy them into OBS or Streamlabs.",
        )
        body.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(20)

        self._accent_edit, accent_swatch = self._make_color_picker(
            "Accent Colour", self._ov_accent, "7c3aed"
        )
        accent_col = QVBoxLayout()
        accent_col.setSpacing(5)
        accent_col.addWidget(_field_label("Accent Colour"))
        accent_col.addLayout(_color_picker_row(self._accent_edit, accent_swatch))
        row.addLayout(accent_col)

        self._text_edit, text_swatch = self._make_color_picker(
            "Text Colour", self._ov_text, "f0e6ff"
        )
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        text_col.addWidget(_field_label("Text Colour"))
        text_col.addLayout(_color_picker_row(self._text_edit, text_swatch))
        row.addLayout(text_col)

        bg_col = QVBoxLayout()
        bg_col.setSpacing(5)
        self._bg_opacity_label = _field_label(f"Background Opacity  ({self._ov_bg}%)")
        bg_col.addWidget(self._bg_opacity_label)
        self._bg_slider = QSlider(Qt.Horizontal)
        self._bg_slider.setObjectName("MusicVolumeSlider")
        self._bg_slider.setRange(0, 100)
        self._bg_slider.setValue(self._ov_bg)
        self._bg_slider.setFixedWidth(180)
        self._bg_slider.valueChanged.connect(self._on_bg_opacity_changed)
        bg_col.addWidget(self._bg_slider)
        row.addLayout(bg_col)

        row.addStretch(1)
        body.addLayout(row)

        # Auto-hide row
        hide_row = QHBoxLayout()
        hide_row.setSpacing(12)
        hide_lbl = _field_label("Auto-hide after finish")
        hide_row.addWidget(hide_lbl)
        self._hide_spin = QSpinBox()
        self._hide_spin.setObjectName("TimerTransportBtn")
        self._hide_spin.setRange(0, 60)
        self._hide_spin.setValue(self._ov_hide_after)
        self._hide_spin.setSuffix(" s")
        self._hide_spin.setSpecialValueText("Never")
        self._hide_spin.setFixedWidth(80)
        self._hide_spin.valueChanged.connect(self._on_hide_after_changed)
        hide_row.addWidget(self._hide_spin)
        hide_note = QLabel("(0 = never hide)")
        hide_note.setObjectName("CardDescription")
        hide_row.addWidget(hide_note)
        hide_row.addStretch(1)
        body.addLayout(hide_row)

        return card

    def _make_color_picker(self, name: str, initial_hex: str, placeholder: str):
        """Return (QLineEdit, swatch QPushButton) wired together."""
        edit = QLineEdit(initial_hex)
        edit.setObjectName("OverlayTextField")
        edit.setMaximumWidth(90)
        edit.setPlaceholderText(placeholder)

        swatch = QPushButton()
        swatch.setObjectName("ColorSwatch")
        swatch.setFixedSize(32, 32)
        swatch.setToolTip(f"Pick {name}")

        def _apply_hex(hex_str: str) -> None:
            hex_str = hex_str.strip().lstrip("#")
            color = QColor(f"#{hex_str}")
            if color.isValid():
                swatch.setStyleSheet(
                    f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                    f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                    f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
                )

        def _open_picker() -> None:
            current = QColor(f"#{edit.text().strip().lstrip('#')}")
            color = QColorDialog.getColor(
                current if current.isValid() else QColor(f"#{placeholder}"),
                self,
                f"Choose {name}",
            )
            if color.isValid():
                hex_val = color.name().lstrip("#")
                edit.blockSignals(True)
                edit.setText(hex_val)
                edit.blockSignals(False)
                _apply_hex(hex_val)
                self._on_overlay_param_changed()

        _apply_hex(initial_hex)
        edit.textChanged.connect(lambda t: (_apply_hex(t), self._on_overlay_param_changed()))
        swatch.clicked.connect(_open_picker)
        return edit, swatch

    def _build_overlay_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        overlays = [
            {
                "name": "Card",
                "path": "/card",
                "obs_size": "400 × 120 px",
                "desc": "Compact card with timer label, large display time, and a progress bar. Great for corner placement in countdown scenes.",
                "preview": self._make_preview_card,
                "mock_name": "OverlayMockTimerCard",
            },
            {
                "name": "Minimal",
                "path": "/minimal",
                "obs_size": "320 × 50 px",
                "desc": "Slim pill showing the timer label and current time. Ideal when you want something subtle that never distracts from your content.",
                "preview": self._make_preview_minimal,
                "mock_name": "OverlayMockTimerMinimal",
            },
            {
                "name": "Circle",
                "path": "/circle",
                "obs_size": "280 × 280 px",
                "desc": "Animated ring that fills as time progresses. The timer label and display time sit at the centre of the ring.",
                "preview": self._make_preview_circle,
                "mock_name": "OverlayMockTimerCircle",
            },
            {
                "name": "Fullscreen",
                "path": "/fullscreen",
                "obs_size": "1920 × 1080 px",
                "desc": "Full-scene countdown overlay. Ideal for break screens or pre-stream countdowns with a centred big-clock display.",
                "preview": self._make_preview_fullscreen,
                "mock_name": "OverlayMockTimerFullscreen",
            },
            {
                "name": "Corner",
                "path": "/corner",
                "obs_size": "220 × 52 px",
                "desc": "Tiny pill badge for a screen corner. Just the label and ticking time — minimum footprint, maximum subtlety.",
                "preview": self._make_preview_corner,
                "mock_name": "OverlayMockTimerCorner",
            },
            {
                "name": "Split",
                "path": "/split",
                "obs_size": "640 × 80 px",
                "desc": "Wide horizontal bar split into label on the left and big time on the right. Works well docked to the top or bottom of your scene.",
                "preview": self._make_preview_split,
                "mock_name": "OverlayMockTimerSplit",
            },
            {
                "name": "Neon",
                "path": "/neon",
                "obs_size": "420 × 140 px",
                "desc": "High-contrast neon-glow display with the timer label beneath a glowing digital clock face. Eye-catching for gaming streams.",
                "preview": self._make_preview_neon,
                "mock_name": "OverlayMockTimerNeon",
            },
            {
                "name": "Orbit",
                "path": "/orbit",
                "obs_size": "280 × 280 px",
                "desc": "Animated circle with five simultaneous motions: a rotating tick ring, counter-spinning accent arcs, an orbiting dot, a spinning inner ring, and a breathing centre glow.",
                "preview": self._make_preview_orbit,
                "mock_name": "OverlayMockTimerOrbit",
            },
            {
                "name": "Surge",
                "path": "/surge",
                "obs_size": "1920 × 1080 px",
                "desc": "Two mirrored wave systems surge toward the centre as the countdown runs down. Calm at the start, turbulent near zero — the waves telegraph urgency without you reading a number.",
                "preview": self._make_preview_surge,
                "mock_name": "OverlayMockTimerSurge",
            },
        ]

        for i, ov in enumerate(overlays):
            card = self._make_overlay_card(ov)
            grid.addWidget(card, i // 2, i % 2)

        return container

    def _make_overlay_card(self, ov: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("OverlayPreviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        preview = ov["preview"]()
        layout.addWidget(preview)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = QLabel(ov["name"])
        name_lbl.setObjectName("OverlayCardTitle")
        obs_lbl = QLabel(ov["obs_size"])
        obs_lbl.setObjectName("OverlayOBSHint")
        name_row.addWidget(name_lbl)
        name_row.addStretch(1)
        name_row.addWidget(obs_lbl)
        layout.addLayout(name_row)

        desc = QLabel(ov["desc"])
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        url_lbl = QLabel()
        url_lbl.setObjectName("OverlayURL")
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_lbl.setWordWrap(False)
        url_lbl.setProperty("_path", ov["path"])
        url_lbl.setText(self._overlay_url(ov["path"]))
        self._ov_url_labels.append(url_lbl)
        layout.addWidget(url_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(lambda _=False, lbl=url_lbl: QGuiApplication.clipboard().setText(lbl.text()))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        return card

    # ── Overlay preview widgets ───────────────────────────────────────────────

    def _make_preview_card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCard")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Coloured left border strip via inner layout trick
        row = QHBoxLayout()
        row.setSpacing(10)
        strip = QFrame()
        strip.setObjectName("OverlayMockBannerStrip")
        strip.setFixedWidth(4)
        row.addWidget(strip)

        info = QVBoxLayout()
        info.setSpacing(2)
        label = QLabel("My Timer")
        label.setObjectName("OverlayMockEQLabel")
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        info.addWidget(label)
        info.addWidget(time_lbl)
        row.addLayout(info, 1)
        layout.addLayout(row)

        # Progress bar track + fill
        track = QFrame()
        track.setObjectName("OverlayMockBarWrap")
        track.setFixedHeight(4)
        track_inner = QHBoxLayout(track)
        track_inner.setContentsMargins(0, 0, 0, 0)
        fill = QFrame()
        fill.setObjectName("OverlayMockBarFill")
        empty = QFrame()
        empty.setObjectName("OverlayMockBarEmpty")
        track_inner.addWidget(fill, 3)
        track_inner.addWidget(empty, 2)
        layout.addWidget(track)

        return f

    def _make_preview_minimal(self) -> QFrame:
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
        sep = QFrame()
        sep.setObjectName("OverlayMockSep")
        sep.setFixedSize(1, 14)
        label = QLabel("My Timer")
        label.setObjectName("OverlayMockArtist")
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addWidget(label)
        pill_layout.addWidget(sep, 0, Qt.AlignVCenter)
        pill_layout.addWidget(time_lbl)
        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        return f

    def _make_preview_circle(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCircle")
        f.setFixedHeight(130)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignCenter)
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            svg_data = _circle_preview_svg("7c3aed").encode()
            svg = QSvgWidget()
            svg.load(svg_data)
            svg.setFixedSize(110, 110)
            layout.addWidget(svg, 0, Qt.AlignCenter)
        except ImportError:
            lbl = QLabel("◎  Ring circle\n(280 × 280 OBS source)")
            lbl.setObjectName("OverlayMockArtist")
            lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl)
        return f

    def _make_preview_fullscreen(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerFullscreen")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)
        badge = QLabel("BREAK")
        badge.setObjectName("OverlayMockBadge")
        badge.setAlignment(Qt.AlignCenter)
        big_time = QLabel("05:00")
        big_time.setObjectName("OverlayMockTitle")
        big_time.setAlignment(Qt.AlignCenter)
        sub = QLabel("Stream returns shortly")
        sub.setObjectName("OverlayMockArtist")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(badge)
        layout.addWidget(big_time)
        layout.addWidget(sub)
        return f

    def _make_preview_corner(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerCorner")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(16, 0, 16, 0)
        pill = QFrame()
        pill.setObjectName("OverlayMockCorner")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(12, 8, 16, 8)
        pill_layout.setSpacing(9)
        dot = QFrame()
        dot.setObjectName("OverlayMockDot")
        dot.setFixedSize(7, 7)
        body = QVBoxLayout()
        body.setSpacing(1)
        lbl = QLabel("TIMER")
        lbl.setObjectName("OverlayMockEQLabel")
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        body.addWidget(lbl)
        body.addWidget(time_lbl)
        pill_layout.addWidget(dot, 0, Qt.AlignVCenter)
        pill_layout.addLayout(body)
        layout.addStretch(1)
        layout.addWidget(pill, 0, Qt.AlignVCenter)
        return f

    def _make_preview_split(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerSplit")
        f.setFixedHeight(80)
        layout = QHBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QFrame()
        left.setObjectName("OverlayMockTicker")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 10, 16, 10)
        left_layout.setAlignment(Qt.AlignVCenter)
        lbl = QLabel("My Timer")
        lbl.setObjectName("OverlayMockEQLabel")
        mode_lbl = QLabel("Countdown")
        mode_lbl.setObjectName("OverlayMockArtist")
        left_layout.addWidget(lbl)
        left_layout.addWidget(mode_lbl)
        layout.addWidget(left, 1)

        sep = QFrame()
        sep.setObjectName("OverlayMockSep")
        sep.setFixedWidth(1)
        layout.addWidget(sep)

        right = QFrame()
        right.setObjectName("OverlayMockCard")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 10, 16, 10)
        right_layout.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_layout.addWidget(time_lbl)
        layout.addWidget(right, 1)

        return f

    def _make_preview_neon(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerNeon")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        time_lbl.setAlignment(Qt.AlignCenter)
        time_lbl.setStyleSheet(
            "QLabel { color: #bf7aed; font-size: 28px; font-weight: bold; "
            "letter-spacing: 4px; }"
        )
        label = QLabel("MY TIMER")
        label.setObjectName("OverlayMockEQLabel")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(time_lbl)
        layout.addWidget(label)
        return f

    def _make_preview_orbit(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerOrbit")
        f.setFixedHeight(130)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignCenter)
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            svg_data = _circle_preview_svg("7c3aed").encode()
            svg = QSvgWidget()
            svg.load(svg_data)
            svg.setFixedSize(110, 110)
            layout.addWidget(svg, 0, Qt.AlignCenter)
        except ImportError:
            lbl = QLabel("⟳  Orbit circle\n(280 × 280 OBS source)")
            lbl.setObjectName("OverlayMockArtist")
            lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl)
        return f

    def _make_preview_surge(self) -> QFrame:
        f = QFrame()
        f.setObjectName("OverlayMockTimerSurge")
        f.setFixedHeight(90)
        layout = QVBoxLayout(f)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        # Upper wave strip
        top_strip = QFrame()
        top_strip.setObjectName("OverlayMockSurgeWave")
        top_strip.setFixedHeight(28)
        layout.addWidget(top_strip)

        # Centre zone with time
        centre = QFrame()
        centre.setObjectName("OverlayMockCard")
        centre_layout = QHBoxLayout(centre)
        centre_layout.setContentsMargins(12, 4, 12, 4)
        time_lbl = QLabel("05:00")
        time_lbl.setObjectName("OverlayMockTitle")
        time_lbl.setAlignment(Qt.AlignCenter)
        label_lbl = QLabel("STARTING SOON")
        label_lbl.setObjectName("OverlayMockEQLabel")
        label_lbl.setAlignment(Qt.AlignCenter)
        centre_layout.addWidget(time_lbl)
        centre_layout.addWidget(label_lbl)
        layout.addWidget(centre, 1)

        # Lower wave strip
        bot_strip = QFrame()
        bot_strip.setObjectName("OverlayMockSurgeWave")
        bot_strip.setFixedHeight(28)
        layout.addWidget(bot_strip)

        return f

    # ── Overlay URL helpers ───────────────────────────────────────────────────

    def _overlay_url(self, path: str) -> str:
        base = self._overlay_base_url or f"http://localhost:{TIMER_OVERLAY_PORT}"
        params = []

        timers = self._engine.timers
        if timers:
            params.append(f"id={timers[0].timer_id}")

        accent = self._accent_edit.text().strip().lstrip("#") if hasattr(self, "_accent_edit") else self._ov_accent
        text = self._text_edit.text().strip().lstrip("#") if hasattr(self, "_text_edit") else self._ov_text

        if accent and accent != "7c3aed":
            params.append(f"accent={accent}")
        if text and text != "f0e6ff":
            params.append(f"text={text}")
        if self._ov_bg != 88:
            params.append(f"bg={self._ov_bg}")
        if self._ov_hide_after != 5:
            params.append(f"hide_after={self._ov_hide_after}")

        qs = ("?" + "&".join(params)) if params else ""
        suffix = "" if self._overlay_base_url else "  (overlay server not running)"
        return f"{base}{path}{qs}{suffix}"

    def _on_hide_after_changed(self, value: int) -> None:
        self._ov_hide_after = value
        self._refresh_overlay_urls()

    def _on_bg_opacity_changed(self, value: int) -> None:
        self._ov_bg = value
        self._bg_opacity_label.setText(f"Background Opacity  ({value}%)")
        self._push_theme()
        self._refresh_overlay_urls()

    def _on_overlay_param_changed(self) -> None:
        self._ov_accent = self._accent_edit.text().strip().lstrip("#")
        self._ov_text = self._text_edit.text().strip().lstrip("#")
        self._push_theme()
        self._refresh_overlay_urls()

    def _push_theme(self) -> None:
        if self._overlay_server is None:
            return
        self._overlay_server.push_theme(
            accent=self._ov_accent,
            text=self._ov_text,
            opacity=self._ov_bg,
        )

    def _refresh_overlay_urls(self) -> None:
        for lbl in self._ov_url_labels:
            path = lbl.property("_path")
            if path:
                lbl.setText(self._overlay_url(path))

    def closeEvent(self, event) -> None:
        self._engine.unsubscribe(self._on_engine_updated)
        super().closeEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# TIMER CARD
# ══════════════════════════════════════════════════════════════════════════════

class _TimerCard(QFrame):
    def __init__(self, timer: "Timer", engine: "TimerEngine", edit_callback) -> None:
        super().__init__()
        self.setObjectName("TimerCard")
        self._tid = timer.timer_id
        self._engine = engine
        self._edit_callback = edit_callback
        self._color = timer.color

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Coloured left border
        self._border_strip = QFrame()
        self._border_strip.setFixedWidth(5)
        self._border_strip.setObjectName("TimerCardBorder")
        root.addWidget(self._border_strip)

        body = QVBoxLayout()
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(8)

        # Header row: label + status badge + edit button
        header = QHBoxLayout()
        header.setSpacing(8)
        self._label_lbl = QLabel(timer.label)
        self._label_lbl.setObjectName("TimerCardLabel")
        self._status_badge = QLabel(_status_text(timer))
        self._status_badge.setObjectName("TimerStatusBadge")
        edit_btn = QPushButton("✎")
        edit_btn.setObjectName("TimerTransportBtn")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setToolTip("Edit timer")
        edit_btn.clicked.connect(self._on_edit)
        header.addWidget(self._label_lbl, 1)
        header.addWidget(self._status_badge)
        header.addWidget(edit_btn)
        body.addLayout(header)

        # Big time display
        self._time_lbl = QLabel(timer.display_time)
        self._time_lbl.setObjectName("TimerCardTime")
        body.addWidget(self._time_lbl)

        # Progress bar (track + fill)
        prog_track = QFrame()
        prog_track.setObjectName("TimerCardProgressTrack")
        prog_track.setFixedHeight(6)
        prog_inner = QHBoxLayout(prog_track)
        prog_inner.setContentsMargins(0, 0, 0, 0)
        prog_inner.setSpacing(0)
        self._prog_fill = QFrame()
        self._prog_fill.setObjectName("TimerCardProgress")
        self._prog_remainder = QFrame()
        self._prog_remainder.setObjectName("TimerCardProgressEmpty")
        prog_inner.addWidget(self._prog_fill, 0)
        prog_inner.addWidget(self._prog_remainder, 100)
        self._prog_inner = prog_inner
        body.addWidget(prog_track)

        # Transport buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._play_btn = QPushButton("▶  Start")
        self._play_btn.setObjectName("TimerPlayBtn")
        self._play_btn.clicked.connect(self._on_play_pause)
        self._reset_btn = QPushButton("↺  Reset")
        self._reset_btn.setObjectName("TimerTransportBtn")
        self._reset_btn.clicked.connect(lambda: engine.reset(self._tid))
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setObjectName("TimerTransportBtn")
        self._stop_btn.clicked.connect(lambda: engine.stop(self._tid))
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setObjectName("TimerDangerBtn")
        self._remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._remove_btn)
        body.addLayout(btn_row)

        root.addLayout(body, 1)
        self._apply_color(timer.color)
        self.refresh(timer)

    def refresh(self, timer: "Timer") -> None:
        from stream_controller.plugins.timer_manager.timer_models import TimerStatus
        self._label_lbl.setText(timer.label)
        self._time_lbl.setText(timer.display_time)
        self._status_badge.setText(_status_text(timer))

        is_running = timer.status == TimerStatus.RUNNING
        self._play_btn.setText("⏸  Pause" if is_running else "▶  Start")

        # Update progress bar proportions
        pct = int(timer.progress * 100)
        pct = max(0, min(100, pct))
        self._prog_inner.setStretch(0, pct)
        self._prog_inner.setStretch(1, max(1, 100 - pct))

        if timer.color != self._color:
            self._color = timer.color
            self._apply_color(timer.color)

    def _apply_color(self, hex_color: str) -> None:
        color = f"#{hex_color}"
        self._border_strip.setStyleSheet(
            f"QFrame {{ background: {color}; border-radius: 3px; }}"
        )
        self._prog_fill.setStyleSheet(
            f"QFrame {{ background: {color}; }}"
        )

    def _on_play_pause(self) -> None:
        self._engine.toggle(self._tid)

    def _on_edit(self) -> None:
        t = self._engine.get(self._tid)
        if t:
            self._edit_callback(t)

    def _on_remove(self) -> None:
        self._engine.remove_timer(self._tid)


# ══════════════════════════════════════════════════════════════════════════════
# NEW / EDIT TIMER DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class _TimerDialog(QDialog):
    def __init__(self, parent: QWidget, timer: "Timer | None" = None) -> None:
        super().__init__(parent)
        self._timer = timer
        self._picked_color = timer.color if timer else "7c3aed"

        self.setWindowTitle("Edit Timer" if timer else "New Timer")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        from PySide6.QtWidgets import QFormLayout
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Label
        self._label_edit = QLineEdit(timer.label if timer else "")
        self._label_edit.setObjectName("OverlayTextField")
        self._label_edit.setPlaceholderText("e.g. Intro countdown")
        form.addRow("Label", self._label_edit)

        # Mode
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Countdown", "countdown")
        self._mode_combo.addItem("Count Up", "countup")
        if timer:
            idx = self._mode_combo.findData(timer.mode.value)
            if idx >= 0:
                self._mode_combo.setCurrentIndex(idx)
        form.addRow("Mode", self._mode_combo)

        # Duration
        dur_widget = QWidget()
        dur_row = QHBoxLayout(dur_widget)
        dur_row.setContentsMargins(0, 0, 0, 0)
        dur_row.setSpacing(6)
        total_secs = int(timer.duration) if timer else 300
        h, rem = divmod(total_secs, 3600)
        m, s = divmod(rem, 60)
        self._hours_spin = QSpinBox()
        self._hours_spin.setRange(0, 99)
        self._hours_spin.setSuffix(" h")
        self._hours_spin.setValue(h)
        self._mins_spin = QSpinBox()
        self._mins_spin.setRange(0, 59)
        self._mins_spin.setSuffix(" m")
        self._mins_spin.setValue(m)
        self._secs_spin = QSpinBox()
        self._secs_spin.setRange(0, 59)
        self._secs_spin.setSuffix(" s")
        self._secs_spin.setValue(s)
        dur_row.addWidget(self._hours_spin)
        dur_row.addWidget(self._mins_spin)
        dur_row.addWidget(self._secs_spin)
        dur_row.addStretch(1)
        form.addRow("Duration", dur_widget)

        # Color picker
        color_widget = QWidget()
        color_row = QHBoxLayout(color_widget)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(8)
        self._color_swatch = QPushButton()
        self._color_swatch.setObjectName("ColorSwatch")
        self._color_swatch.setFixedSize(32, 32)
        self._color_swatch.setToolTip("Click to pick a colour")
        self._color_edit = QLineEdit(self._picked_color)
        self._color_edit.setObjectName("OverlayTextField")
        self._color_edit.setMaximumWidth(90)
        self._color_edit.setPlaceholderText("7c3aed")
        self._apply_color_to_swatch(self._picked_color)
        self._color_swatch.clicked.connect(self._pick_color)
        self._color_edit.textChanged.connect(self._on_color_text_changed)
        color_row.addWidget(self._color_swatch)
        color_row.addWidget(self._color_edit)
        color_row.addStretch(1)
        form.addRow("Color", color_widget)

        # End message
        self._end_msg_edit = QLineEdit(timer.end_message if timer else "Time's up!")
        self._end_msg_edit.setObjectName("OverlayTextField")
        self._end_msg_edit.setPlaceholderText("Time's up!")
        form.addRow("End Message", self._end_msg_edit)

        # Loop checkbox
        self._loop_cb = QCheckBox("Loop (restart when finished)")
        self._loop_cb.setObjectName("OverlayCheckBox")
        if timer:
            self._loop_cb.setChecked(timer.loop)
        form.addRow("", self._loop_cb)

        layout.addLayout(form)

        hint = QLabel("Duration is ignored for open-ended Count Up timers (leave at 0 to run indefinitely, or set a target for a progress bar).")
        hint.setObjectName("MetaText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _apply_color_to_swatch(self, hex_str: str) -> None:
        color = QColor(f"#{hex_str.strip().lstrip('#')}")
        if color.isValid():
            self._color_swatch.setStyleSheet(
                f"QPushButton#ColorSwatch {{ background:{color.name()}; "
                f"border:2px solid rgba(255,255,255,0.18); border-radius:6px; }}"
                f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.4); }}"
            )

    def _pick_color(self) -> None:
        current = QColor(f"#{self._picked_color}")
        color = QColorDialog.getColor(
            current if current.isValid() else QColor("#7c3aed"),
            self,
            "Choose Timer Colour",
        )
        if color.isValid():
            hex_val = color.name().lstrip("#")
            self._picked_color = hex_val
            self._color_edit.blockSignals(True)
            self._color_edit.setText(hex_val)
            self._color_edit.blockSignals(False)
            self._apply_color_to_swatch(hex_val)

    def _on_color_text_changed(self, text: str) -> None:
        clean = text.strip().lstrip("#")
        self._picked_color = clean
        self._apply_color_to_swatch(clean)

    def result_data(self) -> dict:
        from stream_controller.plugins.timer_manager.timer_models import TimerMode
        mode_val = self._mode_combo.currentData()
        mode = TimerMode.COUNTDOWN if mode_val == "countdown" else TimerMode.COUNTUP
        duration = (
            self._hours_spin.value() * 3600
            + self._mins_spin.value() * 60
            + self._secs_spin.value()
        )
        return {
            "label": self._label_edit.text().strip() or "Timer",
            "mode": mode,
            "duration": float(duration),
            "color": self._picked_color or "7c3aed",
            "end_message": self._end_msg_edit.text().strip() or "Time's up!",
            "loop": self._loop_cb.isChecked(),
        }


# ── helpers ───────────────────────────────────────────────────────────────────

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("MusicFieldLabel")
    return lbl


def _color_picker_row(edit: QLineEdit, swatch: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(swatch)
    row.addWidget(edit)
    return row


def _status_text(timer: "Timer") -> str:
    labels = {
        "idle":     "Idle",
        "running":  "Running",
        "paused":   "Paused",
        "finished": "Finished",
    }
    return labels.get(timer.status.value, timer.status.value.title())


def _circle_preview_svg(accent_hex: str) -> str:
    import math
    accent = f"#{accent_hex}"
    total = 10
    gap = 3.0
    seg = (360 - total * gap) / total

    def px(deg, r):
        return 55 + r * math.cos(math.radians(deg))

    def py(deg, r):
        return 55 + r * math.sin(math.radians(deg))

    def arc_path(start, sweep, r):
        end = start + sweep
        x1, y1 = px(start, r), py(start, r)
        x2, y2 = px(end, r), py(end, r)
        large = 1 if sweep > 180 else 0
        return f"M{x1:.2f},{y1:.2f} A{r},{r} 0 {large},1 {x2:.2f},{y2:.2f}"

    paths = ""
    filled = 6  # show 60% progress in preview
    for i in range(total):
        s = -90 + i * (seg + gap)
        d = arc_path(s, seg, 46)
        color = accent if i < filled else "#1a1a2e"
        paths += f'<path d="{d}" stroke="{color}" stroke-width="7" fill="none"/>\n'

    inner_d = arc_path(-90, 360 * 0.6, 36)
    inner_bg = arc_path(-90, 359.9, 36)
    return f'''<svg viewBox="0 0 110 110" xmlns="http://www.w3.org/2000/svg">
{paths}
<path d="{inner_bg}" stroke="#1a1a2e" stroke-width="5" fill="none"/>
<path d="{inner_d}" stroke="{accent}" stroke-width="5" fill="none" stroke-linecap="round"/>
<text x="55" y="50" text-anchor="middle" font-size="9" font-weight="bold" fill="#e8d5ff">05:00</text>
<text x="55" y="63" text-anchor="middle" font-size="7" fill="rgba(180,120,237,0.7)">My Timer</text>
</svg>'''
