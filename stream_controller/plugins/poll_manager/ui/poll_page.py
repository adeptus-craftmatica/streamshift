from __future__ import annotations

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from stream_controller.constants import POLL_OAUTH_PORT

if TYPE_CHECKING:
    from stream_controller.plugins.poll_manager.plugin import PollManagerPlugin
    from stream_controller.plugins.poll_manager.poll_engine import PollEngine
    from stream_controller.plugins.poll_manager.poll_models import Poll, PollState
    from stream_controller.plugins.poll_manager.poll_repository import PollRepository

_DURATIONS = [
    ("1 minute",  60),
    ("2 minutes", 120),
    ("3 minutes", 180),
    ("5 minutes", 300),
    ("10 minutes", 600),
]

_SCOPES = "channel%3Amanage%3Apolls+channel%3Aread%3Apolls"

_CALLBACK_HTML = f"""<!DOCTYPE html>
<html>
<head>
  <title>StreamShift — Poll Manager Authorization</title>
  <style>
    body {{ font-family: sans-serif; background: #0e1a26; color: #e2eaf2;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; }}
    .box {{ text-align: center; padding: 40px; }}
    h2 {{ font-size: 24px; margin-bottom: 12px; }}
    p  {{ color: #94a3b8; }}
  </style>
</head>
<body>
<div class="box" id="msg">
  <h2>Authorizing…</h2>
  <p>Sending token to StreamShift.</p>
</div>
<script>
  const hash   = location.hash.substring(1);
  const params = new URLSearchParams(hash);
  const token  = params.get('access_token');
  if (token) {{
    fetch('/oauth-token?t=' + encodeURIComponent(token))
      .then(() => {{
        document.getElementById('msg').innerHTML =
          '<h2>✓ Authorized!</h2><p>You can close this tab and return to StreamShift.</p>';
      }});
  }} else {{
    document.getElementById('msg').innerHTML =
      '<h2>Authorization failed</h2><p>No token received. Please try again.</p>';
  }}
</script>
</body>
</html>"""


class _ChoiceRow(QHBoxLayout):
    def __init__(self, index: int, on_remove) -> None:
        super().__init__()
        self.setSpacing(6)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(f"Choice {index + 1}  (max 25 chars)")
        self._edit.setMaxLength(25)
        self._edit.setObjectName("OverlayTextField")
        self.addWidget(self._edit, 1)
        self._remove_btn = QPushButton("−")
        self._remove_btn.setObjectName("SecondaryButton")
        self._remove_btn.setFixedWidth(30)
        self._remove_btn.clicked.connect(on_remove)
        self.addWidget(self._remove_btn)

    @property
    def text(self) -> str:
        return self._edit.text().strip()

    def set_text(self, value: str) -> None:
        self._edit.setText(value)

    def set_removable(self, yes: bool) -> None:
        self._remove_btn.setVisible(yes)


class _ChoiceBar(QFrame):
    """Single choice progress row inside the active poll display."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._label = QLabel()
        self._label.setMinimumWidth(120)
        self._label.setObjectName("CardTitle")
        lay.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(16)
        self._bar.setObjectName("PollProgressBar")
        lay.addWidget(self._bar, 1)

        self._pct = QLabel("0%")
        self._pct.setObjectName("MetaText")
        self._pct.setFixedWidth(38)
        self._pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._pct)

        self._votes = QLabel("0")
        self._votes.setObjectName("MetaText")
        self._votes.setFixedWidth(40)
        self._votes.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._votes)

    def update(self, title: str, votes: int, total: int, is_leading: bool) -> None:
        self._label.setText(title)
        pct = int(votes * 100 / total) if total else 0
        self._bar.setValue(pct)
        self._pct.setText(f"{pct}%")
        self._votes.setText(str(votes))
        color = "#7c3aed" if is_leading else "#334155"
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: #1e2d3d; border-radius: 8px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 8px; }}"
        )
        bold = "font-weight:700;" if is_leading else ""
        self._label.setStyleSheet(bold)


class PollPage(QWidget):
    _state_updated = Signal(object)

    def __init__(
        self,
        engine: "PollEngine",
        repo: "PollRepository",
        plugin: "PollManagerPlugin",
    ) -> None:
        super().__init__()
        self._engine = engine
        self._repo   = repo
        self._plugin = plugin
        self._oauth_server: HTTPServer | None = None
        self._choice_rows: list[_ChoiceRow] = []
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._seconds_left: int = 0

        self._build_ui()
        self._state_updated.connect(self._on_state)
        engine.subscribe(self._state_updated.emit)
        self._on_state(engine.state)

        self.destroyed.connect(self._on_destroyed)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        root.addWidget(self._build_connection_card())

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_new_poll_tab(), "New Poll")
        tabs.addTab(self._build_past_polls_tab(), "Past Polls")
        tabs.addTab(self._build_templates_tab(), "Templates")
        root.addWidget(tabs, 1)

    def _build_new_poll_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(self._build_create_card(), 1)
        lay.addWidget(self._build_active_card(), 1)
        return w

    def _build_past_polls_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_history_section())
        return w

    def _build_templates_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_templates_section())
        return w

    def _build_connection_card(self) -> QGroupBox:
        grp = QGroupBox("Connection")
        lay = QVBoxLayout(grp)
        lay.setSpacing(10)

        # Status row
        status_row = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b; font-size:18px;")
        self._status_lbl = QLabel("Not connected")
        self._status_lbl.setObjectName("MetaText")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._status_lbl, 1)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.setFixedWidth(110)
        self._connect_btn.clicked.connect(self._plugin.connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setFixedWidth(110)
        self._disconnect_btn.setVisible(False)
        self._disconnect_btn.clicked.connect(self._plugin.disconnect)
        status_row.addWidget(self._connect_btn)
        status_row.addWidget(self._disconnect_btn)
        lay.addLayout(status_row)

        # Settings row
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        cid_lbl = QLabel("Client ID:")
        cid_lbl.setObjectName("MetaText")
        settings_row.addWidget(cid_lbl)
        self._client_id_edit = QLineEdit()
        self._client_id_edit.setObjectName("OverlayTextField")
        self._client_id_edit.setPlaceholderText("Twitch app client ID (shared from Chat Manager)")
        self._client_id_edit.setText(self._repo.get("client_id") or "")
        self._client_id_edit.textChanged.connect(
            lambda t: self._repo.set("client_id", t.strip())
        )
        settings_row.addWidget(self._client_id_edit, 1)

        self._token_status = QLabel("")
        self._token_status.setObjectName("MetaText")
        settings_row.addWidget(self._token_status)

        auth_btn = QPushButton("Authorize")
        auth_btn.setObjectName("PrimaryButton")
        auth_btn.setFixedWidth(100)
        auth_btn.clicked.connect(self._authorize)
        settings_row.addWidget(auth_btn)

        self._auto_connect_cb = QCheckBox("Auto Connect")
        self._auto_connect_cb.setChecked(bool(self._repo.get("auto_connect")))
        self._auto_connect_cb.toggled.connect(
            lambda v: self._repo.set("auto_connect", v)
        )
        settings_row.addWidget(self._auto_connect_cb)

        lay.addLayout(settings_row)
        self._update_token_status()
        return grp

    def _build_create_card(self) -> QGroupBox:
        grp = QGroupBox("Create Poll")
        lay = QVBoxLayout(grp)
        lay.setSpacing(10)

        title_lbl = QLabel("Title  (max 60 chars)")
        title_lbl.setObjectName("MetaText")
        lay.addWidget(title_lbl)
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("OverlayTextField")
        self._title_edit.setMaxLength(60)
        self._title_edit.setPlaceholderText("What should we play next?")
        lay.addWidget(self._title_edit)

        choices_lbl = QLabel("Choices  (2 – 5)")
        choices_lbl.setObjectName("MetaText")
        lay.addWidget(choices_lbl)
        self._choices_container = QVBoxLayout()
        self._choices_container.setSpacing(6)
        lay.addLayout(self._choices_container)

        self._add_choice_btn = QPushButton("+ Add Choice")
        self._add_choice_btn.setObjectName("SecondaryButton")
        self._add_choice_btn.clicked.connect(self._add_choice)
        lay.addWidget(self._add_choice_btn)

        # Seed with 2 choices
        self._add_choice(removable=False)
        self._add_choice(removable=False)

        dur_row = QHBoxLayout()
        dur_lbl = QLabel("Duration:")
        dur_lbl.setObjectName("MetaText")
        dur_row.addWidget(dur_lbl)
        from PySide6.QtWidgets import QComboBox
        self._dur_combo = QComboBox()
        self._dur_combo.setObjectName("OverlayTextField")
        for label, secs in _DURATIONS:
            self._dur_combo.addItem(label, secs)
        dur_row.addWidget(self._dur_combo, 1)
        lay.addLayout(dur_row)

        lay.addStretch(1)

        self._create_btn = QPushButton("🗳️  Create Poll")
        self._create_btn.setObjectName("PrimaryButton")
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create)
        lay.addWidget(self._create_btn)

        return grp

    def _build_active_card(self) -> QGroupBox:
        self._active_grp = QGroupBox("Active Poll")
        lay = QVBoxLayout(self._active_grp)
        lay.setSpacing(10)

        self._no_poll_lbl = QLabel("No active poll.")
        self._no_poll_lbl.setObjectName("CardDescription")
        self._no_poll_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._no_poll_lbl)

        self._active_widget = QWidget()
        self._active_widget.setVisible(False)
        active_lay = QVBoxLayout(self._active_widget)
        active_lay.setContentsMargins(0, 0, 0, 0)
        active_lay.setSpacing(8)

        self._active_title = QLabel()
        self._active_title.setObjectName("CardTitle")
        self._active_title.setWordWrap(True)
        active_lay.addWidget(self._active_title)

        self._choice_bars: list[_ChoiceBar] = []
        self._bars_container = QVBoxLayout()
        self._bars_container.setSpacing(6)
        active_lay.addLayout(self._bars_container)

        footer = QHBoxLayout()
        self._total_votes_lbl = QLabel("0 votes")
        self._total_votes_lbl.setObjectName("MetaText")
        footer.addWidget(self._total_votes_lbl, 1)
        self._countdown_lbl = QLabel()
        self._countdown_lbl.setObjectName("MetaText")
        self._countdown_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        footer.addWidget(self._countdown_lbl)
        active_lay.addLayout(footer)

        active_lay.addStretch(1)

        btn_row = QHBoxLayout()
        self._end_btn = QPushButton("End Poll")
        self._end_btn.setObjectName("PrimaryButton")
        self._end_btn.clicked.connect(self._on_end_poll)
        self._archive_btn = QPushButton("Archive")
        self._archive_btn.setObjectName("SecondaryButton")
        self._archive_btn.clicked.connect(self._on_archive_poll)
        btn_row.addWidget(self._end_btn)
        btn_row.addWidget(self._archive_btn)
        active_lay.addLayout(btn_row)

        lay.addWidget(self._active_widget, 1)
        lay.addStretch(1)
        self._active_poll_id: str = ""
        return self._active_grp

    def _build_history_section(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._history_layout = QVBoxLayout(inner)
        self._history_layout.setSpacing(8)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        return w

    # ── Choice management ─────────────────────────────────────────────────────

    def _add_choice(self, removable: bool = True, text: str = "") -> None:
        if len(self._choice_rows) >= 5:
            return
        idx = len(self._choice_rows)
        row = _ChoiceRow(idx, on_remove=lambda _=False, r=idx: self._remove_choice(r))
        if text:
            row.set_text(text)
        row.set_removable(removable)
        self._choices_container.addLayout(row)
        self._choice_rows.append(row)
        self._add_choice_btn.setEnabled(len(self._choice_rows) < 5)
        self._refresh_choice_remove_btns()

    def _remove_choice(self, idx: int) -> None:
        if len(self._choice_rows) <= 2 or idx >= len(self._choice_rows):
            return
        row = self._choice_rows.pop(idx)
        # Remove widgets from layout
        while row.count():
            item = row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._choices_container.removeItem(row)
        self._add_choice_btn.setEnabled(len(self._choice_rows) < 5)
        self._refresh_choice_remove_btns()

    def _refresh_choice_remove_btns(self) -> None:
        can_remove = len(self._choice_rows) > 2
        for row in self._choice_rows:
            row.set_removable(can_remove)

    def _clear_choices(self) -> None:
        while self._choice_rows:
            row = self._choice_rows.pop()
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._choices_container.removeItem(row)
        self._add_choice_btn.setEnabled(True)

    # ── Poll actions ──────────────────────────────────────────────────────────

    def _on_create(self) -> None:
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing Title", "Please enter a poll title.")
            return
        choices = [r.text for r in self._choice_rows if r.text]
        if len(choices) < 2:
            QMessageBox.warning(self, "Need Choices", "Enter at least 2 choices.")
            return
        duration = self._dur_combo.currentData()
        self._plugin.create_poll(title, choices, duration)
        self._title_edit.clear()

    def _on_end_poll(self) -> None:
        if self._active_poll_id:
            self._plugin.end_poll(self._active_poll_id, archive=False)

    def _on_archive_poll(self) -> None:
        if self._active_poll_id:
            self._plugin.end_poll(self._active_poll_id, archive=True)

    def _on_rerun(self, title: str, choices: list[str]) -> None:
        self._title_edit.setText(title)
        self._clear_choices()
        for i, c in enumerate(choices[:5]):
            self._add_choice(removable=(i >= 2), text=c)
        while len(self._choice_rows) < 2:
            self._add_choice()

    # ── State updates ─────────────────────────────────────────────────────────

    def _on_state(self, state: "PollState") -> None:
        from stream_controller.plugins.poll_manager.poll_models import ConnectionStatus
        s = state.connection_status
        dot_colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color:{dot_colors.get(s, '#64748b')}; font-size:18px;")

        if s == ConnectionStatus.CONNECTED:
            self._status_lbl.setText("Connected to Twitch")
            self._connect_btn.setVisible(False)
            self._disconnect_btn.setVisible(True)
            self._create_btn.setEnabled(True)
        elif s == ConnectionStatus.CONNECTING:
            self._status_lbl.setText("Connecting…")
            self._connect_btn.setVisible(False)
            self._disconnect_btn.setVisible(False)
            self._create_btn.setEnabled(False)
        elif s == ConnectionStatus.ERROR:
            self._status_lbl.setText(f"Error: {state.connection_error[:60]}")
            self._connect_btn.setVisible(True)
            self._disconnect_btn.setVisible(False)
            self._create_btn.setEnabled(False)
        else:
            self._status_lbl.setText("Not connected")
            self._connect_btn.setVisible(True)
            self._disconnect_btn.setVisible(False)
            self._create_btn.setEnabled(False)

        self._refresh_active_poll(state.active_poll)
        self._refresh_history(state.recent_polls)

    def _refresh_active_poll(self, poll: "Poll | None") -> None:
        if poll is None:
            self._no_poll_lbl.setVisible(True)
            self._active_widget.setVisible(False)
            self._countdown_timer.stop()
            self._active_poll_id = ""
            return

        self._no_poll_lbl.setVisible(False)
        self._active_widget.setVisible(True)
        self._active_poll_id = poll.poll_id
        self._active_title.setText(poll.title)

        # Sync choice bars count
        while len(self._choice_bars) < len(poll.choices):
            bar = _ChoiceBar()
            self._bars_container.addWidget(bar)
            self._choice_bars.append(bar)
        while len(self._choice_bars) > len(poll.choices):
            bar = self._choice_bars.pop()
            self._bars_container.removeWidget(bar)
            bar.deleteLater()

        total = poll.total_votes
        winner_id = poll.winner.choice_id if poll.winner else ""
        for bar, choice in zip(self._choice_bars, poll.choices):
            bar.update(
                title=choice.title,
                votes=choice.total_votes,
                total=total,
                is_leading=(choice.choice_id == winner_id and total > 0),
            )

        votes_text = f"{total:,} vote{'s' if total != 1 else ''}"
        self._total_votes_lbl.setText(votes_text)

        from stream_controller.plugins.poll_manager.poll_models import PollStatus
        if poll.status == PollStatus.ACTIVE:
            self._seconds_left = poll.seconds_remaining
            self._update_countdown_label()
            self._countdown_timer.start()
            self._end_btn.setEnabled(True)
            self._archive_btn.setEnabled(True)
        else:
            self._countdown_timer.stop()
            self._countdown_lbl.setText("Ended")
            self._end_btn.setEnabled(False)
            self._archive_btn.setEnabled(False)

    def _tick_countdown(self) -> None:
        if self._seconds_left > 0:
            self._seconds_left -= 1
        self._update_countdown_label()

    def _update_countdown_label(self) -> None:
        m, s = divmod(self._seconds_left, 60)
        self._countdown_lbl.setText(f"{m}:{s:02d} remaining")

    def _refresh_history(self, polls: "list[Poll]") -> None:
        # Clear old rows (keep stretch at end)
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from stream_controller.plugins.poll_manager.poll_models import PollStatus
        for poll in polls:
            if poll.status == PollStatus.ACTIVE:
                continue
            row = self._build_history_row(poll)
            self._history_layout.insertWidget(self._history_layout.count() - 1, row)

    def _build_history_row(self, poll: "Poll") -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(16)

        # Title + winner summary
        info_lay = QVBoxLayout()
        info_lay.setSpacing(4)
        title_lbl = QLabel(poll.title)
        title_lbl.setObjectName("CardTitle")
        info_lay.addWidget(title_lbl)

        winner = poll.winner
        total  = poll.total_votes
        if winner and total:
            pct = int(winner.total_votes * 100 / total)
            summary = f"🏆 {winner.title} ({pct}%)  ·  {total:,} votes"
        else:
            summary = f"{total:,} votes"
        detail = QLabel(summary)
        detail.setObjectName("MetaText")
        info_lay.addWidget(detail)
        lay.addLayout(info_lay, 1)

        # Choice breakdown
        bars_lay = QVBoxLayout()
        bars_lay.setSpacing(3)
        winner_id = winner.choice_id if winner and total else ""
        for choice in poll.choices:
            row = QHBoxLayout()
            row.setSpacing(6)
            clbl = QLabel(choice.title)
            clbl.setObjectName("MetaText")
            clbl.setFixedWidth(120)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            pct_val = int(choice.total_votes * 100 / total) if total else 0
            bar.setValue(pct_val)
            leading = choice.choice_id == winner_id and total > 0
            bar.setStyleSheet(
                "QProgressBar{background:#1e2d3d;border-radius:4px;}"
                f"QProgressBar::chunk{{background:{'#7c3aed' if leading else '#334155'};border-radius:4px;}}"
            )
            pct_lbl = QLabel(f"{pct_val}%")
            pct_lbl.setObjectName("MetaText")
            pct_lbl.setFixedWidth(38)
            pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(clbl)
            row.addWidget(bar, 1)
            row.addWidget(pct_lbl)
            bars_lay.addLayout(row)
        lay.addLayout(bars_lay, 2)

        rerun_btn = QPushButton("Re-run")
        rerun_btn.setObjectName("SecondaryButton")
        rerun_btn.setFixedWidth(72)
        choices = [c.title for c in poll.choices]
        rerun_btn.clicked.connect(lambda _=False, t=poll.title, c=choices: self._on_rerun(t, c))
        lay.addWidget(rerun_btn, 0, Qt.AlignVCenter)
        return frame

    # ── Templates ─────────────────────────────────────────────────────────────

    def _build_templates_section(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        add_btn = QPushButton("+ New Template")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setFixedWidth(160)
        add_btn.clicked.connect(self._show_template_editor)
        outer.addWidget(add_btn, 0, Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._tpl_list_layout = QVBoxLayout(inner)
        self._tpl_list_layout.setSpacing(8)
        self._tpl_list_layout.setContentsMargins(0, 0, 0, 0)
        self._tpl_list_layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self._refresh_template_list()
        return w

    def _refresh_template_list(self) -> None:
        while self._tpl_list_layout.count() > 1:
            item = self._tpl_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for tpl in self._plugin.get_templates():
            row = QFrame()
            row.setObjectName("Card")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(12)

            info = QVBoxLayout()
            info.setSpacing(2)
            name_lbl = QLabel(tpl["name"])
            name_lbl.setObjectName("CardTitle")
            info.addWidget(name_lbl)
            detail = QLabel(
                f"{tpl['title']}  ·  "
                + ", ".join(tpl["choices"])
                + f"  ·  {tpl['duration'] // 60} min"
            )
            detail.setObjectName("MetaText")
            detail.setWordWrap(True)
            info.addWidget(detail)
            lay.addLayout(info, 1)

            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("SecondaryButton")
            edit_btn.setFixedWidth(60)
            edit_btn.clicked.connect(lambda _=False, t=tpl: self._show_template_editor(t))
            lay.addWidget(edit_btn)

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("SecondaryButton")
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(lambda _=False, tid=tpl["id"]: self._delete_template(tid))
            lay.addWidget(del_btn)

            self._tpl_list_layout.insertWidget(self._tpl_list_layout.count() - 1, row)

    def _delete_template(self, template_id: str) -> None:
        self._plugin.delete_template(template_id)
        self._refresh_template_list()

    def _show_template_editor(self, tpl: dict | None = None) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Edit Template" if tpl else "New Template")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)

        def _lbl(text):
            l = QLabel(text)
            l.setObjectName("MetaText")
            return l

        lay.addWidget(_lbl("Template name (shown in stage tile)"))
        name_edit = QLineEdit(tpl["name"] if tpl else "")
        name_edit.setObjectName("OverlayTextField")
        name_edit.setPlaceholderText("e.g. Game Vote")
        lay.addWidget(name_edit)

        lay.addWidget(_lbl("Poll title (shown to viewers)"))
        title_edit = QLineEdit(tpl["title"] if tpl else "")
        title_edit.setObjectName("OverlayTextField")
        title_edit.setMaxLength(60)
        title_edit.setPlaceholderText("What should we play next?")
        lay.addWidget(title_edit)

        lay.addWidget(_lbl("Choices (one per line, 2–5)"))
        choices_edit = QLineEdit()
        choices_edit.setObjectName("OverlayTextField")
        choices_edit.setPlaceholderText("Option A, Option B, Option C")
        if tpl:
            choices_edit.setText(", ".join(tpl["choices"]))
        lay.addWidget(choices_edit)

        from PySide6.QtWidgets import QComboBox
        lay.addWidget(_lbl("Duration"))
        dur_combo = QComboBox()
        dur_combo.setObjectName("OverlayTextField")
        for label, secs in _DURATIONS:
            dur_combo.addItem(label, secs)
        if tpl:
            idx = dur_combo.findData(tpl["duration"])
            if idx >= 0:
                dur_combo.setCurrentIndex(idx)
        lay.addWidget(dur_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        name = name_edit.text().strip()
        title = title_edit.text().strip()
        choices = [c.strip() for c in choices_edit.text().split(",") if c.strip()]
        duration = dur_combo.currentData()

        if not name or not title or len(choices) < 2:
            QMessageBox.warning(self, "Invalid Template",
                                "Name, title, and at least 2 choices are required.")
            return

        self._plugin.save_template(
            name=name, title=title, choices=choices[:5], duration=duration,
            template_id=tpl["id"] if tpl else None,
        )
        self._refresh_template_list()

    # ── OAuth ─────────────────────────────────────────────────────────────────

    def _authorize(self) -> None:
        client_id = self._client_id_edit.text().strip()
        if not client_id:
            QMessageBox.warning(
                self, "Client ID Required",
                "Enter your Twitch Client ID before authorizing.",
            )
            return

        redirect_uri = f"http://localhost:{POLL_OAUTH_PORT}/callback"

        class _Bridge(QObject):
            token_ready = Signal(str)

        bridge = _Bridge()
        bridge.token_ready.connect(self._on_token_received)
        server_holder: list[HTTPServer] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/callback":
                    body = _CALLBACK_HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/oauth-token"):
                    token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
                    if token:
                        bridge.token_ready.emit(token)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    def _shutdown():
                        server_holder[0].shutdown()
                    threading.Thread(target=_shutdown, daemon=True).start()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        if self._oauth_server is not None:
            threading.Thread(target=self._oauth_server.shutdown, daemon=True).start()
            self._oauth_server = None

        try:
            class _ReuseServer(HTTPServer):
                allow_reuse_address = True
            srv = _ReuseServer(("localhost", POLL_OAUTH_PORT), _Handler)
        except OSError:
            QMessageBox.warning(
                self, "Port In Use",
                f"Port {POLL_OAUTH_PORT} is in use. Restart StreamShift and try again.",
            )
            return

        self._oauth_server = srv
        server_holder.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        url = (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=token"
            f"&scope={_SCOPES}"
        )
        webbrowser.open(url)

    def _on_token_received(self, token: str) -> None:
        self._oauth_server = None
        self._repo.set("oauth_token", token)
        self._update_token_status()
        QMessageBox.information(
            self, "Authorized",
            "Poll Manager token received and saved.\n"
            "Click Connect to start managing polls.",
        )

    def _update_token_status(self) -> None:
        has_token = bool(self._repo.get("oauth_token"))
        self._token_status.setText("✓ Token saved" if has_token else "No token")
        self._token_status.setStyleSheet(
            "color:#22c55e;" if has_token else "color:#64748b;"
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_destroyed(self) -> None:
        self._engine.unsubscribe(self._state_updated.emit)
        self._countdown_timer.stop()
        if self._oauth_server:
            threading.Thread(target=self._oauth_server.shutdown, daemon=True).start()
            self._oauth_server = None
