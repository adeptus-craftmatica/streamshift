from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLayout, QPushButton, QWidget


def clear_layout(layout: QLayout) -> None:
    """Remove and schedule for deletion every item in *layout* recursively."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


def copy_with_feedback(btn: QPushButton, text: str, *, revert_ms: int = 1500) -> None:
    """Copy *text* to clipboard and briefly show '✓ Copied' on *btn*."""
    QGuiApplication.clipboard().setText(text)
    original = btn.text()
    btn.setText("✓ Copied")
    btn.setEnabled(False)
    QTimer.singleShot(revert_ms, lambda: (btn.setText(original), btn.setEnabled(True)))
