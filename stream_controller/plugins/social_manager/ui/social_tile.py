from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.social_manager.plugin import SocialManagerPlugin
    from stream_controller.plugins.social_manager.social_repository import SocialRepository
    from stream_controller.plugins.social_manager.bluesky_client import BlueSkyClient


class _TileSig(QObject):
    done = Signal(bool, str)


class SocialTile(QWidget):
    """Quick-post card for the Stage View."""

    def __init__(
        self,
        plugin: "SocialManagerPlugin",
        repo: "SocialRepository",
        client: "BlueSkyClient",
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._repo = repo
        self._client = client
        self._sig = _TileSig(self)
        self._sig.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Social")
        title.setObjectName("PanelTitle")
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(14)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self._status_dot)
        lay.addLayout(title_row)

        self._tmpl_combo = QComboBox()
        self._tmpl_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self._tmpl_combo)

        self._post_btn = QPushButton("Post Now")
        self._post_btn.setObjectName("PrimaryButton")
        self._post_btn.clicked.connect(self._quick_post)
        lay.addWidget(self._post_btn)

        self._feedback_lbl = QLabel()
        self._feedback_lbl.setObjectName("MetaText")
        self._feedback_lbl.setAlignment(Qt.AlignCenter)
        self._feedback_lbl.setWordWrap(True)
        self._feedback_lbl.hide()
        lay.addWidget(self._feedback_lbl)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(3000)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._refresh()

    def _refresh(self) -> None:
        connected = self._client.connected
        self._status_dot.setStyleSheet(
            "color:#4ade80;" if connected else "color:#f87171;"
        )
        self._status_dot.setToolTip(
            f"Bluesky: connected as @{self._client.handle}" if connected else "Bluesky: not connected"
        )

        # Refresh template list without flicker
        self._tmpl_combo.blockSignals(True)
        current = self._tmpl_combo.currentData()
        self._tmpl_combo.clear()
        for t in self._repo.list_templates():
            self._tmpl_combo.addItem(t.get("name", "Untitled"), t.get("id", ""))
        idx = self._tmpl_combo.findData(current)
        if idx >= 0:
            self._tmpl_combo.setCurrentIndex(idx)
        self._tmpl_combo.blockSignals(False)

    def _quick_post(self) -> None:
        if not self._client.connected:
            self._show_feedback("Not connected to Bluesky.", error=True)
            return
        tid = self._tmpl_combo.currentData()
        tmpl = self._repo.get_template(tid)
        if not tmpl:
            self._show_feedback("No template selected.", error=True)
            return
        text = self._plugin.resolve_template(tmpl.get("text", ""))
        image = tmpl.get("image_path", "")
        if not text.strip():
            self._show_feedback("Template text is empty.", error=True)
            return

        self._post_btn.setEnabled(False)
        self._show_feedback("Posting…", error=False)

        def _worker():
            try:
                from pathlib import Path
                if image and Path(image).exists():
                    self._client.post_with_image(text, image)
                else:
                    self._client.post_text(text)
                self._sig.done.emit(True, "Posted! ✓")
            except Exception as exc:
                self._sig.done.emit(False, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self, success: bool, msg: str) -> None:
        self._post_btn.setEnabled(True)
        self._show_feedback(msg, error=not success)

    def _show_feedback(self, msg: str, *, error: bool) -> None:
        colour = "#f87171" if error else "#4ade80"
        self._feedback_lbl.setStyleSheet(f"color:{colour};")
        self._feedback_lbl.setText(msg)
        self._feedback_lbl.show()
        if not error:
            QTimer.singleShot(4000, self._feedback_lbl.hide)
