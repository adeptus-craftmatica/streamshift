from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
)

_LANGUAGES = [
    ("en", "English"), ("fr", "French"), ("de", "German"), ("es", "Spanish"),
    ("pt", "Portuguese"), ("it", "Italian"), ("nl", "Dutch"), ("pl", "Polish"),
    ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese"),
    ("sv", "Swedish"), ("no", "Norwegian"), ("da", "Danish"), ("fi", "Finnish"),
    ("tr", "Turkish"), ("ar", "Arabic"), ("other", "Other"),
]

if TYPE_CHECKING:
    from stream_controller.plugins.stream_info.plugin import StreamInfoPlugin


class _TileSignals(QObject):
    search_results = Signal(object)  # list[dict] — marshals callback to main thread


class InfoTile(QFrame):
    """
    Compact Stream Info tile for Stage View and dashboard.
    Shows title + category, inline-editable, with Update / Go Live / End Stream buttons.
    """

    def __init__(self, plugin: "StreamInfoPlugin") -> None:
        super().__init__()
        self._plugin = plugin
        self.setObjectName("InfoTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        hdr_lbl = QLabel("Stream Info")
        hdr_lbl.setObjectName("CardTitle")
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b;")
        header.addWidget(hdr_lbl, 1)
        header.addWidget(self._dot)
        root.addLayout(header)

        # Stream status badge
        self._stream_badge = QLabel("OFFLINE")
        self._stream_badge.setObjectName("StreamBadgeOffline")
        self._stream_badge.setAlignment(Qt.AlignCenter)
        self._stream_badge.setStyleSheet(
            "background:#1e293b;color:#64748b;border-radius:4px;"
            "font-size:11px;font-weight:700;padding:2px 10px;letter-spacing:.06em;"
        )
        root.addWidget(self._stream_badge)

        # Title field
        root.addWidget(QLabel("Title", objectName="MetaText"))
        self._title_input = QLineEdit()
        self._title_input.setObjectName("ChatSendInput")
        self._title_input.setPlaceholderText("Stream title…")
        root.addWidget(self._title_input)

        # Go Live Notification
        notif_header = QHBoxLayout()
        notif_header.addWidget(QLabel("Go Live Notification", objectName="MetaText"))
        notif_header.addStretch(1)
        self._notif_counter = QLabel("0/140")
        self._notif_counter.setObjectName("MetaText")
        notif_header.addWidget(self._notif_counter)
        root.addLayout(notif_header)
        self._notif_input = QTextEdit()
        self._notif_input.setObjectName("ChatSendInput")
        self._notif_input.setPlaceholderText("Go live notification message…")
        self._notif_input.setFixedHeight(60)
        self._notif_input.setPlainText(plugin.repo.get("go_live_notification") or "")
        self._notif_input.textChanged.connect(self._on_notif_changed)
        root.addWidget(self._notif_input)

        # Category field
        root.addWidget(QLabel("Category", objectName="MetaText"))
        self._cat_input = QLineEdit()
        self._cat_input.setObjectName("ChatSendInput")
        self._cat_input.setPlaceholderText("Search category…")
        self._cat_id: str = ""

        # Debounce search
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._do_search)
        self._cat_input.textChanged.connect(lambda _: self._search_timer.start())

        self._completer = QCompleter([], self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._on_category_selected)
        self._cat_input.setCompleter(self._completer)
        self._cat_map: dict[str, str] = {}
        root.addWidget(self._cat_input)

        # Tags field
        root.addWidget(QLabel("Tags", objectName="MetaText"))
        self._tags_input = QLineEdit()
        self._tags_input.setObjectName("ChatSendInput")
        self._tags_input.setPlaceholderText("Comma-separated tags…")
        root.addWidget(self._tags_input)

        # Language
        root.addWidget(QLabel("Language", objectName="MetaText"))
        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("ChatSendInput")
        for code, name in _LANGUAGES:
            self._lang_combo.addItem(name, code)
        root.addWidget(self._lang_combo)

        # Update button
        self._update_btn = QPushButton("Update Stream Info")
        self._update_btn.setObjectName("PrimaryButton")
        self._update_btn.clicked.connect(self._update)
        root.addWidget(self._update_btn)

        # Go Live / End Stream
        live_row = QHBoxLayout()
        self._live_btn = QPushButton("▶  Go Live")
        self._live_btn.setObjectName("PrimaryButton")
        self._live_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:#fff;border:none;border-radius:6px;padding:6px 12px;font-weight:600;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#1e293b;color:#64748b;}"
        )
        self._live_btn.clicked.connect(self._go_live)

        self._end_btn = QPushButton("■  End Stream")
        self._end_btn.setObjectName("SecondaryButton")
        self._end_btn.setStyleSheet(
            "QPushButton{background:#dc2626;color:#fff;border:none;border-radius:6px;padding:6px 12px;font-weight:600;}"
            "QPushButton:hover{background:#b91c1c;}"
            "QPushButton:disabled{background:#1e293b;color:#64748b;}"
        )
        self._end_btn.setEnabled(False)
        self._end_btn.clicked.connect(self._end_stream)
        live_row.addWidget(self._live_btn)
        live_row.addWidget(self._end_btn)
        root.addLayout(live_row)

        root.addStretch(1)

        self._sigs = _TileSignals()
        self._sigs.search_results.connect(self._on_search_results)

        self._state_cb = self._on_state
        plugin.subscribe(self._state_cb)
        self._on_state(plugin.state)
        self.destroyed.connect(self._on_destroyed)

    # ── state ─────────────────────────────────────────────────────────────────

    def _on_state(self, state) -> None:
        from stream_controller.plugins.stream_info.info_models import (
            ConnectionStatus, StreamStatus
        )
        dot_colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._dot.setStyleSheet(f"color:{dot_colors.get(state.twitch_status, '#64748b')};")

        # Stream badge
        if state.stream_status == StreamStatus.LIVE:
            self._stream_badge.setText("🔴 LIVE")
            self._stream_badge.setStyleSheet(
                "background:#7f1d1d;color:#fca5a5;border-radius:4px;"
                "font-size:11px;font-weight:700;padding:2px 10px;letter-spacing:.06em;"
            )
        elif state.stream_status in (StreamStatus.STARTING, StreamStatus.STOPPING):
            self._stream_badge.setText("⏳ …")
            self._stream_badge.setStyleSheet(
                "background:#1c1917;color:#f59e0b;border-radius:4px;"
                "font-size:11px;font-weight:700;padding:2px 10px;"
            )
        else:
            self._stream_badge.setText("OFFLINE")
            self._stream_badge.setStyleSheet(
                "background:#1e293b;color:#64748b;border-radius:4px;"
                "font-size:11px;font-weight:700;padding:2px 10px;letter-spacing:.06em;"
            )

        connected = state.twitch_status == ConnectionStatus.CONNECTED
        live = state.stream_status == StreamStatus.LIVE
        busy = state.stream_status in (StreamStatus.STARTING, StreamStatus.STOPPING)
        self._live_btn.setEnabled(connected and not live and not busy)
        self._end_btn.setEnabled(connected and live and not busy)

        # Populate fields if not being edited
        self._notif_counter.setText(f"{len(self._notif_input.toPlainText())}/140")
        if not self._title_input.hasFocus():
            self._title_input.setText(state.info.title)
        if not self._cat_input.hasFocus():
            self._cat_input.blockSignals(True)
            self._cat_input.setText(state.info.category_name)
            self._cat_input.blockSignals(False)
            self._cat_id = state.info.category_id
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

    def _update(self) -> None:
        tags = [t.strip() for t in self._tags_input.text().split(",") if t.strip()]
        language = self._lang_combo.currentData() or "en"
        self._plugin.update_info(self._title_input.text(), self._cat_id, tags, language)

    def _go_live(self) -> None:
        self._plugin.go_live(self._notif_input.toPlainText().strip())

    def _end_stream(self) -> None:
        self._plugin.end_stream(self._title_input.text())

    def _do_search(self) -> None:
        q = self._cat_input.text().strip()
        if len(q) >= 2:
            self._plugin.search_categories(q, self._sigs.search_results.emit)

    def _on_search_results(self, results) -> None:
        from PySide6.QtCore import QStringListModel
        self._cat_map = {r["name"]: r["id"] for r in results}
        self._completer.setModel(QStringListModel(list(self._cat_map.keys()), self._completer))
        self._completer.complete()

    def _on_category_selected(self, name: str) -> None:
        self._cat_id = self._cat_map.get(name, "")
        self._cat_input.setText(name)

    def _on_destroyed(self) -> None:
        if self._plugin and self._state_cb:
            self._plugin.unsubscribe(self._state_cb)
