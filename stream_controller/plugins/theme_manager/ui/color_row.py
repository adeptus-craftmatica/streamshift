from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QWidget,
)


class ColorRow(QWidget):
    """
    A single color-editing row: label | swatch button | hex input.
    Emits `changed(hex_str)` whenever the color is updated.
    """
    changed = Signal(str)   # hex color without #

    def __init__(self, label: str, initial_hex: str = "7c3aed", parent=None) -> None:
        super().__init__(parent)
        self._hex = initial_hex.lstrip("#")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        lbl = QLabel(label)
        lbl.setObjectName("MusicFieldLabel")
        lbl.setFixedWidth(160)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        self._swatch = QPushButton()
        self._swatch.setFixedSize(32, 24)
        self._swatch.setObjectName("ColorSwatch")
        self._swatch.clicked.connect(self._pick)
        layout.addWidget(self._swatch)

        self._edit = QLineEdit(self._hex)
        self._edit.setObjectName("OverlayTextField")
        self._edit.setFixedWidth(90)
        self._edit.setMaxLength(7)
        self._edit.textChanged.connect(self._on_text)
        layout.addWidget(self._edit)

        # Preview swatch (after the input — shows mixed bg)
        self._preview = QFrame()
        self._preview.setFixedSize(48, 24)
        self._preview.setStyleSheet("border-radius: 4px;")
        layout.addWidget(self._preview)

        layout.addStretch(1)
        self._refresh_swatch()

    def hex_value(self) -> str:
        return self._hex

    def set_value(self, hex_color: str) -> None:
        h = hex_color.lstrip("#")
        self._hex = h
        self._edit.blockSignals(True)
        self._edit.setText(h)
        self._edit.blockSignals(False)
        self._refresh_swatch()

    def _pick(self) -> None:
        try:
            current = QColor(f"#{self._hex}")
        except Exception:
            current = QColor("#7c3aed")
        color = QColorDialog.getColor(current if current.isValid() else QColor("#7c3aed"),
                                      self, "Choose color",
                                      QColorDialog.ShowAlphaChannel)
        if color.isValid():
            new_hex = color.name().lstrip("#")
            self._hex = new_hex
            self._edit.blockSignals(True)
            self._edit.setText(new_hex)
            self._edit.blockSignals(False)
            self._refresh_swatch()
            self.changed.emit(new_hex)

    def _on_text(self, text: str) -> None:
        h = text.strip().lstrip("#")
        color = QColor(f"#{h}")
        if color.isValid() and len(h) in (6, 8):
            self._hex = h
            self._refresh_swatch()
            self.changed.emit(h)

    def _refresh_swatch(self) -> None:
        c = QColor(f"#{self._hex}")
        if c.isValid():
            self._swatch.setStyleSheet(
                f"QPushButton#ColorSwatch {{ background:{c.name()}; border:2px solid rgba(255,255,255,0.2); border-radius:5px; }}"
                f"QPushButton#ColorSwatch:hover {{ border-color:rgba(255,255,255,0.5); }}"
            )
            self._preview.setStyleSheet(
                f"QFrame {{ background:{c.name()}; border-radius:4px; border:1px solid rgba(255,255,255,0.12); }}"
            )
