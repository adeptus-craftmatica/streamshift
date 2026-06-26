from __future__ import annotations

"""
Per-source property editor.
Each source type gets its own form widget inside a QStackedWidget.
When the user edits a field, it fires on_changed(SourceConfig).
"""

import os
import subprocess
import sys
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSlider, QSpinBox, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from stream_controller.plugins.scene_designer.designer_models import (
    SOURCE_TYPES, SourceConfig,
)


class SourcePropertiesPanel(QWidget):
    """Right-hand panel — shows a form appropriate for the selected source type."""

    def __init__(self, on_changed: Callable[[SourceConfig], None]) -> None:
        super().__init__()
        self._on_changed = on_changed
        self._source: SourceConfig | None = None
        self._block = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title = QLabel("No source selected")
        self._title.setObjectName("CardTitle")
        self._title.setContentsMargins(16, 14, 16, 10)
        root.addWidget(self._title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separator")
        root.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._scroll = scroll

        self._stack = QStackedWidget()
        self._forms: dict[str, _BaseForm] = {}
        for key in SOURCE_TYPES:
            form = _form_for(key, self._emit)
            self._forms[key] = form
            self._stack.addWidget(form)

        self._empty = QWidget()
        empty_lbl = QLabel("Select a source on the canvas\nto edit its properties.")
        empty_lbl.setObjectName("EmptyState")
        empty_lbl.setAlignment(Qt.AlignCenter)
        empty_lbl.setWordWrap(True)
        QVBoxLayout(self._empty).addWidget(empty_lbl)
        self._stack.addWidget(self._empty)

        scroll.setWidget(self._stack)
        root.addWidget(scroll, 1)

        # Transform section (common to all)
        self._transform_widget = _TransformWidget(self._emit)
        root.addWidget(self._transform_widget)

        self.load(None)

    def load(self, source: SourceConfig | None) -> None:
        self._source = source
        self._block = True
        if source is None:
            self._title.setText("No source selected")
            self._stack.setCurrentWidget(self._empty)
            self._transform_widget.setVisible(False)
        else:
            info = SOURCE_TYPES.get(source.source_type, {})
            self._title.setText(f"{info.get('icon', '')}  {source.name}")
            form = self._forms.get(source.source_type, self._empty)
            form.load(source)
            self._stack.setCurrentWidget(form)
            self._transform_widget.load(source)
            self._transform_widget.setVisible(True)
        self._block = False

    def _emit(self) -> None:
        if self._block or self._source is None:
            return
        # Gather settings from current form
        form = self._forms.get(self._source.source_type)
        if form:
            form.apply(self._source)
        self._transform_widget.apply(self._source)
        self._on_changed(self._source)


# ── transform section ─────────────────────────────────────────────────────────

class _TransformWidget(QFrame):
    def __init__(self, on_changed: Callable) -> None:
        super().__init__()
        self._on_changed = on_changed
        self.setObjectName("Card")
        self.setContentsMargins(0, 0, 0, 0)

        layout = QFormLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        def _spin(min_=0, max_=9999, step=1.0, decimals=0):
            s = QDoubleSpinBox()
            s.setRange(min_, max_)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setObjectName("TimerTransportBtn")
            s.valueChanged.connect(on_changed)
            return s

        self._x = _spin(-9999, 9999, 1, 0)
        self._y = _spin(-9999, 9999, 1, 0)
        self._w = _spin(1, 9999, 1, 0)
        self._h = _spin(1, 9999, 1, 0)
        self._rot = _spin(-360, 360, 1, 1)

        layout.addRow("X", self._x)
        layout.addRow("Y", self._y)
        layout.addRow("W", self._w)
        layout.addRow("H", self._h)
        layout.addRow("Rotation", self._rot)

    def load(self, source: SourceConfig) -> None:
        for spin, val in [
            (self._x, source.x), (self._y, source.y),
            (self._w, source.width), (self._h, source.height),
            (self._rot, source.rotation),
        ]:
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

    def apply(self, source: SourceConfig) -> None:
        source.x = self._x.value()
        source.y = self._y.value()
        source.width = self._w.value()
        source.height = self._h.value()
        source.rotation = self._rot.value()


# ── base form ─────────────────────────────────────────────────────────────────

class _BaseForm(QWidget):
    def __init__(self, on_changed: Callable) -> None:
        super().__init__()
        self._on_changed = on_changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self._layout = layout

    def load(self, source: SourceConfig) -> None:
        pass

    def apply(self, source: SourceConfig) -> None:
        pass

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("MusicFieldLabel")
        return lbl

    def _text_field(self, placeholder: str = "", on_change=None) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("OverlayTextField")
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(on_change or self._on_changed)
        return edit

    def _file_row(self, label: str, filter_: str = "All Files (*)") -> tuple[QLineEdit, QPushButton]:
        edit = QLineEdit()
        edit.setObjectName("OverlayTextField")
        btn = QPushButton("Browse…")
        btn.setObjectName("SecondaryButton")

        def _browse():
            path, _ = QFileDialog.getOpenFileName(self, f"Select {label}", "", filter_)
            if path:
                edit.setText(path)

        btn.clicked.connect(_browse)
        edit.textChanged.connect(self._on_changed)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        self._layout.addWidget(self._field_label(label))
        self._layout.addLayout(row)
        return edit, btn


# ── Image form ─────────────────────────────────────────────────────────────────

class _ImageForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._file, _ = self._file_row("Image File", "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All Files (*)")
        self._layout.addStretch(1)

    def load(self, source):
        self._file.blockSignals(True)
        self._file.setText(source.settings.get("file", ""))
        self._file.blockSignals(False)

    def apply(self, source):
        source.settings["file"] = self._file.text().strip()


# ── Browser form ───────────────────────────────────────────────────────────────

class _BrowserForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("URL"))
        self._url = self._text_field("https://")

        h = QHBoxLayout()
        self._layout.addWidget(self._field_label("Width × Height (px)"))
        self._bw = QSpinBox(); self._bw.setRange(1, 9999); self._bw.setValue(1920)
        self._bh = QSpinBox(); self._bh.setRange(1, 9999); self._bh.setValue(1080)
        self._bw.valueChanged.connect(on_changed)
        self._bh.valueChanged.connect(on_changed)
        for w in (self._bw, self._bh):
            w.setObjectName("TimerTransportBtn")
        h.addWidget(self._bw)
        h.addWidget(QLabel("×"))
        h.addWidget(self._bh)
        h.addStretch(1)
        self._layout.addLayout(h)

        self._layout.addWidget(self._field_label("Custom CSS"))
        self._css = QTextEdit()
        self._css.setObjectName("OverlayTextField")
        self._css.setPlaceholderText("body { ... }")
        self._css.setMaximumHeight(80)
        self._css.textChanged.connect(on_changed)
        self._layout.addWidget(self._css)

        self._fps = QSpinBox(); self._fps.setRange(1, 60); self._fps.setValue(30)
        self._fps.setObjectName("TimerTransportBtn")
        self._fps.valueChanged.connect(on_changed)
        self._layout.addWidget(self._field_label("FPS"))
        self._layout.addWidget(self._fps)

        self._reroute = QCheckBox("Reroute Audio to OBS")
        self._reroute.setObjectName("OverlayCheckBox")
        self._reroute.toggled.connect(on_changed)
        self._layout.addWidget(self._reroute)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        for ctrl, val in [
            (self._url, s.get("url", "")),
            (self._bw, s.get("width", 1920)),
            (self._bh, s.get("height", 1080)),
            (self._fps, s.get("fps", 30)),
        ]:
            ctrl.blockSignals(True)
            if isinstance(ctrl, QLineEdit):
                ctrl.setText(str(val))
            else:
                ctrl.setValue(int(val))
            ctrl.blockSignals(False)
        self._css.blockSignals(True)
        self._css.setPlainText(s.get("css", ""))
        self._css.blockSignals(False)
        self._reroute.blockSignals(True)
        self._reroute.setChecked(bool(s.get("reroute_audio", False)))
        self._reroute.blockSignals(False)

    def apply(self, source):
        source.settings.update({
            "url": self._url.text().strip(),
            "width": self._bw.value(),
            "height": self._bh.value(),
            "css": self._css.toPlainText(),
            "fps": self._fps.value(),
            "reroute_audio": self._reroute.isChecked(),
        })


# ── Text form ──────────────────────────────────────────────────────────────────

class _TextForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Text Content"))
        self._text = QTextEdit()
        self._text.setObjectName("OverlayTextField")
        self._text.setMaximumHeight(80)
        self._text.textChanged.connect(on_changed)
        self._layout.addWidget(self._text)

        h = QHBoxLayout()
        self._layout.addWidget(self._field_label("Font Size"))
        self._size = QSpinBox(); self._size.setRange(6, 500); self._size.setValue(48)
        self._size.setObjectName("TimerTransportBtn")
        self._size.valueChanged.connect(on_changed)
        h.addWidget(self._size)
        h.addStretch(1)
        self._layout.addLayout(h)

        self._layout.addWidget(self._field_label("Color (#RRGGBB)"))
        self._color = self._text_field("#ffffff")

        self._bold = QCheckBox("Bold")
        self._italic = QCheckBox("Italic")
        self._outline = QCheckBox("Outline")
        self._shadow = QCheckBox("Drop Shadow")
        for cb in (self._bold, self._italic, self._outline, self._shadow):
            cb.setObjectName("OverlayCheckBox")
            cb.toggled.connect(on_changed)
        row = QHBoxLayout()
        for cb in (self._bold, self._italic, self._outline, self._shadow):
            row.addWidget(cb)
        row.addStretch(1)
        self._layout.addLayout(row)

        self._layout.addWidget(self._field_label("Alignment"))
        self._align = QComboBox()
        self._align.addItems(["Left", "Center", "Right"])
        self._align.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._align)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        font_settings = s.get("font", {})
        self._text.blockSignals(True)
        self._text.setPlainText(s.get("text", ""))
        self._text.blockSignals(False)
        self._size.blockSignals(True)
        self._size.setValue(font_settings.get("size", 48))
        self._size.blockSignals(False)
        self._color.blockSignals(True)
        self._color.setText(s.get("color_hex", "ffffff"))
        self._color.blockSignals(False)
        align_map = {"left": 0, "center": 1, "right": 2}
        self._align.blockSignals(True)
        self._align.setCurrentIndex(align_map.get(s.get("align", "left"), 0))
        self._align.blockSignals(False)
        for cb, key in [(self._bold, "bold"), (self._italic, "italic"),
                        (self._outline, "outline"), (self._shadow, "drop_shadow")]:
            cb.blockSignals(True)
            cb.setChecked(bool(s.get(key, False)))
            cb.blockSignals(False)

    def apply(self, source):
        align_vals = ["left", "center", "right"]
        source.settings.update({
            "text": self._text.toPlainText(),
            "color_hex": self._color.text().strip().lstrip("#"),
            "font": {
                "face": source.settings.get("font", {}).get("face", "Arial"),
                "size": self._size.value(),
                "style": ("Bold" if self._bold.isChecked() else "") + ("Italic" if self._italic.isChecked() else "") or "Regular",
            },
            "outline": self._outline.isChecked(),
            "drop_shadow": self._shadow.isChecked(),
            "align": align_vals[self._align.currentIndex()],
        })


# ── Color form ─────────────────────────────────────────────────────────────────

class _ColorForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Color (#RRGGBB)"))
        self._color = self._text_field("#1a1a2e")
        self._layout.addStretch(1)

    def load(self, source):
        self._color.blockSignals(True)
        self._color.setText(source.settings.get("color_hex", "1a1a2e"))
        self._color.blockSignals(False)

    def apply(self, source):
        source.settings["color_hex"] = self._color.text().strip().lstrip("#")


# ── Media form ─────────────────────────────────────────────────────────────────

class _MediaForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._file, _ = self._file_row("Media File", "Video/Audio (*.mp4 *.mov *.avi *.mkv *.mp3 *.wav *.flac);;All Files (*)")
        self._loop = QCheckBox("Loop")
        self._restart = QCheckBox("Restart on Activate")
        self._clear = QCheckBox("Clear on End")
        for cb in (self._loop, self._restart, self._clear):
            cb.setObjectName("OverlayCheckBox")
            cb.toggled.connect(on_changed)
        for cb in (self._loop, self._restart, self._clear):
            self._layout.addWidget(cb)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        self._file.blockSignals(True)
        self._file.setText(s.get("local_file", ""))
        self._file.blockSignals(False)
        for cb, key in [(self._loop, "looping"), (self._restart, "restart_on_activate"), (self._clear, "clear_on_media_end")]:
            cb.blockSignals(True)
            cb.setChecked(bool(s.get(key, False)))
            cb.blockSignals(False)

    def apply(self, source):
        source.settings.update({
            "local_file": self._file.text().strip(),
            "looping": self._loop.isChecked(),
            "restart_on_activate": self._restart.isChecked(),
            "clear_on_media_end": self._clear.isChecked(),
        })


# ── Audio Input form ───────────────────────────────────────────────────────────

class _AudioInputForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Audio Device"))
        self._device = QComboBox()
        self._device.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._device)

        btn = QPushButton("Refresh Devices")
        btn.setObjectName("SecondaryButton")
        btn.clicked.connect(self._refresh_devices)
        self._layout.addWidget(btn)

        self._layout.addWidget(self._field_label("Volume"))
        self._vol = QSlider(Qt.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(100)
        self._vol.valueChanged.connect(on_changed)
        self._layout.addWidget(self._vol)

        self._muted = QCheckBox("Muted")
        self._muted.setObjectName("OverlayCheckBox")
        self._muted.toggled.connect(on_changed)
        self._layout.addWidget(self._muted)
        self._layout.addStretch(1)
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        self._device.blockSignals(True)
        self._device.clear()
        self._device.addItem("Default", "default")
        try:
            import sounddevice as sd
            for dev in sd.query_devices():
                if dev["max_input_channels"] > 0:
                    self._device.addItem(dev["name"], dev["name"])
        except Exception:
            pass
        self._device.blockSignals(False)

    def load(self, source):
        dev_id = source.settings.get("device_id", "default")
        idx = self._device.findData(dev_id)
        if idx >= 0:
            self._device.setCurrentIndex(idx)
        self._vol.blockSignals(True)
        self._vol.setValue(int(source.volume * 100))
        self._vol.blockSignals(False)
        self._muted.blockSignals(True)
        self._muted.setChecked(source.muted)
        self._muted.blockSignals(False)

    def apply(self, source):
        source.settings["device_id"] = self._device.currentData() or "default"
        source.volume = self._vol.value() / 100.0
        source.muted = self._muted.isChecked()


# ── Window Capture form ────────────────────────────────────────────────────────

class _WindowCaptureForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Window / Application"))
        self._window = QComboBox()
        self._window.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._window)

        btn = QPushButton("Refresh Windows")
        btn.setObjectName("SecondaryButton")
        btn.clicked.connect(self._refresh_windows)
        self._layout.addWidget(btn)

        self._cursor = QCheckBox("Capture Cursor")
        self._cursor.setObjectName("OverlayCheckBox")
        self._cursor.setChecked(True)
        self._cursor.toggled.connect(on_changed)
        self._layout.addWidget(self._cursor)
        self._layout.addStretch(1)
        self._refresh_windows()

    def _refresh_windows(self) -> None:
        self._window.blockSignals(True)
        self._window.clear()
        self._window.addItem("(none)", "")
        windows = _list_windows()
        for title, ident in windows:
            self._window.addItem(title, ident)
        self._window.blockSignals(False)

    def load(self, source):
        ident = source.settings.get("window", "")
        idx = self._window.findData(ident)
        if idx >= 0:
            self._window.setCurrentIndex(idx)
        self._cursor.blockSignals(True)
        self._cursor.setChecked(source.settings.get("capture_cursor", True))
        self._cursor.blockSignals(False)

    def apply(self, source):
        source.settings["window"] = self._window.currentData() or ""
        source.settings["capture_cursor"] = self._cursor.isChecked()


# ── Display Capture form ───────────────────────────────────────────────────────

class _DisplayCaptureForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Display"))
        self._display = QComboBox()
        self._display.currentIndexChanged.connect(on_changed)
        from PySide6.QtWidgets import QApplication
        screens = QApplication.screens()
        for i, screen in enumerate(screens):
            self._display.addItem(f"Display {i+1} — {screen.name()} ({screen.size().width()}×{screen.size().height()})", i)
        self._layout.addWidget(self._display)

        self._cursor = QCheckBox("Capture Cursor")
        self._cursor.setObjectName("OverlayCheckBox")
        self._cursor.setChecked(True)
        self._cursor.toggled.connect(on_changed)
        self._layout.addWidget(self._cursor)
        self._layout.addStretch(1)

    def load(self, source):
        idx = source.settings.get("display", 0)
        if 0 <= idx < self._display.count():
            self._display.setCurrentIndex(idx)
        self._cursor.blockSignals(True)
        self._cursor.setChecked(source.settings.get("capture_cursor", True))
        self._cursor.blockSignals(False)

    def apply(self, source):
        source.settings["display"] = self._display.currentData() or 0
        source.settings["capture_cursor"] = self._cursor.isChecked()


# ── Chat Overlay form ──────────────────────────────────────────────────────────

class _ChatOverlayForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._field_label("Overlay URL"))
        self._url = self._text_field("http://localhost:47892/chat")
        hint = QLabel("The StreamShift chat overlay server runs on port 47892 by default.")
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        self._layout.addWidget(hint)

        h = QHBoxLayout()
        self._layout.addWidget(self._field_label("Width × Height (px)"))
        self._bw = QSpinBox(); self._bw.setRange(1, 9999); self._bw.setValue(400)
        self._bh = QSpinBox(); self._bh.setRange(1, 9999); self._bh.setValue(800)
        for w in (self._bw, self._bh):
            w.setObjectName("TimerTransportBtn")
            w.valueChanged.connect(on_changed)
        h.addWidget(self._bw); h.addWidget(QLabel("×")); h.addWidget(self._bh); h.addStretch(1)
        self._layout.addLayout(h)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        self._url.blockSignals(True)
        self._url.setText(s.get("url", "http://localhost:47892/chat"))
        self._url.blockSignals(False)
        for spin, key, default in [(self._bw, "width", 400), (self._bh, "height", 800)]:
            spin.blockSignals(True)
            spin.setValue(int(s.get(key, default)))
            spin.blockSignals(False)

    def apply(self, source):
        source.settings.update({
            "url": self._url.text().strip(),
            "width": self._bw.value(),
            "height": self._bh.value(),
        })


# ── factory ────────────────────────────────────────────────────────────────────

def _form_for(source_type: str, on_changed: Callable) -> _BaseForm:
    return {
        "image":          _ImageForm,
        "browser":        _BrowserForm,
        "text":           _TextForm,
        "color":          _ColorForm,
        "media":          _MediaForm,
        "audio_input":    _AudioInputForm,
        "window_capture": _WindowCaptureForm,
        "display_capture":_DisplayCaptureForm,
        "chat_overlay":   _ChatOverlayForm,
    }.get(source_type, _BaseForm)(on_changed)


# ── window list helper ─────────────────────────────────────────────────────────

def _list_windows() -> list[tuple[str, str]]:
    """Return (display_name, identifier) for visible windows on the current platform."""
    result = []
    try:
        if sys.platform == "darwin":
            import subprocess
            out = subprocess.check_output(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every process whose background only is false'],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode().strip()
            for name in out.split(", "):
                name = name.strip()
                if name:
                    result.append((name, name))
        elif sys.platform == "win32":
            import ctypes
            import ctypes.wintypes
            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            buf = ctypes.create_unicode_buffer(512)
            titles = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def callback(hwnd, lp):
                if IsWindowVisible(hwnd):
                    GetWindowText(hwnd, buf, 512)
                    title = buf.value.strip()
                    if title:
                        titles.append(title)
                return True

            EnumWindows(callback, 0)
            result = [(t, t) for t in titles]
        else:
            # Linux: try wmctrl, fall back to xdotool
            import subprocess as _sp
            try:
                out = _sp.check_output(["wmctrl", "-l"], stderr=_sp.DEVNULL, timeout=3).decode()
                for line in out.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) >= 4:
                        title = parts[3].strip()
                        if title and title != "N/A":
                            result.append((title, title))
            except FileNotFoundError:
                try:
                    ids = _sp.check_output(["xdotool", "search", "--onlyvisible", "--name", ""],
                                           stderr=_sp.DEVNULL, timeout=3).decode().split()
                    for wid in ids:
                        name = _sp.check_output(["xdotool", "getwindowname", wid],
                                                stderr=_sp.DEVNULL, timeout=1).decode().strip()
                        if name:
                            result.append((name, name))
                except Exception:
                    pass
    except Exception:
        pass
    return result
