from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.plugins.scene_manager.scene_client import SceneClient
    from stream_controller.plugins.scene_manager.scene_models import SceneManagerState

_PREVIEW_W = 320
_PREVIEW_H = 180  # 16:9


class _PreviewSignals(QObject):
    image_ready = Signal(str)  # base64 data-URL


class SceneTile(QFrame):
    """Compact scene-switcher tile — works in deck, dashboard, and Stage View."""

    def __init__(self, client: "SceneClient") -> None:
        super().__init__()
        self._client = client
        self._current_scene: str = ""
        self._preview_sig = _PreviewSignals()
        self._preview_sig.image_ready.connect(self._apply_preview)
        self.setObjectName("SceneTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Scene Manager")
        title.setObjectName("CardTitle")
        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("SceneTileStatusDot")
        self._status_dot.setStyleSheet("color:#64748b;")
        header.addWidget(title, 1)
        header.addWidget(self._status_dot)
        root.addLayout(header)

        # Live preview thumbnail (16:9)
        self._preview_label = QLabel()
        self._preview_label.setObjectName("SceneTilePreview")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumHeight(_PREVIEW_H)
        self._preview_label.setMaximumHeight(_PREVIEW_H)
        self._preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._preview_label.setStyleSheet(
            "background:#0d1117; border:1px solid #1e293b; border-radius:4px;"
        )
        self._preview_label.setText("No preview")
        root.addWidget(self._preview_label)

        # Current scene label
        self._current_label = QLabel("Not connected to OBS")
        self._current_label.setObjectName("SceneTileCurrentLabel")
        self._current_label.setWordWrap(True)
        root.addWidget(self._current_label)

        # Scene buttons container
        self._buttons_layout = QVBoxLayout()
        self._buttons_layout.setSpacing(5)
        root.addLayout(self._buttons_layout, 1)

        # Preview poll timer — fires every 1.5 s when connected
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(1500)
        self._preview_timer.timeout.connect(self._poll_preview)

        self.destroyed.connect(self._on_destroyed)

        if client:
            self._state_cb = self._on_state_changed
            client.subscribe(self._state_cb)
            self._refresh(client.state)
        else:
            self._state_cb = None

    # ── public ────────────────────────────────────────────────────────────────

    def on_state_changed(self, state: "SceneManagerState") -> None:
        self._refresh(state)

    # ── internal ──────────────────────────────────────────────────────────────

    def _on_state_changed(self, state: "SceneManagerState") -> None:
        self._refresh(state)

    def _refresh(self, state) -> None:
        from stream_controller.plugins.scene_manager.scene_models import ConnectionStatus
        colors = {
            ConnectionStatus.CONNECTED:    "#22c55e",
            ConnectionStatus.CONNECTING:   "#f59e0b",
            ConnectionStatus.DISCONNECTED: "#64748b",
            ConnectionStatus.ERROR:        "#ef4444",
        }
        self._status_dot.setStyleSheet(f"color:{colors.get(state.status, '#64748b')};")

        connected = state.status == ConnectionStatus.CONNECTED
        if connected:
            self._current_label.setText(
                f"LIVE: {state.current_scene}" if state.current_scene else "Connected"
            )
            self._current_scene = state.current_scene or ""
            if not self._preview_timer.isActive():
                self._preview_timer.start()
                self._poll_preview()
        elif state.status == ConnectionStatus.CONNECTING:
            self._current_label.setText("Connecting to OBS…")
            self._preview_timer.stop()
            self._preview_label.setText("Connecting…")
        elif state.status == ConnectionStatus.ERROR:
            self._current_label.setText(f"Error: {state.error[:60]}")
            self._preview_timer.stop()
            self._preview_label.setText("No preview")
        else:
            self._current_label.setText("Not connected to OBS")
            self._preview_timer.stop()
            self._preview_label.setText("No preview")
            self._current_scene = ""

        # Update or rebuild scene buttons.
        # Only do a full rebuild if the scene list itself changed (names added/removed).
        # When just the active scene changes we update ObjectNames in-place so that
        # no widgets are destroyed — avoids the macOS focus-steal that happens when
        # a clicked button is deleted mid-event.
        visible_scenes = [s for s in state.scenes if not s.is_group and s.name]
        existing_btns = [
            self._buttons_layout.itemAt(i).widget()
            for i in range(self._buttons_layout.count())
            if isinstance(self._buttons_layout.itemAt(i).widget(), QPushButton)
        ]
        existing_names = [b.text() for b in existing_btns]
        new_names = [s.name for s in visible_scenes]

        if existing_names == new_names:
            # Only active-scene highlight changed — update styles in place.
            for btn, scene in zip(existing_btns, visible_scenes):
                obj = "SceneTileBtnActive" if scene.is_current else "SceneTileBtn"
                if btn.objectName() != obj:
                    btn.setObjectName(obj)
                    btn.style().unpolish(btn)
                    btn.style().polish(btn)
        else:
            # Scene list changed — full rebuild.
            while self._buttons_layout.count():
                item = self._buttons_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            if visible_scenes:
                for scene in visible_scenes:
                    name = scene.name
                    btn = QPushButton(name, self)
                    btn.setObjectName("SceneTileBtnActive" if scene.is_current else "SceneTileBtn")
                    btn.clicked.connect(lambda checked=False, n=name: self._client.switch_scene(n))
                    self._buttons_layout.addWidget(btn)
            else:
                hint = QLabel("Connect to OBS in Scene Manager → Settings", self)
                hint.setObjectName("CardDescription")
                hint.setWordWrap(True)
                self._buttons_layout.addWidget(hint)

    def _poll_preview(self) -> None:
        """Fire a background thread to fetch the OBS screenshot (non-blocking)."""
        scene = self._current_scene
        client = self._client
        sig = self._preview_sig
        if not client or not scene:
            return

        def _fetch():
            data = client.get_preview_screenshot(scene)
            if data:
                sig.image_ready.emit(data)

        threading.Thread(target=_fetch, daemon=True, name="scene-preview").start()

    def _apply_preview(self, data_url: str) -> None:
        """Receive base64 data-URL from background thread and paint the label."""
        try:
            # data_url is "data:image/jpeg;base64,<b64>"
            b64 = data_url.split(",", 1)[-1].encode()
            ba = QByteArray.fromBase64(b64)
            pixmap = QPixmap()
            if pixmap.loadFromData(ba):
                scaled = pixmap.scaled(
                    self._preview_label.width(), _PREVIEW_H,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                self._preview_label.setPixmap(scaled)
        except Exception:
            pass

    def _on_destroyed(self) -> None:
        self._preview_timer.stop()
        if self._client and self._state_cb is not None:
            self._client.unsubscribe(self._state_cb)
            self._state_cb = None
