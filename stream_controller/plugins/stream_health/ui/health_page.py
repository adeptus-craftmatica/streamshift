from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _color_style(color: str) -> str:
    return f"color: {color}; font-size: 28px; font-weight: bold;"


def _duration_str(ms: int) -> str:
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _stat_card(value_text: str, description: str) -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("CardFrame")
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(4)

    value_label = QLabel(value_text)
    value_label.setStyleSheet(_color_style("#ffffff"))
    value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    desc_label = QLabel(description)
    desc_label.setObjectName("CardDescription")
    desc_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    layout.addWidget(value_label)
    layout.addWidget(desc_label)

    return frame, value_label, desc_label


class HealthPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(16)

        # ── header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(12)

        title = QLabel("Stream Health Monitor")
        title.setObjectName("PageTitle")

        self._status_badge = QLabel("OBS Disconnected")
        self._status_badge.setAlignment(Qt.AlignCenter)
        self._status_badge.setFixedHeight(24)
        self._status_badge.setStyleSheet(
            "background: #ef4444; color: white; border-radius: 8px; padding: 2px 10px; font-size: 12px;"
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._status_badge)
        root_layout.addLayout(header)

        # ── error label ───────────────────────────────────────────────────────
        self._error_label = QLabel("")
        self._error_label.setObjectName("CardDescription")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root_layout.addWidget(self._error_label)

        # ── scroll area holding the grid ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Row 0
        self._live_card, self._live_value, self._live_desc = _stat_card("⚫ OFFLINE", "Live Status")
        grid.addWidget(self._live_card, 0, 0)

        self._fps_card, self._fps_value, self._fps_desc = _stat_card("--", "Frames Per Second")
        grid.addWidget(self._fps_card, 0, 1)

        self._cpu_card, self._cpu_value, self._cpu_desc = _stat_card("--", "CPU Usage")
        grid.addWidget(self._cpu_card, 0, 2)

        # Row 1
        self._drop_card, self._drop_value, self._drop_desc = _stat_card("--", "Dropped Frames")
        grid.addWidget(self._drop_card, 1, 0)

        self._render_card, self._render_value, self._render_desc = _stat_card("--", "Render Time (ms)")
        grid.addWidget(self._render_card, 1, 1)

        self._mem_card, self._mem_value, self._mem_desc = _stat_card("--", "Memory Usage")
        grid.addWidget(self._mem_card, 1, 2)

        # Row 2
        self._bitrate_card, self._bitrate_value, self._bitrate_desc = _stat_card("--", "Estimated Bitrate")
        grid.addWidget(self._bitrate_card, 2, 0)

        # Frame health spans 2 columns
        fh_frame = QFrame()
        fh_frame.setObjectName("CardFrame")
        fh_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fh_layout = QVBoxLayout(fh_frame)
        fh_layout.setContentsMargins(16, 16, 16, 16)
        fh_layout.setSpacing(8)

        fh_title = QLabel("Frame Health")
        fh_title.setObjectName("CardDescription")

        self._frame_bar = QProgressBar()
        self._frame_bar.setRange(0, 100)
        self._frame_bar.setValue(0)
        self._frame_bar.setTextVisible(True)
        self._frame_bar.setFormat("%p%")
        self._frame_bar.setFixedHeight(20)

        self._frame_bar_desc = QLabel("0 / 0 frames")
        self._frame_bar_desc.setObjectName("CardDescription")

        fh_layout.addWidget(fh_title)
        fh_layout.addWidget(self._frame_bar)
        fh_layout.addWidget(self._frame_bar_desc)

        grid.addWidget(fh_frame, 2, 1, 1, 2)

        grid_container.setLayout(grid)
        scroll.setWidget(grid_container)
        root_layout.addWidget(scroll)

    # ── public ────────────────────────────────────────────────────────────────

    def update_stats(self, d: dict) -> None:
        connected = d.get("connected", False)

        if not connected:
            self._set_disconnected(d.get("error"))
            return

        # Connection badge
        self._status_badge.setText("OBS Connected")
        self._status_badge.setStyleSheet(
            "background: #22c55e; color: white; border-radius: 8px; padding: 2px 10px; font-size: 12px;"
        )
        self._error_label.setVisible(False)

        streaming = d.get("streaming", False)
        duration_ms = d.get("stream_duration_ms", 0) or 0

        # Live status
        if streaming:
            self._live_value.setText(f"🔴 LIVE\n{_duration_str(duration_ms)}")
            self._live_value.setStyleSheet(_color_style("#ef4444"))
        else:
            self._live_value.setText("⚫ OFFLINE")
            self._live_value.setStyleSheet(_color_style("#9ca3af"))

        # FPS
        fps = d.get("fps", 0.0) or 0.0
        if fps >= 59:
            fps_color = "#22c55e"
        elif fps >= 55:
            fps_color = "#f59e0b"
        else:
            fps_color = "#ef4444"
        self._fps_value.setText(f"{fps:.1f}")
        self._fps_value.setStyleSheet(_color_style(fps_color))

        # CPU
        cpu = d.get("cpu_usage", 0.0) or 0.0
        if cpu < 50:
            cpu_color = "#22c55e"
        elif cpu < 75:
            cpu_color = "#f59e0b"
        else:
            cpu_color = "#ef4444"
        self._cpu_value.setText(f"{cpu:.1f}%")
        self._cpu_value.setStyleSheet(_color_style(cpu_color))

        # Dropped frames
        dropped = d.get("dropped_frames", 0) or 0
        dropped_pct = d.get("dropped_pct", 0.0) or 0.0
        if dropped_pct < 0.1:
            drop_color = "#22c55e"
        elif dropped_pct < 1.0:
            drop_color = "#f59e0b"
        else:
            drop_color = "#ef4444"
        self._drop_value.setText(f"{dropped:,}")
        self._drop_value.setStyleSheet(_color_style(drop_color))
        self._drop_desc.setText(f"Dropped Frames ({dropped_pct:.2f}%)")

        # Render time
        render_ms = d.get("render_time_ms", 0.0) or 0.0
        if render_ms < 8:
            render_color = "#22c55e"
        elif render_ms < 16:
            render_color = "#f59e0b"
        else:
            render_color = "#ef4444"
        self._render_value.setText(f"{render_ms:.1f}")
        self._render_value.setStyleSheet(_color_style(render_color))

        # Memory
        mem_mb = d.get("memory_mb", 0.0) or 0.0
        self._mem_value.setText(f"{mem_mb:.0f} MB")
        self._mem_value.setStyleSheet(_color_style("#ffffff"))

        # Bitrate
        output_bytes = d.get("output_bytes", 0) or 0
        if streaming and duration_ms > 0:
            bitrate_kbps = output_bytes * 8 / (duration_ms / 1000) / 1000
            self._bitrate_value.setText(f"{bitrate_kbps:.0f} kbps")
        else:
            self._bitrate_value.setText("--")
        self._bitrate_value.setStyleSheet(_color_style("#ffffff"))

        # Frame health bar
        total = d.get("total_frames", 0) or 0
        good = total - dropped
        if total > 0:
            pct = max(0, min(100, int(good / total * 100)))
        else:
            pct = 0
        self._frame_bar.setValue(pct)
        self._frame_bar_desc.setText(f"{good:,} / {total:,} frames rendered")

        if pct >= 99:
            bar_color = "#22c55e"
        elif pct >= 95:
            bar_color = "#f59e0b"
        else:
            bar_color = "#ef4444"
        self._frame_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {bar_color}; border-radius: 4px; }}"
            "QProgressBar { border-radius: 4px; text-align: center; }"
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _set_disconnected(self, error: str | None) -> None:
        self._status_badge.setText("OBS Disconnected")
        self._status_badge.setStyleSheet(
            "background: #ef4444; color: white; border-radius: 8px; padding: 2px 10px; font-size: 12px;"
        )

        if error:
            self._error_label.setText(error)
            self._error_label.setVisible(True)
        else:
            self._error_label.setVisible(False)

        placeholder_style = _color_style("#6b7280")
        for lbl in (
            self._live_value, self._fps_value, self._cpu_value,
            self._drop_value, self._render_value, self._mem_value,
            self._bitrate_value,
        ):
            lbl.setText("--")
            lbl.setStyleSheet(placeholder_style)

        self._live_value.setText("⚫ OFFLINE")
        self._drop_desc.setText("Dropped Frames")
        self._frame_bar.setValue(0)
        self._frame_bar_desc.setText("-- / -- frames")
        self._frame_bar.setStyleSheet("")
