from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

from stream_controller.plugins.stream_health.health_poller import HealthPoller


class HealthTile(QFrame):
    """Stage panel tile: OBS connection badge + key health stats."""

    _stats_ready = Signal(dict)

    def __init__(self, poller: HealthPoller) -> None:
        super().__init__()
        self._poller = poller

        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Title
        title = QLabel("Stream Health")
        title.setObjectName("CardTitle")
        root.addWidget(title)

        # Status badge
        self._badge = QLabel("⚫  OBS Disconnected")
        self._badge.setObjectName("LiveBadge")
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            "font-size:14px;font-weight:700;color:#64748b;"
            "padding:4px 10px;border-radius:8px;"
            "background:rgba(100,116,139,0.12);"
        )
        root.addWidget(self._badge)

        # Stat rows: (label text, attribute name, color)
        self._fps_val  = self._make_row(root, "FPS",            "#22c55e")
        self._cpu_val  = self._make_row(root, "CPU",            "#38bdf8")
        self._drop_val = self._make_row(root, "Dropped",        "#f59e0b")
        self._dur_val  = self._make_row(root, "Duration",       "#a78bfa")

        root.addStretch(1)

        self._stats_ready.connect(self._apply_stats)
        poller.add_listener(self._on_stats_bg)
        self.destroyed.connect(self._on_destroyed)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_row(layout: QVBoxLayout, name: str, color: str) -> QLabel:
        row = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setObjectName("MetaText")
        val_lbl = QLabel("—")
        val_lbl.setObjectName("MetricValue")
        val_lbl.setStyleSheet(f"color:{color};font-size:14px;font-weight:700;")
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(name_lbl, 1)
        row.addWidget(val_lbl)
        layout.addLayout(row)
        return val_lbl

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_stats_bg(self, stats: dict) -> None:
        self._stats_ready.emit(stats)

    def _apply_stats(self, d: dict) -> None:
        connected = d.get("connected", False)

        if not connected:
            self._badge.setText("⚫  OBS Disconnected")
            self._badge.setStyleSheet(
                "font-size:14px;font-weight:700;color:#64748b;"
                "padding:4px 10px;border-radius:8px;"
                "background:rgba(100,116,139,0.12);"
            )
            for lbl in (self._fps_val, self._cpu_val, self._drop_val, self._dur_val):
                lbl.setText("—")
            return

        streaming = d.get("streaming", False)
        if streaming:
            self._badge.setText("🔴  LIVE")
            self._badge.setStyleSheet(
                "font-size:14px;font-weight:700;color:#ffffff;"
                "padding:4px 10px;border-radius:8px;"
                "background:rgba(34,197,94,0.25);"
            )
        else:
            self._badge.setText("🟢  OBS Connected")
            self._badge.setStyleSheet(
                "font-size:14px;font-weight:700;color:#22c55e;"
                "padding:4px 10px;border-radius:8px;"
                "background:rgba(34,197,94,0.12);"
            )

        fps = d.get("fps", 0.0)
        fps_color = "#22c55e" if fps >= 59 else ("#f59e0b" if fps >= 55 else "#ef4444")
        self._fps_val.setStyleSheet(f"color:{fps_color};font-size:14px;font-weight:700;")
        self._fps_val.setText(f"{fps:.1f}")

        cpu = d.get("cpu_usage", 0.0)
        cpu_color = "#22c55e" if cpu < 50 else ("#f59e0b" if cpu < 75 else "#ef4444")
        self._cpu_val.setStyleSheet(f"color:{cpu_color};font-size:14px;font-weight:700;")
        self._cpu_val.setText(f"{cpu:.1f}%")

        pct = d.get("dropped_pct", 0.0)
        drop_color = "#22c55e" if pct < 0.1 else ("#f59e0b" if pct < 1.0 else "#ef4444")
        self._drop_val.setStyleSheet(f"color:{drop_color};font-size:14px;font-weight:700;")
        self._drop_val.setText(f"{pct:.2f}%")

        ms = d.get("stream_duration_ms", 0)
        total_s = ms // 1000
        h = total_s // 3600
        m = (total_s % 3600) // 60
        s = total_s % 60
        dur_str = f"{h}:{m:02d}:{s:02d}" if streaming else "—"
        self._dur_val.setText(dur_str)

    # ── cleanup ───────────────────────────────────────────────────────────────

    def _on_destroyed(self) -> None:
        self._poller.remove_listener(self._on_stats_bg)
