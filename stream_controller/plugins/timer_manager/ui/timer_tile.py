from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.plugins.timer_manager.timer_engine import TimerEngine
    from stream_controller.plugins.timer_manager.timer_models import Timer


class TimerTile(QFrame):
    """Compact deck tile showing all timers with quick controls."""

    def __init__(self, engine: "TimerEngine") -> None:
        super().__init__()
        self._engine = engine
        self.setObjectName("TimerTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Timers")
        title.setObjectName("CardTitle")
        header.addWidget(title, 1)
        root.addLayout(header)

        self._rows_container = QVBoxLayout()
        self._rows_container.setSpacing(6)
        root.addLayout(self._rows_container, 1)

        self.destroyed.connect(self._on_destroyed)
        self._engine.subscribe(self._on_updated)
        self._on_updated(self._engine.timers)

    def _on_updated(self, timers: list) -> None:
        # Clear existing rows
        while self._rows_container.count():
            item = self._rows_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for t in timers[:5]:
            row = _TimerRow(t, self._engine)
            self._rows_container.addWidget(row)

        if not timers:
            empty = QLabel("No timers — open Timer Manager to create one.")
            empty.setObjectName("CardDescription")
            empty.setWordWrap(True)
            self._rows_container.addWidget(empty)

    def _on_destroyed(self) -> None:
        self._engine.unsubscribe(self._on_updated)


class _TimerRow(QFrame):
    def __init__(self, timer, engine: "TimerEngine") -> None:
        super().__init__()
        self.setObjectName("TimerTileRow")
        self._tid = timer.timer_id
        self._engine = engine

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setObjectName("TimerStatusDot")
        self._dot.setFixedWidth(12)
        self._label = QLabel(timer.label)
        self._label.setObjectName("TimerTileLabel")
        self._time = QLabel(timer.display_time)
        self._time.setObjectName("TimerTileTime")
        self._time.setFixedWidth(56)
        self._time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        play_btn = QPushButton("▶")
        play_btn.setObjectName("TimerMiniBtn")
        play_btn.setFixedSize(24, 24)
        play_btn.clicked.connect(lambda: engine.toggle(self._tid))

        reset_btn = QPushButton("↺")
        reset_btn.setObjectName("TimerMiniBtn")
        reset_btn.setFixedSize(24, 24)
        reset_btn.clicked.connect(lambda: engine.reset(self._tid))

        row.addWidget(self._dot)
        row.addWidget(self._label, 1)
        row.addWidget(self._time)
        row.addWidget(play_btn)
        row.addWidget(reset_btn)

        self._refresh(timer)

    def _refresh(self, timer) -> None:
        colors = {"running": "#22c55e", "paused": "#f59e0b",
                  "idle": "#64748b", "finished": "#ef4444"}
        self._dot.setStyleSheet(f"color:{colors.get(timer.status.value,'#64748b')};")
        self._time.setText(timer.display_time)
