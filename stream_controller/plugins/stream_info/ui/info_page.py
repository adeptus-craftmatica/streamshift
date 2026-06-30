from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.stream_info.plugin import StreamInfoPlugin
    from stream_controller.plugins.stream_info.info_models import InfoState


def _fmt_viewers(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M viewers"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K viewers"
    return f"{n} viewers"



_LANGUAGES = [
    ("en", "English"), ("fr", "French"), ("de", "German"), ("es", "Spanish"),
    ("pt", "Portuguese"), ("it", "Italian"), ("nl", "Dutch"), ("pl", "Polish"),
    ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese"),
    ("sv", "Swedish"), ("no", "Norwegian"), ("da", "Danish"), ("fi", "Finnish"),
    ("tr", "Turkish"), ("ar", "Arabic"), ("other", "Other"),
]


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("CardDescription")
    lbl.setWordWrap(True)
    return lbl


class _PageSignals(QObject):
    auth_ok        = Signal(str, str)  # token, username
    auth_err       = Signal(str)       # error message
    search_results = Signal(object)    # list[dict]


class InfoPage(QWidget):
    def __init__(self, plugin: "StreamInfoPlugin") -> None:
        super().__init__()
        self._plugin    = plugin
        self._auth_flow = None
        self._cat_map: dict[str, str] = {}
        self._pending_cat_id: str = ""
        self._sigs = _PageSignals()
        self._sigs.auth_ok.connect(self._apply_auth)
        self._sigs.auth_err.connect(self._show_auth_error)
        self._sigs.search_results.connect(self._on_search_results)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(20)

        root.addWidget(QLabel("Stream Info", objectName="PageTitle"))

        tabs = QTabWidget()
        tabs.setObjectName("InfoTabWidget")
        tabs.addTab(self._build_control_tab(), "Stream Control")
        tabs.addTab(self._build_settings_tab(), "Settings")
        saved_tab = int(QSettings("StreamShift", "StreamController").value("stream_info/tab", 0))
        tabs.setCurrentIndex(saved_tab if 0 <= saved_tab < tabs.count() else 0)
        tabs.currentChanged.connect(lambda i: QSettings("StreamShift", "StreamController").setValue("stream_info/tab", i))
        root.addWidget(tabs, 1)

        plugin.subscribe(self._on_state)
        self._on_state(plugin.state)
        self.destroyed.connect(lambda: plugin.unsubscribe(self._on_state))

    # ── Stream Control tab ────────────────────────────────────────────────────

    def _build_control_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 16, 0, 16)
        root.setSpacing(20)

        # Connection + stream status row
        status_card = QFrame(inner)
        status_card.setObjectName("Card")
        sl = QVBoxLayout(status_card)
        sl.setContentsMargins(20, 14, 20, 14)
        sl.setSpacing(10)
        top = QHBoxLayout()
        self._dot      = QLabel("●")
        self._dot.setStyleSheet("color:#64748b;font-size:16px;")
        self._status_lbl = QLabel("Not connected")
        self._status_lbl.setObjectName("CardDescription")
        self._conn_btn = QPushButton("Connect")
        self._conn_btn.setObjectName("PrimaryButton")
        self._conn_btn.setMinimumWidth(90)
        self._conn_btn.clicked.connect(self._connect)
        self._disconn_btn = QPushButton("Disconnect")
        self._disconn_btn.setObjectName("SecondaryButton")
        self._disconn_btn.setMinimumWidth(90)
        self._disconn_btn.clicked.connect(self._disconnect)
        self._disconn_btn.hide()
        top.addWidget(self._dot)
        top.addWidget(self._status_lbl, 1)
        top.addWidget(self._conn_btn)
        top.addWidget(self._disconn_btn)
        sl.addLayout(top)

        # Stream status badge + Go Live / End Stream
        live_row = QHBoxLayout()
        self._stream_badge = QLabel("OFFLINE")
        self._stream_badge.setStyleSheet(
            "background:#1e293b;color:#64748b;border-radius:6px;"
            "font-size:12px;font-weight:700;padding:4px 14px;letter-spacing:.06em;"
        )
        live_row.addWidget(self._stream_badge)
        live_row.addStretch(1)

        self._live_btn = QPushButton("▶  Go Live")
        self._live_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:#fff;border:none;border-radius:6px;"
            "padding:7px 18px;font-weight:700;font-size:13px;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#1e293b;color:#64748b;}"
        )
        self._live_btn.clicked.connect(self._go_live)

        self._end_btn = QPushButton("■  End Stream")
        self._end_btn.setStyleSheet(
            "QPushButton{background:#dc2626;color:#fff;border:none;border-radius:6px;"
            "padding:7px 18px;font-weight:700;font-size:13px;}"
            "QPushButton:hover{background:#b91c1c;}"
            "QPushButton:disabled{background:#1e293b;color:#64748b;}"
        )
        self._end_btn.setEnabled(False)
        self._end_btn.clicked.connect(self._end_stream)
        live_row.addWidget(self._live_btn)
        live_row.addWidget(self._end_btn)
        sl.addLayout(live_row)
        root.addWidget(status_card)

        # Stream info editor
        info_card = QFrame(inner)
        info_card.setObjectName("Card")
        il = QVBoxLayout(info_card)
        il.setContentsMargins(20, 16, 20, 16)
        il.setSpacing(14)
        il.addWidget(QLabel("Stream Info", objectName="CardTitle"))
        il.addWidget(_hint(
            "Changes are only saved to Twitch when you click Update. "
            "Title and category update live mid-stream too."
        ))

        il.addWidget(QLabel("Stream Title", objectName="MetaText"))
        self._title_input = QLineEdit()
        self._title_input.setObjectName("ChatSendInput")
        self._title_input.setPlaceholderText("Enter your stream title…")
        il.addWidget(self._title_input)

        notif_header = QHBoxLayout()
        notif_header.addWidget(QLabel("Go Live Notification", objectName="MetaText"))
        notif_header.addStretch(1)
        self._notif_counter = QLabel("0/140")
        self._notif_counter.setObjectName("MetaText")
        notif_header.addWidget(self._notif_counter)
        il.addLayout(notif_header)
        il.addWidget(_hint("Shown to followers when you go live. Stored locally — set this on Twitch too if you want the native notification."))
        self._notif_input = QTextEdit()
        self._notif_input.setObjectName("ChatSendInput")
        self._notif_input.setPlaceholderText("e.g. Wanna watch a colorblind man paint tiny models. Feel free to join.")
        self._notif_input.setFixedHeight(72)
        self._notif_input.setPlainText(self._plugin.repo.get("go_live_notification") or "")
        self._notif_input.textChanged.connect(self._on_notif_changed)
        il.addWidget(self._notif_input)

        il.addWidget(QLabel("Category / Game", objectName="MetaText"))
        cat_row = QHBoxLayout()
        self._cat_input = QLineEdit()
        self._cat_input.setObjectName("ChatSendInput")
        self._cat_input.setPlaceholderText("Search Twitch categories…")
        self._cat_clear_btn = QPushButton("✕")
        self._cat_clear_btn.setObjectName("SecondaryButton")
        self._cat_clear_btn.setFixedWidth(32)
        self._cat_clear_btn.clicked.connect(self._clear_category)
        cat_row.addWidget(self._cat_input, 1)
        cat_row.addWidget(self._cat_clear_btn)
        il.addLayout(cat_row)

        # Inline results panel — no popup window, no macOS transparency issues.
        self._cat_results = QFrame()
        self._cat_results.setObjectName("Card")
        self._cat_results.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cat_results_layout = QVBoxLayout(self._cat_results)
        self._cat_results_layout.setContentsMargins(4, 4, 4, 4)
        self._cat_results_layout.setSpacing(1)
        self._cat_results.hide()
        il.addWidget(self._cat_results)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._do_search)
        self._cat_input.textChanged.connect(self._on_cat_text_changed)

        il.addWidget(_hint("Viewer counts show live totals from the top streams in that category."))

        il.addWidget(QLabel("Tags", objectName="MetaText"))
        il.addWidget(_hint("Up to 10 tags, comma-separated. Tags help viewers find your stream."))
        self._tags_input = QLineEdit()
        self._tags_input.setObjectName("ChatSendInput")
        self._tags_input.setPlaceholderText("e.g. FPS, Competitive, English…")
        il.addWidget(self._tags_input)

        il.addWidget(QLabel("Stream Language", objectName="MetaText"))
        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("ChatSendInput")
        for code, name in _LANGUAGES:
            self._lang_combo.addItem(name, code)
        il.addWidget(self._lang_combo)

        self._update_btn = QPushButton("Update Stream Info")
        self._update_btn.setObjectName("PrimaryButton")
        self._update_btn.setMinimumWidth(160)
        self._update_btn.clicked.connect(self._update_info)
        self._update_status = QLabel("")
        self._update_status.setObjectName("MetaText")
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._update_btn)
        btn_row.addWidget(self._update_status, 1)
        il.addLayout(btn_row)
        root.addWidget(info_card)
        root.addStretch(1)
        return scroll

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

        auth_card = QFrame(inner)
        auth_card.setObjectName("Card")
        al = QVBoxLayout(auth_card)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(12)
        al.addWidget(QLabel("Twitch Authorization", objectName="CardTitle"))
        al.addWidget(_hint(
            "Stream Info needs the channel:manage:broadcast scope to update your stream title "
            "and category. Uses the same Client ID as Chat Manager."
        ))

        form = QGridLayout()
        form.setSpacing(8)
        form.addWidget(QLabel("Client ID"), 0, 0)
        self._client_id_input = QLineEdit(self._plugin.repo.get("client_id") or "")
        self._client_id_input.setObjectName("ChatSendInput")
        self._client_id_input.setPlaceholderText("Twitch Client ID")
        self._client_id_input.textChanged.connect(
            lambda t: self._plugin.repo.set("client_id", t.strip())
        )
        form.addWidget(self._client_id_input, 0, 1)
        al.addLayout(form)

        token = self._plugin.repo.get("oauth_token") or ""
        self._auth_status = QLabel("✓ Authorized" if token else "Not authorized")
        self._auth_status.setObjectName("MetaText")
        self._auth_status.setStyleSheet("color:#22c55e;" if token else "color:#64748b;")
        al.addWidget(self._auth_status)

        auth_row = QHBoxLayout()
        auth_btn = QPushButton("Authorize with Twitch")
        auth_btn.setObjectName("PrimaryButton")
        auth_btn.setMinimumWidth(180)
        auth_btn.clicked.connect(self._start_auth)
        revoke_btn = QPushButton("Revoke")
        revoke_btn.setObjectName("SecondaryButton")
        revoke_btn.clicked.connect(self._revoke)
        auth_row.addWidget(auth_btn)
        auth_row.addWidget(revoke_btn)
        auth_row.addStretch(1)
        al.addLayout(auth_row)
        root.addWidget(auth_card)

        obs_card = QFrame(inner)
        obs_card.setObjectName("Card")
        ol = QVBoxLayout(obs_card)
        ol.setContentsMargins(20, 16, 20, 16)
        ol.setSpacing(10)
        ol.addWidget(QLabel("OBS Connection (for Go Live / End Stream)", objectName="CardTitle"))
        ol.addWidget(_hint(
            "Uses the same OBS credentials as Scene Manager by default. "
            "Override here only if different."
        ))
        obs_form = QGridLayout()
        obs_form.setSpacing(8)
        obs_form.addWidget(QLabel("Host"), 0, 0)
        self._obs_host_input = QLineEdit(self._plugin.repo.get("obs_host") or "")
        self._obs_host_input.setObjectName("ChatSendInput")
        self._obs_host_input.setPlaceholderText("localhost (default)")
        self._obs_host_input.textChanged.connect(
            lambda t: self._plugin.repo.set("obs_host", t.strip())
        )
        obs_form.addWidget(self._obs_host_input, 0, 1)
        obs_form.addWidget(QLabel("Port"), 1, 0)
        self._obs_port_input = QLineEdit(str(self._plugin.repo.get("obs_port") or ""))
        self._obs_port_input.setObjectName("ChatSendInput")
        self._obs_port_input.setPlaceholderText("4455 (default)")
        self._obs_port_input.textChanged.connect(
            lambda t: self._plugin.repo.set("obs_port", t.strip())
        )
        obs_form.addWidget(self._obs_port_input, 1, 1)
        obs_form.addWidget(QLabel("Password"), 2, 0)
        self._obs_pw_input = QLineEdit(self._plugin.repo.get("obs_password") or "")
        self._obs_pw_input.setObjectName("ChatSendInput")
        self._obs_pw_input.setEchoMode(QLineEdit.Password)
        self._obs_pw_input.setPlaceholderText("OBS WebSocket password")
        self._obs_pw_input.textChanged.connect(
            lambda t: self._plugin.repo.set("obs_password", t.strip())
        )
        obs_form.addWidget(self._obs_pw_input, 2, 1)
        ol.addLayout(obs_form)
        root.addWidget(obs_card)
        root.addStretch(1)
        return scroll

    # ── state ─────────────────────────────────────────────────────────────────

    def _on_state(self, state: "InfoState") -> None:
        from stream_controller.plugins.stream_info.info_models import (
            ConnectionStatus, StreamStatus
        )
        dot_c = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color:{dot_c.get(state.twitch_status,'#64748b')};font-size:16px;")

        lbl = {
            ConnectionStatus.CONNECTED:    f"Connected as {state.username}" if state.username else "Connected",
            ConnectionStatus.CONNECTING:   "Connecting…",
            ConnectionStatus.DISCONNECTED: "Not connected",
            ConnectionStatus.ERROR:        f"Error: {state.error[:80]}",
        }
        self._status_lbl.setText(lbl.get(state.twitch_status, ""))

        connected = state.twitch_status == ConnectionStatus.CONNECTED
        self._conn_btn.setVisible(not connected)
        self._disconn_btn.setVisible(connected)

        # Stream badge
        if state.stream_status == StreamStatus.LIVE:
            self._stream_badge.setText("🔴 LIVE")
            self._stream_badge.setStyleSheet(
                "background:#7f1d1d;color:#fca5a5;border-radius:6px;"
                "font-size:12px;font-weight:700;padding:4px 14px;letter-spacing:.06em;"
            )
        elif state.stream_status in (StreamStatus.STARTING, StreamStatus.STOPPING):
            self._stream_badge.setText("⏳  …")
            self._stream_badge.setStyleSheet(
                "background:#1c1917;color:#f59e0b;border-radius:6px;"
                "font-size:12px;font-weight:700;padding:4px 14px;"
            )
        else:
            self._stream_badge.setText("OFFLINE")
            self._stream_badge.setStyleSheet(
                "background:#1e293b;color:#64748b;border-radius:6px;"
                "font-size:12px;font-weight:700;padding:4px 14px;letter-spacing:.06em;"
            )

        live = state.stream_status == StreamStatus.LIVE
        busy = state.stream_status in (StreamStatus.STARTING, StreamStatus.STOPPING)
        self._live_btn.setEnabled(connected and not live and not busy)
        self._end_btn.setEnabled(connected and live and not busy)

        notif_text = self._notif_input.toPlainText()
        self._notif_counter.setText(f"{len(notif_text)}/140")
        if not self._title_input.hasFocus():
            self._title_input.setText(state.info.title)
        if not self._cat_input.hasFocus():
            self._cat_input.blockSignals(True)
            self._cat_input.setText(state.info.category_name)
            self._cat_input.blockSignals(False)
            self._pending_cat_id = state.info.category_id
        if not self._tags_input.hasFocus():
            self._tags_input.setText(", ".join(state.info.tags))
        lang = state.info.language or "en"
        idx = self._lang_combo.findData(lang)
        if idx < 0:
            idx = self._lang_combo.findData("other")
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

    # ── actions ───────────────────────────────────────────────────────────────

    def _on_notif_changed(self) -> None:
        text = self._notif_input.toPlainText()
        if len(text) > 140:
            cursor = self._notif_input.textCursor()
            self._notif_input.setPlainText(text[:140])
            self._notif_input.setTextCursor(cursor)
            text = text[:140]
        self._notif_counter.setText(f"{len(text)}/140")
        self._plugin.repo.set("go_live_notification", text)

    def _connect(self) -> None:
        self._plugin.do_connect()

    def _disconnect(self) -> None:
        self._plugin.do_disconnect()

    def _go_live(self) -> None:
        self._plugin.go_live(self._notif_input.toPlainText().strip())

    def _end_stream(self) -> None:
        self._plugin.end_stream(self._title_input.text())

    def _update_info(self) -> None:
        tags = [t.strip() for t in self._tags_input.text().split(",") if t.strip()]
        language = self._lang_combo.currentData() or "en"
        self._plugin.update_info(self._title_input.text(), self._pending_cat_id, tags, language)
        self._update_status.setText("Updating…")
        self._update_status.setStyleSheet("color:#f59e0b;")
        QTimer.singleShot(2000, lambda: self._update_status.setText(""))

    def _on_cat_text_changed(self, text: str) -> None:
        if len(text.strip()) >= 2:
            self._search_timer.start()
        else:
            self._search_timer.stop()
            self._cat_results.hide()

    def _do_search(self) -> None:
        q = self._cat_input.text().strip()
        if len(q) >= 2:
            self._plugin.search_categories(q, self._sigs.search_results.emit)

    def _on_search_results(self, results: list) -> None:
        # Clear old rows
        while self._cat_results_layout.count():
            item = self._cat_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            self._cat_results.hide()
            return

        for r in results:
            name = r.get("name", "")
            gid  = r.get("id", "")
            vc   = r.get("viewer_count", 0)

            row = QPushButton()
            row.setFlat(True)
            row.setCursor(Qt.PointingHandCursor)
            left = name
            right = _fmt_viewers(vc) if vc > 0 else ""
            row.setText(f"{left}   {right}" if right else left)
            row.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px 10px; border-radius: 6px;"
                " color: #f0f0ff; background: transparent; }"
                "QPushButton:hover { background: rgba(255,255,255,0.1); }"
            )
            row.clicked.connect(lambda _checked, n=name, g=gid: self._on_category_selected(n, g))
            self._cat_results_layout.addWidget(row)

        self._cat_results.show()

    def _on_category_selected(self, name: str, gid: str) -> None:
        self._pending_cat_id = gid
        self._cat_input.blockSignals(True)
        self._cat_input.setText(name)
        self._cat_input.blockSignals(False)
        self._cat_results.hide()

    def _clear_category(self) -> None:
        self._cat_input.blockSignals(True)
        self._cat_input.clear()
        self._cat_input.blockSignals(False)
        self._pending_cat_id = ""
        self._cat_results.hide()

    def _start_auth(self) -> None:
        from stream_controller.plugins.stream_info.twitch_auth import InfoAuthFlow
        cid = self._client_id_input.text().strip()
        if not cid:
            self._auth_status.setText("Enter a Client ID first.")
            self._auth_status.setStyleSheet("color:#ef4444;")
            return
        self._auth_status.setText("Opening browser…")
        self._auth_status.setStyleSheet("color:#f59e0b;")
        self._auth_flow = InfoAuthFlow(
            client_id=cid,
            on_complete=self._on_auth_ok,
            on_error=self._on_auth_err,
        )
        self._auth_flow.start()

    def _on_auth_ok(self, token: str, username: str) -> None:
        self._sigs.auth_ok.emit(token, username)

    def _apply_auth(self, token: str, username: str) -> None:
        self._plugin.repo.set("oauth_token", token)
        self._plugin.repo.set("auto_connect", True)
        self._auth_status.setText(f"✓ Authorized as {username}" if username else "✓ Authorized")
        self._auth_status.setStyleSheet("color:#22c55e;")
        self._plugin.do_connect()

    def _on_auth_err(self, msg: str) -> None:
        self._sigs.auth_err.emit(msg)

    def _show_auth_error(self, msg: str) -> None:
        self._auth_status.setText(f"Error: {msg}")
        self._auth_status.setStyleSheet("color:#ef4444;")

    def _revoke(self) -> None:
        self._plugin.repo.set("oauth_token", "")
        self._auth_status.setText("Not authorized")
        self._auth_status.setStyleSheet("color:#64748b;")
