from __future__ import annotations

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


class MacroTile(QFrame):
    def __init__(self, macro_id: str, engine: MacroEngine) -> None:
        super().__init__()
        self._macro_id = macro_id
        self._engine = engine
        self.setObjectName("MacroTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self._header_lbl = QLabel()
        self._header_lbl.setObjectName("CardTitle")
        root.addWidget(self._header_lbl)

        self._step_lbl = QLabel()
        self._step_lbl.setObjectName("CardDescription")
        root.addWidget(self._step_lbl)

        self._hotkey_lbl = QLabel()
        self._hotkey_lbl.setObjectName("TimerStatusBadge")
        self._hotkey_lbl.setVisible(False)
        root.addWidget(self._hotkey_lbl)

        self._run_btn = QPushButton("▶  Run")
        self._run_btn.setObjectName("PrimaryButton")
        self._run_btn.clicked.connect(self._on_run)
        root.addWidget(self._run_btn)

        self._engine.macro_started.connect(self._on_macro_started)
        self._engine.macro_finished.connect(self._on_macro_finished)
        self.destroyed.connect(self._on_destroyed)

        self._refresh()

    def _refresh(self) -> None:
        macro = self._engine.repo.get_macro(self._macro_id)
        if macro is None:
            self._header_lbl.setText("(deleted)")
            return
        self._header_lbl.setText(f"{macro.icon}  {macro.name}")
        count = len(macro.steps)
        self._step_lbl.setText(f"{count} step{'s' if count != 1 else ''}")
        if macro.hotkey:
            self._hotkey_lbl.setText(macro.hotkey)
            self._hotkey_lbl.setVisible(True)
        else:
            self._hotkey_lbl.setVisible(False)

    def _on_run(self) -> None:
        self._engine.run_macro(self._macro_id)

    def _on_macro_started(self, macro_id: str) -> None:
        if macro_id != self._macro_id:
            return
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Running…")

    def _on_macro_finished(self, macro_id: str) -> None:
        if macro_id != self._macro_id:
            return
        self._run_btn.setEnabled(True)
        self._run_btn.setText("▶  Run")

    def _on_destroyed(self) -> None:
        try:
            self._engine.macro_started.disconnect(self._on_macro_started)
            self._engine.macro_finished.disconnect(self._on_macro_finished)
        except Exception:
            pass


class MacroCatalogTile(QFrame):
    def __init__(self, engine: MacroEngine) -> None:
        super().__init__()
        self._engine = engine
        self.setObjectName("MacroCatalogTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Macros")
        title.setObjectName("CardTitle")
        header.addWidget(title, 1)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)

        scroll.setWidget(self._rows_container)
        root.addWidget(scroll, 1)

        self._engine.macro_started.connect(self._on_macro_started)
        self._engine.macro_finished.connect(self._on_macro_finished)
        self.destroyed.connect(self._on_destroyed)

        self._build_rows()

    def _build_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        macros = self._engine.repo.list_macros()
        for macro in macros:
            row = _MacroRow(macro, self._engine)
            self._rows_layout.addWidget(row)

        if not macros:
            empty = QLabel("No macros — open Macro Manager to create one.")
            empty.setObjectName("CardDescription")
            empty.setWordWrap(True)
            self._rows_layout.addWidget(empty)

        self._rows_layout.addStretch(1)

    def _on_macro_started(self, macro_id: str) -> None:
        for i in range(self._rows_layout.count()):
            w = self._rows_layout.itemAt(i).widget()
            if isinstance(w, _MacroRow) and w.macro_id == macro_id:
                w.set_running(True)

    def _on_macro_finished(self, macro_id: str) -> None:
        for i in range(self._rows_layout.count()):
            w = self._rows_layout.itemAt(i).widget()
            if isinstance(w, _MacroRow) and w.macro_id == macro_id:
                w.set_running(False)

    def _on_destroyed(self) -> None:
        try:
            self._engine.macro_started.disconnect(self._on_macro_started)
            self._engine.macro_finished.disconnect(self._on_macro_finished)
        except Exception:
            pass


class _MacroRow(QFrame):
    def __init__(self, macro, engine: MacroEngine) -> None:
        super().__init__()
        self.macro_id = macro.macro_id
        self._engine = engine
        self.setObjectName("TimerTileRow")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        icon_lbl = QLabel(macro.icon)
        icon_lbl.setObjectName("TimerTileLabel")
        icon_lbl.setFixedWidth(22)

        self._name_lbl = QLabel(macro.name)
        self._name_lbl.setObjectName("TimerTileLabel")

        self._run_btn = QPushButton("▶ Run")
        self._run_btn.setObjectName("TimerMiniBtn")
        self._run_btn.setFixedHeight(26)
        self._run_btn.clicked.connect(lambda: engine.run_macro(self.macro_id))

        row.addWidget(icon_lbl)
        row.addWidget(self._name_lbl, 1)
        row.addWidget(self._run_btn)

    def set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._run_btn.setText("Running…" if running else "▶ Run")
