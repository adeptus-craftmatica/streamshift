from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.stream_stats.stats_engine import StatsEngine
    from stream_controller.plugins.stream_stats.stats_models import LiveStats
    from stream_controller.plugins.stream_stats.stats_repository import StatsRepository


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("CardDescription")
    lbl.setWordWrap(True)
    return lbl


class _AuthSignals(QObject):
    auth_ok  = Signal(str, str)  # token, username
    auth_err = Signal(str)       # error message


class StatsPage(QWidget):
    def __init__(self, engine: "StatsEngine", repo: "StatsRepository",
                 overlay_base_url: str) -> None:
        super().__init__()
        self._engine = engine
        self._repo   = repo
        self._overlay_base = overlay_base_url
        self._auth_flow = None
        self._auth_signals = _AuthSignals()
        self._auth_signals.auth_ok.connect(self._apply_auth)
        self._auth_signals.auth_err.connect(self._show_auth_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(20)

        title = QLabel("Stream Stats")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setObjectName("StatsTabWidget")
        tabs.addTab(self._build_live_tab(), "Live Stats")
        tabs.addTab(self._build_settings_tab(), "Settings")
        tabs.addTab(self._build_overlays_tab(), "Overlays")
        tabs.addTab(self._build_history_tab(), "History")
        saved_tab = int(QSettings("StreamShift", "StreamController").value("stats/tab", 0))
        tabs.setCurrentIndex(saved_tab if 0 <= saved_tab < tabs.count() else 0)
        tabs.currentChanged.connect(lambda i: QSettings("StreamShift", "StreamController").setValue("stats/tab", i))
        root.addWidget(tabs, 1)

        engine.subscribe(self._on_stats)
        self._on_stats(engine.live)
        self.destroyed.connect(lambda: engine.unsubscribe(self._on_stats))

    # ── Live Stats tab ────────────────────────────────────────────────────────

    def _build_live_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 16, 0, 0)
        root.setSpacing(16)

        # Connection status bar
        status_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color:#64748b;font-size:16px;")
        self._status_lbl = QLabel("Not connected")
        self._status_lbl.setObjectName("CardDescription")
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.setMinimumWidth(100)
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setMinimumWidth(100)
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._disconnect_btn.hide()
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_lbl, 1)
        status_row.addWidget(self._connect_btn)
        status_row.addWidget(self._disconnect_btn)
        root.addLayout(status_row)

        # Session controls
        sess_card = QFrame()
        sess_card.setObjectName("Card")
        sess_layout = QVBoxLayout(sess_card)
        sess_layout.setContentsMargins(20, 16, 20, 16)
        sess_layout.setSpacing(10)
        sess_title = QLabel("Session")
        sess_title.setObjectName("CardTitle")
        sess_layout.addWidget(sess_title)
        sess_layout.addWidget(_hint(
            "Start a session when you go live. Stats accumulate until you end the session, "
            "which saves a record to History."
        ))
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶  Start Session")
        self._start_btn.setObjectName("PrimaryButton")
        self._start_btn.setMinimumWidth(140)
        self._start_btn.clicked.connect(self._start_session)
        self._end_btn = QPushButton("■  End Session")
        self._end_btn.setObjectName("SecondaryButton")
        self._end_btn.setMinimumWidth(140)
        self._end_btn.setEnabled(False)
        self._end_btn.clicked.connect(self._end_session)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._end_btn)
        btn_row.addStretch(1)
        sess_layout.addLayout(btn_row)
        self._session_label = QLabel("")
        self._session_label.setObjectName("MetaText")
        sess_layout.addWidget(self._session_label)
        root.addWidget(sess_card)

        # Live stats grid
        stats_card = QFrame()
        stats_card.setObjectName("Card")
        sl = QVBoxLayout(stats_card)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(12)
        sl.addWidget(QLabel("Current Session", objectName="CardTitle"))

        grid = QGridLayout()
        grid.setSpacing(8)
        self._stat_labels: dict[str, QLabel] = {}
        rows = [
            ("total_followers",  "Total Followers",  "#22c55e"),
            ("followers_gained", "Followers Gained", "#7c3aed"),
            ("latest_follower",  "Latest Follower",  "#f0f0ff"),
            ("bits_donated",     "Bits Donated",     "#f59e0b"),
            ("new_subs",         "Subscriptions",    "#ec4899"),
            ("gifted_subs",      "Gifted Subs",      "#38bdf8"),
        ]
        for i, (key, label, color) in enumerate(rows):
            lbl = QLabel(label)
            lbl.setObjectName("MetaText")
            val = QLabel("–")
            val.setObjectName("MetricValue")
            val.setStyleSheet(f"color:{color};font-size:20px;font-weight:700;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(val, i, 1)
            self._stat_labels[key] = val
        sl.addLayout(grid)
        root.addWidget(stats_card)
        root.addStretch(1)
        return w

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 16, 0, 16)
        root.setSpacing(20)

        auth_card = QFrame()
        auth_card.setObjectName("Card")
        al = QVBoxLayout(auth_card)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(12)
        al.addWidget(QLabel("Twitch Connection", objectName="CardTitle"))
        al.addWidget(_hint(
            "Stream Stats uses the same Client ID as your Chat Manager. "
            "Click Authorize to grant the additional scopes needed for follower, "
            "subscription, and bits tracking."
        ))

        form = QGridLayout()
        form.setSpacing(8)

        form.addWidget(QLabel("Client ID"), 0, 0)
        self._client_id_input = QLineEdit(self._repo.get("client_id") or "")
        self._client_id_input.setObjectName("ChatSendInput")
        self._client_id_input.setPlaceholderText("Paste your Twitch Client ID")
        self._client_id_input.textChanged.connect(lambda t: self._repo.set("client_id", t.strip()))
        form.addWidget(self._client_id_input, 0, 1)

        self._auth_status = QLabel(
            "✓ Authorized" if self._repo.get("oauth_token") else "Not authorized"
        )
        self._auth_status.setObjectName("MetaText")
        self._auth_status.setStyleSheet(
            "color:#22c55e;" if self._repo.get("oauth_token") else "color:#64748b;"
        )
        form.addWidget(self._auth_status, 1, 1)

        al.addLayout(form)

        auth_btn_row = QHBoxLayout()
        auth_btn = QPushButton("Authorize with Twitch")
        auth_btn.setObjectName("PrimaryButton")
        auth_btn.setMinimumWidth(180)
        auth_btn.clicked.connect(self._start_auth)
        revoke_btn = QPushButton("Revoke")
        revoke_btn.setObjectName("SecondaryButton")
        revoke_btn.clicked.connect(self._revoke)
        auth_btn_row.addWidget(auth_btn)
        auth_btn_row.addWidget(revoke_btn)
        auth_btn_row.addStretch(1)
        al.addLayout(auth_btn_row)
        root.addWidget(auth_card)
        root.addStretch(1)
        return scroll

    # ── Overlays tab ──────────────────────────────────────────────────────────

    def _build_overlays_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 16, 0, 16)
        root.setSpacing(16)

        root.addWidget(QLabel("Browser Source URLs", objectName="CardTitle"))
        root.addWidget(_hint(
            "Add these as Browser Source in OBS. The overlay server runs at "
            f"{self._overlay_base} while StreamShift is open."
        ))

        overlays = [
            ("Combined Card",    "/combined",  "All stats in a dark card — great for corner placement."),
            ("Followers",        "/followers", "Pill showing total followers, gained, and latest follower."),
            ("Stats Bar",        "/bar",       "Horizontal bar with all 5 stats — fits along the bottom."),
            ("Ticker",           "/ticker",    "Scrolling ticker strip — place at bottom of screen."),
            ("Minimal",          "/minimal",   "Compact side strip — minimal footprint on screen."),
        ]
        for name, path, desc in overlays:
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(6)
            cl.addWidget(QLabel(name, objectName="CardTitle"))
            cl.addWidget(_hint(desc))
            url_row = QHBoxLayout()
            url_lbl = QLabel(f"{self._overlay_base}{path}")
            url_lbl.setObjectName("MetaText")
            url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            copy_btn = QPushButton("Copy URL")
            copy_btn.setObjectName("SecondaryButton")
            copy_btn.setFixedWidth(84)
            url = f"{self._overlay_base}{path}"
            copy_btn.clicked.connect(lambda _, u=url: self._copy(u))
            url_row.addWidget(url_lbl, 1)
            url_row.addWidget(copy_btn)
            cl.addLayout(url_row)
            root.addWidget(card)

        root.addStretch(1)
        return scroll

    # ── History tab ───────────────────────────────────────────────────────────

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 16, 0, 0)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Session History", objectName="CardTitle"), 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.clicked.connect(self._load_history)
        hdr.addWidget(refresh_btn)
        root.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._history_inner = QWidget()
        self._history_layout = QVBoxLayout(self._history_inner)
        self._history_layout.setSpacing(10)
        self._history_layout.addStretch(1)
        scroll.setWidget(self._history_inner)
        root.addWidget(scroll, 1)

        self._load_history()
        return w

    def _load_history(self) -> None:
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sessions = self._repo.sessions()
        if not sessions:
            lbl = QLabel("No sessions recorded yet.")
            lbl.setObjectName("EmptyState")
            self._history_layout.insertWidget(0, lbl)
            return

        for rec in sessions:
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(6)

            date_str = rec.started_at[:10] if rec.started_at else "Unknown"
            title_str = rec.stream_title or "Stream Session"
            cl.addWidget(QLabel(f"{date_str} — {title_str}", objectName="CardTitle"))

            grid = QGridLayout()
            grid.setSpacing(4)
            pairs = [
                ("Total Followers", f"{rec.total_followers:,}"),
                ("Followers Gained", f"+{rec.followers_gained:,}"),
                ("Bits Donated", f"{rec.bits_donated:,}"),
                ("Subscriptions", str(rec.new_subs)),
                ("Gifted Subs", str(rec.gifted_subs)),
                ("Latest Follower", rec.latest_follower or "—"),
            ]
            for i, (lbl, val) in enumerate(pairs):
                col = (i % 2) * 2
                row = i // 2
                name_l = QLabel(lbl)
                name_l.setObjectName("MetaText")
                val_l = QLabel(val)
                val_l.setObjectName("MetricValue")
                val_l.setStyleSheet("font-size:14px;font-weight:600;")
                grid.addWidget(name_l, row, col)
                grid.addWidget(val_l,  row, col + 1)
            cl.addLayout(grid)
            self._history_layout.insertWidget(self._history_layout.count() - 1, card)

    # ── state update ──────────────────────────────────────────────────────────

    def on_stats_changed(self, stats: "LiveStats") -> None:
        self._on_stats(stats)

    def _on_stats(self, stats: "LiveStats") -> None:
        from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus
        colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        labels = {
            ConnectionStatus.CONNECTED:    "Connected to Twitch",
            ConnectionStatus.CONNECTING:   "Connecting…",
            ConnectionStatus.DISCONNECTED: "Not connected",
            ConnectionStatus.ERROR:        f"Error: {stats.error[:80]}",
        }
        color = colors.get(stats.status, "#64748b")
        self._status_dot.setStyleSheet(f"color:{color};font-size:16px;")
        self._status_lbl.setText(labels.get(stats.status, ""))

        connected = stats.status == ConnectionStatus.CONNECTED
        self._connect_btn.setVisible(not connected)
        self._disconnect_btn.setVisible(connected)

        active = stats.session_active
        self._start_btn.setEnabled(not active)
        self._end_btn.setEnabled(active)
        self._session_label.setText("● Session active" if active else "")

        self._stat_labels["total_followers"].setText(f"{stats.total_followers:,}")
        self._stat_labels["followers_gained"].setText(f"+{stats.followers_gained:,}")
        self._stat_labels["latest_follower"].setText(stats.latest_follower or "—")
        self._stat_labels["bits_donated"].setText(f"{stats.bits_donated:,}")
        self._stat_labels["new_subs"].setText(str(stats.new_subs))
        self._stat_labels["gifted_subs"].setText(str(stats.gifted_subs))

    # ── actions ───────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        if self._plugin_ref:
            self._plugin_ref.do_connect()

    def _disconnect(self) -> None:
        if self._plugin_ref:
            self._plugin_ref.do_disconnect()

    def _start_session(self) -> None:
        self._engine.start_session()

    def _end_session(self) -> None:
        self._engine.end_session()
        self._load_history()

    def _start_auth(self) -> None:
        from stream_controller.plugins.stream_stats.twitch_auth import StatsAuthFlow
        client_id = self._client_id_input.text().strip()
        if not client_id:
            self._auth_status.setText("Enter a Client ID first.")
            self._auth_status.setStyleSheet("color:#ef4444;")
            return
        self._auth_status.setText("Opening browser…")
        self._auth_status.setStyleSheet("color:#f59e0b;")
        self._auth_flow = StatsAuthFlow(
            client_id=client_id,
            on_complete=self._on_auth_complete,
            on_error=self._on_auth_error,
        )
        self._auth_flow.start()

    def _on_auth_complete(self, token: str, username: str) -> None:
        self._auth_signals.auth_ok.emit(token, username)

    def _apply_auth(self, token: str, username: str) -> None:
        self._repo.set("oauth_token", token)
        self._auth_status.setText(f"✓ Authorized as {username}" if username else "✓ Authorized")
        self._auth_status.setStyleSheet("color:#22c55e;")

    def _on_auth_error(self, msg: str) -> None:
        self._auth_signals.auth_err.emit(msg)

    def _show_auth_error(self, msg: str) -> None:
        self._auth_status.setText(f"Error: {msg}")
        self._auth_status.setStyleSheet("color:#ef4444;")

    def _revoke(self) -> None:
        self._repo.set("oauth_token", "")
        self._auth_status.setText("Not authorized")
        self._auth_status.setStyleSheet("color:#64748b;")

    def _copy(self, url: str) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(url)

    def set_plugin_ref(self, plugin) -> None:
        self._plugin_ref = plugin

    _plugin_ref = None
