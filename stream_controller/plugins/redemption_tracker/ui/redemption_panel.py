from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.redemption_tracker.redemption_client import RedemptionClient
    from stream_controller.plugins.redemption_tracker.redemption_models import QueueItem
    from stream_controller.plugins.redemption_tracker.redemption_store import RedemptionStore

_KIND_ICON = {"redemption": "🎁", "bits": "💎"}
_KIND_COLOR = {"redemption": "#a78bfa", "bits": "#38bdf8"}


class RedemptionPanel(QFrame):
    """Compact stage panel — shows pending redemptions and bit cheers."""

    _refresh_sig = Signal()

    def __init__(
        self,
        store: "RedemptionStore",
        client: "RedemptionClient",
        fulfil_on_complete: bool = True,
    ) -> None:
        super().__init__()
        self._store              = store
        self._client             = client
        self._fulfil_on_complete = fulfil_on_complete

        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Queue")
        title.setObjectName("CardTitle")
        header.addWidget(title, 1)

        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("MetaText")
        header.addWidget(self._count_lbl)

        clear_btn = QPushButton("Clear done")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet("font-size:11px; padding: 0 8px;")
        clear_btn.clicked.connect(self._clear_completed)
        header.addWidget(clear_btn)

        root.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separator")
        root.addWidget(sep)

        # ── Scroll area ───────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, 1)

        # ── Signals + store subscription ──────────────────────────────────────
        self._refresh_sig.connect(self._rebuild)
        store.add_listener(self._on_store_changed)
        self.destroyed.connect(self._on_destroyed)

        self._rebuild()

    # ── Store callback (background thread) ────────────────────────────────────

    def _on_store_changed(self) -> None:
        self._refresh_sig.emit()

    # ── UI rebuild ────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        layout = self._list_layout
        # Remove all item widgets (leave the trailing stretch)
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pending = self._store.pending()
        self._count_lbl.setText(f"{len(pending)} pending")

        if not pending:
            empty = QLabel("No pending items")
            empty.setObjectName("MetaText")
            empty.setAlignment(Qt.AlignCenter)
            empty.setContentsMargins(0, 16, 0, 16)
            layout.insertWidget(0, empty)
            return

        for idx, item in enumerate(pending):
            layout.insertWidget(idx, self._make_row(item))

    def _make_row(self, item: "QueueItem") -> QWidget:
        row = QFrame()
        row.setObjectName("CardFrame")
        row.setStyleSheet(
            "QFrame#CardFrame { border-radius: 8px; background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.06); }"
        )

        vl = QVBoxLayout(row)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(3)

        # Top row: icon + reward name + viewer + timestamp
        top = QHBoxLayout()
        top.setSpacing(6)

        icon_color = _KIND_COLOR.get(item.kind.value, "#ffffff")
        icon_lbl = QLabel(_KIND_ICON.get(item.kind.value, "•"))
        icon_lbl.setStyleSheet(f"font-size:16px;")
        top.addWidget(icon_lbl)

        reward_lbl = QLabel(item.reward_name)
        reward_lbl.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{icon_color};"
        )
        reward_lbl.setWordWrap(False)
        top.addWidget(reward_lbl, 1)

        if item.amount:
            amt_str = f"{item.amount:,} pts" if item.kind.value == "redemption" else f"{item.amount:,} bits"
            amt_lbl = QLabel(amt_str)
            amt_lbl.setObjectName("MetaText")
            amt_lbl.setStyleSheet("font-size:10px; color: rgba(255,255,255,0.45);")
            top.addWidget(amt_lbl)

        vl.addLayout(top)

        # Viewer name + timestamp
        meta_row = QHBoxLayout()
        meta_row.setSpacing(4)
        viewer_lbl = QLabel(item.viewer_name)
        viewer_lbl.setObjectName("MetaText")
        viewer_lbl.setStyleSheet("font-size:11px; color:rgba(255,255,255,0.6);")
        meta_row.addWidget(viewer_lbl)
        meta_row.addStretch(1)
        if item.timestamp:
            ts_lbl = QLabel(item.timestamp)
            ts_lbl.setStyleSheet("font-size:10px; color:rgba(255,255,255,0.3);")
            meta_row.addWidget(ts_lbl)
        vl.addLayout(meta_row)

        # User input (if any)
        if item.user_input.strip():
            input_lbl = QLabel(f'"{item.user_input.strip()}"')
            input_lbl.setStyleSheet(
                "font-size:11px; color:rgba(255,255,255,0.5); font-style:italic;"
            )
            input_lbl.setWordWrap(True)
            vl.addWidget(input_lbl)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        btn_row.addStretch(1)

        if item.kind.value == "redemption":
            cancel_btn = QPushButton("✕ Cancel")
            cancel_btn.setFixedHeight(22)
            cancel_btn.setStyleSheet(
                "font-size:10px; padding:0 8px; color:#f87171;"
                "background:rgba(248,113,113,0.1); border:1px solid rgba(248,113,113,0.3);"
                "border-radius:4px;"
            )
            cancel_btn.clicked.connect(lambda _, i=item: self._on_cancel(i))
            btn_row.addWidget(cancel_btn)

        done_btn = QPushButton("✓ Complete")
        done_btn.setFixedHeight(22)
        done_btn.setStyleSheet(
            "font-size:10px; padding:0 8px; color:#4ade80;"
            "background:rgba(74,222,128,0.1); border:1px solid rgba(74,222,128,0.3);"
            "border-radius:4px;"
        )
        done_btn.clicked.connect(lambda _, i=item: self._on_complete(i))
        btn_row.addWidget(done_btn)

        vl.addLayout(btn_row)
        return row

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_complete(self, item: "QueueItem") -> None:
        self._store.complete(item.item_id)
        if self._fulfil_on_complete and item.kind.value == "redemption":
            threading.Thread(
                target=self._client.fulfil_redemption,
                args=(item,),
                daemon=True,
                name="fulfil-redemption",
            ).start()

    def _on_cancel(self, item: "QueueItem") -> None:
        self._store.cancel(item.item_id)
        if item.kind.value == "redemption":
            threading.Thread(
                target=self._client.cancel_redemption,
                args=(item,),
                daemon=True,
                name="cancel-redemption",
            ).start()

    def _clear_completed(self) -> None:
        self._store.clear_completed()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_destroyed(self) -> None:
        self._store.remove_listener(self._on_store_changed)
