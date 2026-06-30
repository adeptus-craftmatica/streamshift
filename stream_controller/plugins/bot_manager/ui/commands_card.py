from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stream_controller.plugins.bot_manager.bot_engine import BotEngine


class _CommandRow(QWidget):
    """Single command row: checkbox | trigger | response preview | cooldown badge."""

    def __init__(self, cmd, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._db = db

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        self._checkbox = QCheckBox()
        self._checkbox.setChecked(cmd.enabled)
        self._checkbox.setFixedWidth(18)
        self._checkbox.toggled.connect(self._on_toggle)
        layout.addWidget(self._checkbox)

        trigger_lbl = QLabel(f"!{cmd.trigger.lstrip('!')}")
        trigger_lbl.setStyleSheet(
            "font-family:monospace; font-size:11px; font-weight:600; "
            "color:#7c3aed; min-width:80px; max-width:100px;"
        )
        trigger_lbl.setTextFormat(Qt.PlainText)
        layout.addWidget(trigger_lbl)

        preview = cmd.response[:40] + ("…" if len(cmd.response) > 40 else "")
        preview_lbl = QLabel(preview)
        preview_lbl.setStyleSheet("font-size:10px; color:#94a3b8;")
        preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview_lbl.setTextFormat(Qt.PlainText)
        layout.addWidget(preview_lbl)

        if cmd.cooldown_seconds > 0:
            cool_lbl = QLabel(f"{cmd.cooldown_seconds}s")
            cool_lbl.setStyleSheet(
                "background:#1e293b; color:#64748b; font-size:9px;"
                "padding:1px 5px; border-radius:3px; font-weight:600;"
            )
            cool_lbl.setFixedWidth(30)
            layout.addWidget(cool_lbl)

        self._apply_dim(cmd.enabled)

        self._trigger_lbl = trigger_lbl
        self._preview_lbl = preview_lbl

    def _on_toggle(self, checked: bool) -> None:
        self._cmd.enabled = checked
        self._db.save_command(self._cmd)
        self._apply_dim(checked)

    def _apply_dim(self, enabled: bool) -> None:
        opacity = "1.0" if enabled else "0.4"
        self.setStyleSheet(f"opacity: {opacity};")
        # Qt doesn't support CSS opacity on QWidget directly — use setEnabled dimming via palette trick
        for lbl in self.findChildren(QLabel):
            current = lbl.styleSheet()
            if enabled:
                lbl.setStyleSheet(current.replace("color:#475569", ""))
            lbl.setEnabled(True)
        # Visually dim the whole row by adjusting child label colours
        self._set_row_enabled(enabled)

    def _set_row_enabled(self, enabled: bool) -> None:
        dim_color = "#3a4a5a"
        for child in self.findChildren(QLabel):
            style = child.styleSheet()
            if not enabled:
                child.setStyleSheet(style + f" color:{dim_color};")
            # on enable we rebuild from scratch on next refresh


class _BotSection(QWidget):
    """Group header + command rows for a single bot."""

    def __init__(self, bot_name: str, bot_icon: str, commands, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        # Section header
        header = QLabel(f"{bot_icon or '🤖'} {bot_name}")
        header.setStyleSheet(
            "font-size:11px; font-weight:700; color:#64748b;"
            "padding:2px 6px; background:#0d1117; border-radius:3px;"
        )
        layout.addWidget(header)

        for i, cmd in enumerate(commands):
            row = _CommandRow(cmd, db)
            if i % 2 == 1:
                row.setStyleSheet(row.styleSheet() + "background:#0f172a;")
            layout.addWidget(row)

            if i < len(commands) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.HLine)
                div.setStyleSheet("color:#1e293b; margin:0px;")
                layout.addWidget(div)


class CommandsCard(QFrame):
    """Stage panel card showing all registered bot commands with enable/disable toggles."""

    def __init__(self, engines: dict[str, BotEngine], app_context) -> None:
        super().__init__()
        self._engines = engines
        self._app_context = app_context

        self.setObjectName("Card")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("⌨ Commands")
        title.setObjectName("CardTitle")
        title.setStyleSheet("font-size:13px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("StagePrimaryBtn")
        refresh_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        refresh_btn.clicked.connect(self._reload)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # ── Scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("background:transparent;")

        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll)

        # ── Auto-refresh timer ──
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._reload)
        self._timer.start()

        self._reload()

    def _reload(self) -> None:
        # Clear existing content (keep trailing stretch)
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._engines:
            empty = QLabel("No bots connected.")
            empty.setStyleSheet("color:#475569; font-size:11px; padding:8px;")
            empty.setAlignment(Qt.AlignCenter)
            self._content_layout.insertWidget(0, empty)
            return

        # Collect commands grouped by bot_id, then look up bot names from engines
        idx = 0
        for bot_id, engine in self._engines.items():
            commands = engine._db.list_commands()
            if not commands:
                continue

            bot_name = engine._config.name if hasattr(engine, "_config") else bot_id
            bot_icon = getattr(engine._config, "icon", "🤖") if hasattr(engine, "_config") else "🤖"

            section = _BotSection(bot_name, bot_icon, commands, engine._db)
            self._content_layout.insertWidget(idx, section)
            idx += 1

            if idx < len(self._engines):
                div = QFrame()
                div.setFrameShape(QFrame.HLine)
                div.setStyleSheet("color:#1e293b;")
                self._content_layout.insertWidget(idx, div)
                idx += 1

        if idx == 0:
            empty = QLabel("No commands configured.")
            empty.setStyleSheet("color:#475569; font-size:11px; padding:8px;")
            empty.setAlignment(Qt.AlignCenter)
            self._content_layout.insertWidget(0, empty)
