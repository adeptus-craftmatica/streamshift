from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.macro_manager.macro_engine import MacroEngine
    from stream_controller.plugins.macro_manager.macro_models import MacroExecutionRecord

_MAX_ENTRIES = 50


class MacroLogCard(QFrame):
    def __init__(self, engine: MacroEngine) -> None:
        super().__init__()
        self._engine = engine
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)
        root.setAlignment(Qt.AlignTop)

        # Header row
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Macro Log")
        title.setObjectName("CardTitle")
        header.addWidget(title, 1)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("TimerMiniBtn")
        clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)
        root.addLayout(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._log_container = QWidget()
        self._log_layout = QVBoxLayout(self._log_container)
        self._log_layout.setContentsMargins(0, 0, 0, 0)
        self._log_layout.setSpacing(6)
        self._log_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self._log_container)
        root.addWidget(scroll, 1)

        # Placeholder
        self._placeholder = QLabel("No macros have run yet.")
        self._placeholder.setObjectName("CardDescription")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._log_layout.addWidget(self._placeholder)

        engine.execution_finished.connect(self._on_execution_finished)
        self.destroyed.connect(self._on_destroyed)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_execution_finished(self, record: MacroExecutionRecord) -> None:
        self._ensure_placeholder_hidden()

        entry = _LogEntry(record, self._engine)
        self._log_layout.insertWidget(0, entry)

        # Enforce max entries (count excludes placeholder which is hidden)
        self._trim_to_limit()

    def _on_clear(self) -> None:
        while self._log_layout.count():
            item = self._log_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._placeholder = QLabel("No macros have run yet.")
        self._placeholder.setObjectName("CardDescription")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._log_layout.addWidget(self._placeholder)

    def _on_destroyed(self) -> None:
        try:
            self._engine.execution_finished.disconnect(self._on_execution_finished)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_placeholder_hidden(self) -> None:
        if self._placeholder is not None and self._placeholder.isVisible():
            self._placeholder.setVisible(False)

    def _trim_to_limit(self) -> None:
        entries = []
        for i in range(self._log_layout.count()):
            w = self._log_layout.itemAt(i).widget()
            if isinstance(w, _LogEntry):
                entries.append(w)

        while len(entries) > _MAX_ENTRIES:
            oldest = entries.pop()
            self._log_layout.removeWidget(oldest)
            oldest.deleteLater()


class _LogEntry(QFrame):
    def __init__(self, record: MacroExecutionRecord, engine: MacroEngine) -> None:
        super().__init__()
        self._engine = engine
        self._macro_id = record.macro_id
        self.setObjectName("TimerTileRow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.setSpacing(0)

        # Left colored stripe
        stripe = QFrame()
        stripe.setFixedWidth(4)
        color = "#4ade80" if record.success else "#f87171"
        stripe.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        outer.addWidget(stripe)

        # Content area
        content = QVBoxLayout()
        content.setContentsMargins(10, 6, 0, 6)
        content.setSpacing(2)
        outer.addLayout(content, 1)

        # Top row: name + re-run button
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        name_lbl = QLabel(record.macro_name)
        name_lbl.setObjectName("TimerTileLabel")
        name_lbl.setStyleSheet("font-weight: bold;")
        top_row.addWidget(name_lbl, 1)

        rerun_btn = QPushButton("▶ Re-run")
        rerun_btn.setObjectName("TimerMiniBtn")
        rerun_btn.setFixedHeight(22)
        rerun_btn.clicked.connect(self._on_rerun)
        top_row.addWidget(rerun_btn)

        content.addLayout(top_row)

        # Meta row: timestamp · steps · duration
        ts = datetime.datetime.fromtimestamp(record.started_at).strftime("%H:%M:%S")
        duration = ""
        if record.finished_at is not None:
            duration = f" · {record.finished_at - record.started_at:.1f}s"
        meta_text = (
            f"{ts} · {record.steps_completed}/{record.total_steps} steps{duration}"
        )
        meta_lbl = QLabel(meta_text)
        meta_lbl.setObjectName("CardDescription")
        content.addWidget(meta_lbl)

        # Error row
        if record.error:
            truncated = record.error[:80] + ("…" if len(record.error) > 80 else "")
            err_lbl = QLabel(truncated)
            err_lbl.setObjectName("CardDescription")
            err_lbl.setStyleSheet("color: #f87171;")
            err_lbl.setWordWrap(True)
            content.addWidget(err_lbl)

    def _on_rerun(self) -> None:
        try:
            self._engine.run_macro(self._macro_id)
        except Exception:
            pass
