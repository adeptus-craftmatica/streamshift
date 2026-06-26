from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout


def stylesheet_path() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "styles" / "app.qss"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    available_fonts = set(QFontDatabase.families())
    preferred_families = ("Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI", "Arial")
    family = next((name for name in preferred_families if name in available_fonts), "Arial")
    app.setFont(QFont(family, 10))
    app.setStyleSheet(stylesheet_path().read_text(encoding="utf-8"))


def create_card(
    title: str | None = None,
    description: str | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(12)

    if title:
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

    if description:
        description_label = QLabel(description)
        description_label.setObjectName("CardDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

    body_layout = QVBoxLayout()
    body_layout.setSpacing(12)
    layout.addLayout(body_layout)

    return frame, body_layout


def create_badge(text: str, tone: str = "neutral") -> QLabel:
    badge = QLabel(text)
    badge.setProperty("badgeTone", tone)
    badge.setAlignment(Qt.AlignCenter)
    return badge
