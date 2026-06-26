from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from stream_controller import __version__


class Sidebar(QWidget):
    page_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(280)

        self._buttons: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        # Outer layout: scroll area expands, version label is pinned at bottom
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scroll area wraps all sidebar content ──────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setObjectName("SidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        inner = QWidget()
        inner.setObjectName("SidebarInner")
        root_layout = QVBoxLayout(inner)
        root_layout.setContentsMargins(24, 24, 20, 16)
        root_layout.setSpacing(20)

        # Brand block
        brand_block = QFrame()
        brand_block.setObjectName("BrandBlock")
        brand_layout = QVBoxLayout(brand_block)
        brand_layout.setContentsMargins(20, 20, 20, 20)
        brand_layout.setSpacing(6)
        brand_title = QLabel("Stream Controller")
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("Stream control surface")
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_subtitle.setWordWrap(True)
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_subtitle)
        root_layout.addWidget(brand_block)

        # Primary nav
        nav_title = QLabel("Navigate")
        nav_title.setObjectName("SidebarSectionTitle")
        root_layout.addWidget(nav_title)

        self._primary_nav_layout = QVBoxLayout()
        self._primary_nav_layout.setSpacing(4)
        root_layout.addLayout(self._primary_nav_layout)

        self._add_nav_button("dashboard", "Dashboard")
        self._add_nav_button("stage_view", "Stage View")
        self._add_nav_button("plugins", "Plugins")
        self._add_nav_button("settings", "Settings")

        # Plugin nav
        plugin_title = QLabel("Plugin Workspaces")
        plugin_title.setObjectName("SidebarSectionTitle")
        root_layout.addWidget(plugin_title)

        self._plugin_nav_layout = QVBoxLayout()
        self._plugin_nav_layout.setSpacing(4)
        root_layout.addLayout(self._plugin_nav_layout)

        self._plugin_placeholder = QLabel("Installed plugin pages appear here automatically.")
        self._plugin_placeholder.setObjectName("SidebarEmptyState")
        self._plugin_placeholder.setWordWrap(True)
        self._plugin_nav_layout.addWidget(self._plugin_placeholder)

        root_layout.addStretch(1)

        self._scroll.setWidget(inner)
        outer.addWidget(self._scroll, 1)

        # ── Version label pinned at bottom, outside scroll ─────────────────────
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("SidebarVersionLabel")
        version_label.setContentsMargins(24, 6, 20, 14)
        outer.addWidget(version_label)

    def add_plugin_page(self, page_id: str, title: str) -> None:
        if page_id in self._buttons:
            return
        self._plugin_placeholder.hide()
        self._add_nav_button(page_id=page_id, title=title, plugin_item=True)

    def remove_plugin_page(self, page_id: str) -> None:
        button = self._buttons.pop(page_id, None)
        if button is None:
            return
        self._button_group.removeButton(button)
        self._plugin_nav_layout.removeWidget(button)
        button.deleteLater()
        if not any(b.property("pluginItem") for b in self._buttons.values()):
            self._plugin_placeholder.show()

    def set_active_page(self, page_id: str) -> None:
        button = self._buttons.get(page_id)
        if button is not None:
            button.setChecked(True)

    def _add_nav_button(self, page_id: str, title: str, plugin_item: bool = False) -> None:
        button = QPushButton(title)
        button.setCheckable(True)
        button.setProperty("navItem", True)
        button.setProperty("pluginItem", plugin_item)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(lambda checked=False, pid=page_id: self.page_requested.emit(pid))

        self._button_group.addButton(button)
        self._buttons[page_id] = button

        target = self._plugin_nav_layout if plugin_item else self._primary_nav_layout
        target.addWidget(button)
