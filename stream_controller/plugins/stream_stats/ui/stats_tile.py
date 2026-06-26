from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.plugins.stream_stats.stats_engine import StatsEngine
    from stream_controller.plugins.stream_stats.stats_models import LiveStats


class StatsTile(QFrame):
    """Compact stats tile for dashboard and Stage View."""

    def __init__(self, engine: "StatsEngine") -> None:
        super().__init__()
        self._engine = engine
        self.setObjectName("StatsTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("Stream Stats")
        title.setObjectName("CardTitle")
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b;")
        header.addWidget(title, 1)
        header.addWidget(self._dot)
        root.addLayout(header)

        # Stats grid
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)

        self._labels: dict[str, QLabel] = {}
        rows = [
            ("total_followers",  "Total Followers", "#22c55e"),
            ("followers_gained", "Gained",          "#7c3aed"),
            ("bits_donated",     "Bits",            "#f59e0b"),
            ("new_subs",         "Subs",            "#ec4899"),
            ("gifted_subs",      "Gifted Subs",     "#38bdf8"),
        ]
        for i, (key, lbl, color) in enumerate(rows):
            name_lbl = QLabel(lbl)
            name_lbl.setObjectName("MetaText")
            val_lbl = QLabel("–")
            val_lbl.setObjectName("MetricValue")
            val_lbl.setStyleSheet(f"color:{color};font-size:16px;font-weight:700;")
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(name_lbl, i, 0)
            grid.addWidget(val_lbl,  i, 1)
            self._labels[key] = val_lbl

        root.addLayout(grid)

        # Latest follower
        self._latest = QLabel("No followers yet")
        self._latest.setObjectName("CardDescription")
        self._latest.setWordWrap(True)
        root.addWidget(self._latest)

        # Session buttons
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start Session")
        self._start_btn.setObjectName("PrimaryButton")
        self._start_btn.clicked.connect(self._start)
        self._end_btn = QPushButton("End Session")
        self._end_btn.setObjectName("SecondaryButton")
        self._end_btn.clicked.connect(self._end)
        self._end_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._end_btn)
        root.addLayout(btn_row)

        self._state_cb = self._on_stats
        engine.subscribe(self._state_cb)
        self._on_stats(engine.live)
        self.destroyed.connect(self._on_destroyed)

    def _on_stats(self, stats: "LiveStats") -> None:
        from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus
        dot_colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color:{dot_colors.get(stats.status, '#64748b')};")

        self._labels["total_followers"].setText(f"{stats.total_followers:,}")
        self._labels["followers_gained"].setText(f"+{stats.followers_gained:,}")
        self._labels["bits_donated"].setText(f"{stats.bits_donated:,}")
        self._labels["new_subs"].setText(str(stats.new_subs))
        self._labels["gifted_subs"].setText(str(stats.gifted_subs))

        if stats.latest_follower:
            self._latest.setText(f"Latest: {stats.latest_follower}")

        active = stats.session_active
        self._start_btn.setEnabled(not active)
        self._end_btn.setEnabled(active)

    def _start(self) -> None:
        self._engine.start_session()

    def _end(self) -> None:
        self._engine.end_session()

    def _on_destroyed(self) -> None:
        if self._engine and self._state_cb:
            self._engine.unsubscribe(self._state_cb)
