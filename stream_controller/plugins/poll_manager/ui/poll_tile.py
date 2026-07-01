from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.poll_manager.plugin import PollManagerPlugin
    from stream_controller.plugins.poll_manager.poll_engine import PollEngine
    from stream_controller.plugins.poll_manager.poll_models import Poll

logger = logging.getLogger(__name__)

_DURATIONS = [
    ("1 min",   60),
    ("2 min",  120),
    ("3 min",  180),
    ("5 min",  300),
    ("10 min", 600),
]


class PollTile(QFrame):
    """Compact Poll Manager tile for the Stage View."""

    def __init__(self, engine: "PollEngine", plugin: "PollManagerPlugin") -> None:
        super().__init__()
        self._plugin = plugin
        self._active_poll_id: str = ""
        self._seconds_left: int = 0
        self._last_poll_id: str = ""

        self.setObjectName("StatsTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Poll Manager")
        title.setObjectName("CardTitle")
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b;")
        hdr.addWidget(title, 1)
        hdr.addWidget(self._dot)
        root.addLayout(hdr)

        # ── No-poll placeholder ───────────────────────────────────────────────
        self._no_poll_lbl = QLabel("No active poll")
        self._no_poll_lbl.setObjectName("CardDescription")
        self._no_poll_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._no_poll_lbl)

        # ── Active poll display ───────────────────────────────────────────────
        self._active_frame = QWidget()
        self._active_frame.setVisible(False)
        af = QVBoxLayout(self._active_frame)
        af.setContentsMargins(0, 0, 0, 0)
        af.setSpacing(4)

        self._poll_title_lbl = QLabel()
        self._poll_title_lbl.setObjectName("CardTitle")
        self._poll_title_lbl.setWordWrap(True)
        af.addWidget(self._poll_title_lbl)

        self._bars_lay = QVBoxLayout()
        self._bars_lay.setSpacing(3)
        af.addLayout(self._bars_lay)
        self._bars: list[tuple[QLabel, QProgressBar, QLabel]] = []

        foot = QHBoxLayout()
        self._votes_lbl = QLabel()
        self._votes_lbl.setObjectName("MetaText")
        foot.addWidget(self._votes_lbl, 1)
        self._time_lbl = QLabel()
        self._time_lbl.setObjectName("MetaText")
        self._time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        foot.addWidget(self._time_lbl)
        af.addLayout(foot)

        root.addWidget(self._active_frame, 1)

        # ── Inline create-poll form (hidden until "+ New Poll" clicked) ────────
        self._create_frame = QFrame()
        self._create_frame.setObjectName("Card")
        self._create_frame.setVisible(False)
        cf = QVBoxLayout(self._create_frame)
        cf.setContentsMargins(8, 8, 8, 8)
        cf.setSpacing(6)

        cf.addWidget(self._meta("Poll title"))
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("OverlayTextField")
        self._title_edit.setMaxLength(60)
        self._title_edit.setPlaceholderText("What should we play?")
        cf.addWidget(self._title_edit)

        cf.addWidget(self._meta("Choices (2–5)"))
        self._choice_edits: list[QLineEdit] = []
        self._choices_box = QVBoxLayout()
        self._choices_box.setSpacing(3)
        cf.addLayout(self._choices_box)

        # Must exist before _add_choice() is called
        self._add_choice_btn = QPushButton("+ choice")
        self._add_choice_btn.setObjectName("SecondaryButton")
        self._add_choice_btn.clicked.connect(self._add_choice)

        self._add_choice()
        self._add_choice()

        cf.addWidget(self._add_choice_btn)

        cf.addWidget(self._meta("Duration"))
        self._dur_combo = QComboBox()
        self._dur_combo.setObjectName("OverlayTextField")
        for lbl, secs in _DURATIONS:
            self._dur_combo.addItem(lbl, secs)
        cf.addWidget(self._dur_combo)

        form_btns = QHBoxLayout()
        form_btns.setSpacing(6)
        submit_btn = QPushButton("Create Poll")
        submit_btn.setObjectName("PrimaryButton")
        submit_btn.clicked.connect(self._submit_poll)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self._hide_form)
        form_btns.addWidget(submit_btn, 1)
        form_btns.addWidget(cancel_btn)
        cf.addLayout(form_btns)

        root.addWidget(self._create_frame)

        # ── Inline template picker (hidden until "From Template" clicked) ─────
        self._template_frame = QFrame()
        self._template_frame.setObjectName("Card")
        self._template_frame.setVisible(False)
        tf = QVBoxLayout(self._template_frame)
        tf.setContentsMargins(8, 8, 8, 8)
        tf.setSpacing(4)
        tf.addWidget(self._meta("Select a template"))
        self._template_list_lay = QVBoxLayout()
        self._template_list_lay.setSpacing(4)
        tf.addLayout(self._template_list_lay)
        self._no_templates_lbl = QLabel("No templates — add some in Poll Manager settings.")
        self._no_templates_lbl.setObjectName("CardDescription")
        self._no_templates_lbl.setWordWrap(True)
        tf.addWidget(self._no_templates_lbl)
        tpl_cancel = QPushButton("Cancel")
        tpl_cancel.setObjectName("SecondaryButton")
        tpl_cancel.clicked.connect(self._hide_template_picker)
        tf.addWidget(tpl_cancel)
        root.addWidget(self._template_frame)

        root.addStretch(1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("SecondaryButton")
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._connect_btn)

        self._new_poll_btn = QPushButton("+ Custom")
        self._new_poll_btn.setObjectName("PrimaryButton")
        self._new_poll_btn.setEnabled(False)
        self._new_poll_btn.clicked.connect(self._show_form)
        btn_row.addWidget(self._new_poll_btn)

        self._template_btn = QPushButton("From Template")
        self._template_btn.setObjectName("SecondaryButton")
        self._template_btn.setEnabled(False)
        self._template_btn.clicked.connect(self._show_template_picker)
        btn_row.addWidget(self._template_btn)

        self._end_btn = QPushButton("End Poll")
        self._end_btn.setObjectName("SecondaryButton")
        self._end_btn.setEnabled(False)
        self._end_btn.setVisible(False)
        self._end_btn.clicked.connect(self._on_end)
        btn_row.addWidget(self._end_btn)

        root.addLayout(btn_row)

        # ── Timers ────────────────────────────────────────────────────────────
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self.destroyed.connect(self._refresh_timer.stop)

        self._countdown = QTimer(self)
        self._countdown.setInterval(1000)
        self._countdown.timeout.connect(self._tick)
        self.destroyed.connect(self._countdown.stop)

        self._refresh()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _meta(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("MetaText")
        return l

    def _add_choice(self) -> None:
        if len(self._choice_edits) >= 5:
            return
        idx = len(self._choice_edits)
        e = QLineEdit()
        e.setObjectName("OverlayTextField")
        e.setMaxLength(25)
        e.setPlaceholderText(f"Choice {idx + 1}")
        self._choices_box.addWidget(e)
        self._choice_edits.append(e)
        self._add_choice_btn.setEnabled(len(self._choice_edits) < 5)

    # ── Form show/hide ────────────────────────────────────────────────────────

    def _show_form(self) -> None:
        print("POLL TILE: _show_form called", flush=True)
        logger.warning("PollTile: showing create-poll form")
        self._title_edit.clear()
        for e in self._choice_edits:
            e.clear()
        self._active_frame.setVisible(False)
        self._no_poll_lbl.setVisible(False)
        self._new_poll_btn.setVisible(False)
        self._end_btn.setVisible(False)
        self._create_frame.setVisible(True)
        self.updateGeometry()
        self.update()
        print("POLL TILE: create_frame visible =", self._create_frame.isVisible(), flush=True)

    def _hide_form(self) -> None:
        self._create_frame.setVisible(False)
        self._new_poll_btn.setVisible(True)
        self._template_btn.setVisible(True)
        self._refresh()

    # ── Template picker ───────────────────────────────────────────────────────

    def _show_template_picker(self) -> None:
        # Rebuild the list fresh each time so edits in settings show up
        while self._template_list_lay.count():
            item = self._template_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        templates = self._plugin.get_templates()
        self._no_templates_lbl.setVisible(not templates)
        for tpl in templates:
            btn = QPushButton(tpl["name"])
            btn.setObjectName("SecondaryButton")
            btn.setToolTip(
                f"{tpl['title']}\n"
                + "\n".join(f"• {c}" for c in tpl["choices"])
                + f"\n{tpl['duration'] // 60} min"
            )
            btn.clicked.connect(lambda _=False, t=tpl: self._launch_template(t))
            self._template_list_lay.addWidget(btn)

        self._active_frame.setVisible(False)
        self._no_poll_lbl.setVisible(False)
        self._new_poll_btn.setVisible(False)
        self._template_btn.setVisible(False)
        self._end_btn.setVisible(False)
        self._template_frame.setVisible(True)
        self.updateGeometry()

    def _hide_template_picker(self) -> None:
        self._template_frame.setVisible(False)
        self._new_poll_btn.setVisible(True)
        self._template_btn.setVisible(True)
        self._refresh()

    def _launch_template(self, tpl: dict) -> None:
        self._hide_template_picker()
        self._plugin.create_poll(tpl["title"], tpl["choices"], tpl["duration"])

    def _submit_poll(self) -> None:
        title   = self._title_edit.text().strip()
        choices = [e.text().strip() for e in self._choice_edits if e.text().strip()]
        duration = self._dur_combo.currentData()
        logger.debug("PollTile: submit — title=%r choices=%s dur=%s", title, choices, duration)
        if not title:
            logger.warning("PollTile: no title entered")
            return
        if len(choices) < 2:
            logger.warning("PollTile: fewer than 2 choices: %s", choices)
            return
        self._plugin.create_poll(title, choices, duration)
        self._hide_form()

    # ── State polling ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus
        engine = getattr(self._plugin, "_engine", None)
        if engine is None:
            return

        state = engine.state
        dot_colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color:{dot_colors.get(state.connection_status, '#64748b')};")

        connected  = state.connection_status == ConnectionStatus.CONNECTED
        connecting = state.connection_status == ConnectionStatus.CONNECTING
        self._connect_btn.setVisible(not connected and not connecting)

        # Don't touch buttons / active frame while a form is open
        if not self._create_frame.isVisible() and not self._template_frame.isVisible():
            self._new_poll_btn.setEnabled(connected)
            self._new_poll_btn.setVisible(True)
            self._template_btn.setEnabled(connected)
            self._template_btn.setVisible(True)
            self._refresh_poll(state.active_poll)

    def _refresh_poll(self, poll: "Poll | None") -> None:
        if poll is None:
            self._no_poll_lbl.setVisible(True)
            self._active_frame.setVisible(False)
            self._countdown.stop()
            self._active_poll_id = ""
            self._end_btn.setEnabled(False)
            self._end_btn.setVisible(False)
            return

        self._no_poll_lbl.setVisible(False)
        self._active_frame.setVisible(True)
        self._active_poll_id = poll.poll_id
        self._poll_title_lbl.setText(poll.title)

        total     = poll.total_votes
        winner_id = poll.winner.choice_id if poll.winner else ""
        shown     = poll.choices

        while len(self._bars) < len(shown):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel()
            lbl.setObjectName("MetaText")
            lbl.setFixedWidth(80)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            pct = QLabel("0%")
            pct.setObjectName("MetaText")
            pct.setFixedWidth(38)
            pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addWidget(bar, 1)
            row.addWidget(pct)
            self._bars_lay.addLayout(row)
            self._bars.append((lbl, bar, pct))

        while len(self._bars) > len(shown):
            lbl, bar, pct = self._bars.pop()
            lbl.deleteLater(); bar.deleteLater(); pct.deleteLater()

        for (lbl, bar, pct_lbl), choice in zip(self._bars, shown):
            v = choice.total_votes
            p = int(v * 100 / total) if total else 0
            lbl.setText(choice.title[:10] + "…" if len(choice.title) > 10 else choice.title)
            bar.setValue(p)
            pct_lbl.setText(f"{p}%")
            leading = choice.choice_id == winner_id and total > 0
            bar.setStyleSheet(
                "QProgressBar{background:#1e2d3d;border-radius:5px;}"
                f"QProgressBar::chunk{{background:{'#7c3aed' if leading else '#334155'};border-radius:5px;}}"
            )

        self._votes_lbl.setText(f"{total:,} vote{'s' if total != 1 else ''}")

        from stream_controller.plugins.poll_manager.poll_models import PollStatus
        active = poll.status == PollStatus.ACTIVE
        if active:
            if poll.poll_id != self._last_poll_id or self._seconds_left == 0:
                self._seconds_left = poll.seconds_remaining
                self._last_poll_id = poll.poll_id
            self._update_time_label()
            if not self._countdown.isActive():
                self._countdown.start()
        else:
            self._countdown.stop()
            self._time_lbl.setText("Ended")

        self._end_btn.setEnabled(active)
        self._end_btn.setVisible(True)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _on_connect(self) -> None:
        self._plugin.connect()
        self._connect_btn.setVisible(False)
        self._dot.setStyleSheet("color:#f59e0b;")

    def _on_end(self) -> None:
        if self._active_poll_id:
            self._plugin.end_poll(self._active_poll_id, archive=False)

    # ── Countdown ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._seconds_left > 0:
            self._seconds_left -= 1
            self._update_time_label()
            if self._seconds_left == 0:
                self._plugin.request_refresh()
        else:
            self._update_time_label()

    def _update_time_label(self) -> None:
        m, s = divmod(self._seconds_left, 60)
        self._time_lbl.setText(f"{m}:{s:02d} left")
