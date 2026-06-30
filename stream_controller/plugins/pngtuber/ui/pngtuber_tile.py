from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.plugins.pngtuber.plugin import PngTuberPlugin


class PngTuberTile(QFrame):
    def __init__(self, plugin: "PngTuberPlugin") -> None:
        super().__init__()
        self._plugin = plugin
        self._last_state = ""
        self._last_img_path = ""

        self.setObjectName("SceneTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("PNGtuber")
        title.setObjectName("CardTitle")
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b;")
        header.addWidget(title, 1)
        header.addWidget(self._dot)
        root.addLayout(header)

        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setFixedSize(160, 160)
        self._preview.setStyleSheet(
            "background:#0d1117; border:1px solid #1e293b; border-radius:4px;"
        )
        self._preview.setText("No image")
        root.addWidget(self._preview, 0, Qt.AlignHCenter)

        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setValue(0)
        self._level_bar.setTextVisible(False)
        self._level_bar.setFixedHeight(6)
        root.addWidget(self._level_bar)

        self._state_lbl = QLabel("Idle")
        self._state_lbl.setObjectName("MetaText")
        root.addWidget(self._state_lbl)

        self._expr_lbl = QLabel("")
        self._expr_lbl.setObjectName("CardDescription")
        root.addWidget(self._expr_lbl)

        self._toggle_btn = QPushButton("Start")
        self._toggle_btn.setObjectName("PrimaryButton")
        self._toggle_btn.clicked.connect(self._toggle)
        root.addWidget(self._toggle_btn)

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _toggle(self) -> None:
        st = self._plugin.get_state()
        if st["running"]:
            self._plugin.stop()
        else:
            self._plugin.start()

    def _refresh(self) -> None:
        st = self._plugin.get_state()
        running = st["running"]
        state = st["state"]
        expression = st["expression"]
        level = st["level"]

        self._dot.setStyleSheet(f"color:{'#22c55e' if running else '#64748b'};")
        self._toggle_btn.setText("Stop" if running else "Start")
        self._toggle_btn.setObjectName("SecondaryButton" if running else "PrimaryButton")

        label_map = {
            "idle": "Idle",
            "talking": "Talking",
            "idle_blink": "Blinking",
            "talking_blink": "Talking + Blink",
        }
        self._state_lbl.setText(label_map.get(state, state.capitalize()))
        self._expr_lbl.setText(expression)
        self._level_bar.setValue(int(level * 100))

        self._update_preview(expression, state)

    def _update_preview(self, expression: str, state: str) -> None:
        repo = self._plugin._repo
        if not repo:
            return
        layers = repo.get_expression(expression)
        layer_order = [state, "idle"]
        img_path = ""
        for layer in layer_order:
            p = layers.get(layer, "")
            if p and Path(p).exists():
                img_path = p
                break

        if img_path == self._last_img_path:
            return
        self._last_img_path = img_path

        if img_path:
            pix = QPixmap(img_path)
            if not pix.isNull():
                scaled = pix.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._preview.setPixmap(scaled)
                return
        self._preview.setPixmap(QPixmap())
        self._preview.setText("No image")
