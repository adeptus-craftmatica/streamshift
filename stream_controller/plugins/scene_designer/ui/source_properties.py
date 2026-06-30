from __future__ import annotations

"""
Per-source property editor.
Each source type gets its own form widget inside a QStackedWidget.
When the user edits a field, it fires on_changed(SourceConfig).
"""

import os
import subprocess
import sys
import webbrowser
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
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

        # ── Header: editable name + type badge ───────────────────────────────
        header = QWidget()
        header.setObjectName("SidebarPanel")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 10)
        hl.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("OverlayTextField")
        self._name_edit.setPlaceholderText("Source name…")
        self._name_edit.textChanged.connect(self._on_name_changed)
        hl.addWidget(self._name_edit, 1)

        self._type_badge = QLabel("")
        self._type_badge.setObjectName("CardDescription")
        hl.addWidget(self._type_badge)

        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separator")
        root.addWidget(sep)

        # ── Common section (opacity, visible, locked) ─────────────────────────
        self._common = _CommonWidget(self._emit)
        root.addWidget(self._common)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("Separator")
        root.addWidget(sep2)

        # ── Type-specific form in a scroll area ───────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

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

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setObjectName("Separator")
        root.addWidget(sep3)

        # ── Transform (X Y W H Rotation) always pinned at bottom ─────────────
        self._transform = _TransformWidget(self._emit)
        root.addWidget(self._transform)

        self.load(None)

    def load(self, source: SourceConfig | None) -> None:
        self._source = source
        self._block = True
        if source is None:
            self._name_edit.setText("")
            self._name_edit.setEnabled(False)
            self._type_badge.setText("")
            self._stack.setCurrentWidget(self._empty)
            self._common.setVisible(False)
            self._transform.setVisible(False)
        else:
            info = SOURCE_TYPES.get(source.source_type, {})
            self._name_edit.blockSignals(True)
            self._name_edit.setText(source.name)
            self._name_edit.blockSignals(False)
            self._name_edit.setEnabled(True)
            self._type_badge.setText(f"{info.get('icon','')}")
            self._common.load(source)
            self._common.setVisible(True)
            form = self._forms.get(source.source_type, self._empty)
            form.load(source)
            self._stack.setCurrentWidget(form)
            self._transform.load(source)
            self._transform.setVisible(True)
        self._block = False

    def _on_name_changed(self, text: str) -> None:
        if self._block or self._source is None:
            return
        self._source.name = text.strip() or self._source.name
        self._on_changed(self._source)

    def _emit(self) -> None:
        if self._block or self._source is None:
            return
        form = self._forms.get(self._source.source_type)
        if form:
            form.apply(self._source)
        self._common.apply(self._source)
        self._transform.apply(self._source)
        self._on_changed(self._source)


# ── common section (opacity / visible / locked) ───────────────────────────────

class _CommonWidget(QFrame):
    def __init__(self, on_changed: Callable) -> None:
        super().__init__()
        self._on_changed = on_changed
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        # Opacity row
        op_row = QHBoxLayout()
        op_row.setSpacing(8)
        op_label = QLabel("Opacity")
        op_label.setObjectName("MusicFieldLabel")
        op_label.setFixedWidth(54)
        self._op_slider = QSlider(Qt.Horizontal)
        self._op_slider.setRange(0, 100)
        self._op_slider.setValue(100)
        self._op_slider.valueChanged.connect(self._slider_moved)
        self._op_spin = QSpinBox()
        self._op_spin.setRange(0, 100)
        self._op_spin.setValue(100)
        self._op_spin.setSuffix("%")
        self._op_spin.setFixedWidth(62)
        self._op_spin.setObjectName("TimerTransportBtn")
        self._op_spin.valueChanged.connect(self._spin_moved)
        op_row.addWidget(op_label)
        op_row.addWidget(self._op_slider, 1)
        op_row.addWidget(self._op_spin)
        outer.addLayout(op_row)

        # Visible + Locked row
        flags_row = QHBoxLayout()
        flags_row.setSpacing(16)
        self._visible_chk = QCheckBox("Visible")
        self._visible_chk.setObjectName("OverlayCheckBox")
        self._visible_chk.setChecked(True)
        self._visible_chk.toggled.connect(on_changed)
        self._locked_chk = QCheckBox("Locked")
        self._locked_chk.setObjectName("OverlayCheckBox")
        self._locked_chk.toggled.connect(on_changed)
        flags_row.addWidget(self._visible_chk)
        flags_row.addWidget(self._locked_chk)
        flags_row.addStretch(1)
        outer.addLayout(flags_row)

    def _slider_moved(self, v: int) -> None:
        self._op_spin.blockSignals(True)
        self._op_spin.setValue(v)
        self._op_spin.blockSignals(False)
        self._on_changed()

    def _spin_moved(self, v: int) -> None:
        self._op_slider.blockSignals(True)
        self._op_slider.setValue(v)
        self._op_slider.blockSignals(False)
        self._on_changed()

    def load(self, source: SourceConfig) -> None:
        pct = int(round(source.opacity * 100))
        for w in (self._op_slider, self._op_spin):
            w.blockSignals(True)
            w.setValue(pct)
            w.blockSignals(False)
        self._visible_chk.blockSignals(True)
        self._visible_chk.setChecked(source.visible)
        self._visible_chk.blockSignals(False)
        self._locked_chk.blockSignals(True)
        self._locked_chk.setChecked(source.locked)
        self._locked_chk.blockSignals(False)

    def apply(self, source: SourceConfig) -> None:
        source.opacity  = self._op_slider.value() / 100.0
        source.visible  = self._visible_chk.isChecked()
        source.locked   = self._locked_chk.isChecked()


# ── transform section ─────────────────────────────────────────────────────────

class _TransformWidget(QFrame):
    def __init__(self, on_changed: Callable) -> None:
        super().__init__()
        self._on_changed = on_changed
        self.setObjectName("Card")

        from PySide6.QtWidgets import QFormLayout
        layout = QFormLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        def _spin(min_=0, max_=9999, step=1.0, decimals=0):
            s = QDoubleSpinBox()
            s.setRange(min_, max_)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setObjectName("TimerTransportBtn")
            s.valueChanged.connect(on_changed)
            return s

        self._x   = _spin(-9999, 9999)
        self._y   = _spin(-9999, 9999)
        self._w   = _spin(1, 9999)
        self._h   = _spin(1, 9999)
        self._rot = _spin(-360, 360, 1, 1)

        layout.addRow("X", self._x)
        layout.addRow("Y", self._y)
        layout.addRow("W", self._w)
        layout.addRow("H", self._h)
        layout.addRow("°", self._rot)

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
        source.x        = self._x.value()
        source.y        = self._y.value()
        source.width    = self._w.value()
        source.height   = self._h.value()
        source.rotation = self._rot.value()


# ── base form ─────────────────────────────────────────────────────────────────

class _BaseForm(QWidget):
    def __init__(self, on_changed: Callable) -> None:
        super().__init__()
        self._on_changed = on_changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self._layout = layout

    def load(self, source: SourceConfig) -> None:
        pass

    def apply(self, source: SourceConfig) -> None:
        pass

    def _lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("MusicFieldLabel")
        return lbl

    def _text_field(self, placeholder: str = "", on_change=None) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("OverlayTextField")
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(on_change or self._on_changed)
        return edit

    def _file_row(self, label: str, filter_: str = "All Files (*)") -> QLineEdit:
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
        self._layout.addWidget(self._lbl(label))
        self._layout.addLayout(row)
        return edit

    def _color_row(self, label: str) -> tuple[QLineEdit, QPushButton]:
        """Hex field + color-picker button."""
        edit = QLineEdit()
        edit.setObjectName("OverlayTextField")
        edit.setPlaceholderText("RRGGBB")
        edit.setMaximumWidth(100)
        edit.textChanged.connect(self._on_changed)

        swatch = QPushButton()
        swatch.setFixedSize(32, 28)
        swatch.setObjectName("SecondaryButton")

        def _pick():
            current = QColor(f"#{edit.text().lstrip('#')}") if edit.text() else QColor("#ffffff")
            col = QColorDialog.getColor(current, self, label, QColorDialog.ShowAlphaChannel)
            if col.isValid():
                hex_val = col.name(QColor.HexRgb).lstrip("#")
                edit.setText(hex_val)
                _update_swatch(hex_val)

        def _update_swatch(hex_val: str) -> None:
            try:
                c = QColor(f"#{hex_val}")
                swatch.setStyleSheet(
                    f"QPushButton {{ background:{c.name()}; border:1px solid #444; border-radius:4px; }}"
                )
            except Exception:
                pass

        edit.textChanged.connect(_update_swatch)
        swatch.clicked.connect(_pick)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(edit)
        row.addWidget(swatch)
        row.addStretch(1)
        self._layout.addWidget(self._lbl(label))
        self._layout.addLayout(row)
        return edit, swatch

    def _set_color(self, edit: QLineEdit, swatch: QPushButton, hex_val: str) -> None:
        edit.blockSignals(True)
        edit.setText(hex_val.lstrip("#"))
        edit.blockSignals(False)
        try:
            c = QColor(f"#{hex_val.lstrip('#')}")
            swatch.setStyleSheet(
                f"QPushButton {{ background:{c.name()}; border:1px solid #444; border-radius:4px; }}"
            )
        except Exception:
            pass


# ── Image form ─────────────────────────────────────────────────────────────────

class _ImageForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._file = self._file_row(
            "Image File",
            "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All Files (*)"
        )
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

        self._layout.addWidget(self._lbl("URL or Local File"))
        self._url = QLineEdit()
        self._url.setObjectName("OverlayTextField")
        self._url.setPlaceholderText("https://  or  file:///path/to/page.html")
        self._url.textChanged.connect(on_changed)
        self._layout.addWidget(self._url)

        url_btn_row = QHBoxLayout()
        url_btn_row.setSpacing(6)

        browse_btn = QPushButton("Browse File…")
        browse_btn.setObjectName("SecondaryButton")
        browse_btn.setToolTip("Pick a local HTML file")
        browse_btn.clicked.connect(self._browse_local_file)
        url_btn_row.addWidget(browse_btn, 1)

        self._open_btn = QPushButton("Open ↗")
        self._open_btn.setObjectName("SecondaryButton")
        self._open_btn.setToolTip("Open URL in system browser")
        self._open_btn.clicked.connect(self._open_in_browser)
        url_btn_row.addWidget(self._open_btn)
        self._layout.addLayout(url_btn_row)

        # StreamShift built-in overlays quick-pick
        self._layout.addWidget(self._lbl("StreamShift Overlays"))
        self._overlay_combo = QComboBox()
        self._overlay_combo.setObjectName("OverlayTextField")
        self._overlay_combo.addItem("— pick a built-in overlay —", "")
        for label, url in [
            ("Chat Overlay",           "http://localhost:47892/chat"),
            ("Now Playing",            "http://localhost:47891/now-playing"),
            ("Alert Queue",            "http://localhost:47892/alerts"),
            ("Scene Timer",            "http://localhost:47894/timer"),
            ("Social Feed",            "http://localhost:47892/social"),
            ("PNGtuber",               "http://localhost:47897/pngtuber"),
        ]:
            self._overlay_combo.addItem(label, url)
        self._overlay_combo.currentIndexChanged.connect(self._on_overlay_picked)
        self._layout.addWidget(self._overlay_combo)

        self._layout.addWidget(self._lbl("Width × Height (px)"))
        wh_row = QHBoxLayout()
        wh_row.setSpacing(6)
        self._bw = QSpinBox(); self._bw.setRange(1, 9999); self._bw.setValue(1920)
        self._bh = QSpinBox(); self._bh.setRange(1, 9999); self._bh.setValue(1080)
        self._bw.valueChanged.connect(on_changed)
        self._bh.valueChanged.connect(on_changed)
        for w in (self._bw, self._bh):
            w.setObjectName("TimerTransportBtn")
        wh_row.addWidget(self._bw)
        wh_row.addWidget(QLabel("×"))
        wh_row.addWidget(self._bh)
        wh_row.addStretch(1)
        self._layout.addLayout(wh_row)

        self._layout.addWidget(self._lbl("Custom CSS"))
        self._css = QTextEdit()
        self._css.setObjectName("OverlayTextField")
        self._css.setPlaceholderText("body { background: transparent; }")
        self._css.setMaximumHeight(80)
        self._css.textChanged.connect(on_changed)
        self._layout.addWidget(self._css)

        self._layout.addWidget(self._lbl("FPS"))
        self._fps = QSpinBox()
        self._fps.setRange(1, 60)
        self._fps.setValue(30)
        self._fps.setObjectName("TimerTransportBtn")
        self._fps.valueChanged.connect(on_changed)
        self._layout.addWidget(self._fps)

        self._reroute = QCheckBox("Reroute Audio to OBS")
        self._reroute.setObjectName("OverlayCheckBox")
        self._reroute.toggled.connect(on_changed)
        self._layout.addWidget(self._reroute)

        self._refresh_btn = QPushButton("↺  Refresh Preview")
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.clicked.connect(self._refresh_preview)
        self._layout.addWidget(self._refresh_btn)
        self._layout.addStretch(1)

        self._source_ref: SourceConfig | None = None

    def _browse_local_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HTML File", "",
            "Web Files (*.html *.htm *.xhtml);;All Files (*)",
        )
        if path:
            self._url.setText(f"file://{path}")

    def _on_overlay_picked(self, idx: int) -> None:
        url = self._overlay_combo.itemData(idx)
        if url:
            self._url.setText(url)
            # Reset combo back to placeholder so it acts like a menu
            self._overlay_combo.blockSignals(True)
            self._overlay_combo.setCurrentIndex(0)
            self._overlay_combo.blockSignals(False)

    def _open_in_browser(self) -> None:
        url = self._url.text().strip()
        if url:
            webbrowser.open(url)

    def _refresh_preview(self) -> None:
        # Re-emit so the canvas item reloads its web view with the current URL
        self._on_changed()

    def load(self, source):
        self._source_ref = source
        s = source.settings
        for ctrl, val in [
            (self._url, s.get("url", "")),
            (self._bw,  s.get("width", 1920)),
            (self._bh,  s.get("height", 1080)),
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
        self._overlay_combo.blockSignals(True)
        self._overlay_combo.setCurrentIndex(0)
        self._overlay_combo.blockSignals(False)

    def apply(self, source):
        source.settings.update({
            "url":           self._url.text().strip(),
            "width":         self._bw.value(),
            "height":        self._bh.value(),
            "css":           self._css.toPlainText(),
            "fps":           self._fps.value(),
            "reroute_audio": self._reroute.isChecked(),
        })


# ── Text form ──────────────────────────────────────────────────────────────────

class _TextForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)

        self._layout.addWidget(self._lbl("Text Content"))
        self._text = QTextEdit()
        self._text.setObjectName("OverlayTextField")
        self._text.setMaximumHeight(80)
        self._text.textChanged.connect(on_changed)
        self._layout.addWidget(self._text)

        self._layout.addWidget(self._lbl("Font Family"))
        self._font_family = QLineEdit()
        self._font_family.setObjectName("OverlayTextField")
        self._font_family.setPlaceholderText("Arial")
        self._font_family.textChanged.connect(on_changed)
        self._layout.addWidget(self._font_family)

        self._layout.addWidget(self._lbl("Font Size (px)"))
        self._size = QSpinBox()
        self._size.setRange(6, 500)
        self._size.setValue(48)
        self._size.setObjectName("TimerTransportBtn")
        self._size.valueChanged.connect(on_changed)
        self._layout.addWidget(self._size)

        self._color_edit, self._color_swatch = self._color_row("Color")

        flags_row = QHBoxLayout()
        flags_row.setSpacing(12)
        self._bold    = QCheckBox("Bold")
        self._italic  = QCheckBox("Italic")
        self._outline = QCheckBox("Outline")
        self._shadow  = QCheckBox("Shadow")
        for cb in (self._bold, self._italic, self._outline, self._shadow):
            cb.setObjectName("OverlayCheckBox")
            cb.toggled.connect(on_changed)
            flags_row.addWidget(cb)
        flags_row.addStretch(1)
        self._layout.addLayout(flags_row)

        self._layout.addWidget(self._lbl("Alignment"))
        self._align = QComboBox()
        self._align.addItems(["Left", "Center", "Right"])
        self._align.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._align)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        font = s.get("font", {}) if isinstance(s.get("font"), dict) else {}
        self._text.blockSignals(True)
        self._text.setPlainText(s.get("content", s.get("text", "")))
        self._text.blockSignals(False)
        self._font_family.blockSignals(True)
        self._font_family.setText(font.get("face", "Arial"))
        self._font_family.blockSignals(False)
        self._size.blockSignals(True)
        self._size.setValue(int(s.get("font_size", font.get("size", 48))))
        self._size.blockSignals(False)
        self._set_color(self._color_edit, self._color_swatch, s.get("color_hex", "ffffff"))
        align_map = {"left": 0, "center": 1, "right": 2}
        self._align.blockSignals(True)
        self._align.setCurrentIndex(align_map.get(s.get("align", "left"), 0))
        self._align.blockSignals(False)
        for cb, key in [
            (self._bold,    "bold"),
            (self._italic,  "italic"),
            (self._outline, "outline"),
            (self._shadow,  "shadow"),
        ]:
            cb.blockSignals(True)
            cb.setChecked(bool(s.get(key, False)))
            cb.blockSignals(False)

    def apply(self, source):
        align_vals = ["left", "center", "right"]
        source.settings.update({
            "content":    self._text.toPlainText(),
            "text":       self._text.toPlainText(),   # OBS compat key
            "color_hex":  self._color_edit.text().strip().lstrip("#"),
            "font_size":  self._size.value(),
            "font": {
                "face":  self._font_family.text().strip() or "Arial",
                "size":  self._size.value(),
                "style": (
                    ("Bold" if self._bold.isChecked() else "") +
                    ("Italic" if self._italic.isChecked() else "")
                ) or "Regular",
            },
            "bold":    self._bold.isChecked(),
            "italic":  self._italic.isChecked(),
            "outline": self._outline.isChecked(),
            "shadow":  self._shadow.isChecked(),
            "align":   align_vals[self._align.currentIndex()],
        })


# ── Color form ─────────────────────────────────────────────────────────────────

class _ColorForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._color_edit, self._color_swatch = self._color_row("Fill Color")
        self._layout.addStretch(1)

    def load(self, source):
        self._set_color(
            self._color_edit, self._color_swatch,
            source.settings.get("color_hex", "1a1a2e")
        )

    def apply(self, source):
        source.settings["color_hex"] = self._color_edit.text().strip().lstrip("#")


# ── Media form ─────────────────────────────────────────────────────────────────

class _MediaForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._file = self._file_row(
            "Media File",
            "Video/Audio (*.mp4 *.mov *.avi *.mkv *.webm *.mp3 *.wav *.flac *.ogg);;All Files (*)"
        )
        self._loop    = QCheckBox("Loop")
        self._restart = QCheckBox("Restart on Activate")
        self._clear   = QCheckBox("Clear on End")
        for cb in (self._loop, self._restart, self._clear):
            cb.setObjectName("OverlayCheckBox")
            cb.toggled.connect(on_changed)
            self._layout.addWidget(cb)
        self._layout.addStretch(1)

    def load(self, source):
        s = source.settings
        self._file.blockSignals(True)
        self._file.setText(s.get("file", s.get("local_file", "")))
        self._file.blockSignals(False)
        for cb, key in [
            (self._loop,    "loop"),
            (self._restart, "restart_on_activate"),
            (self._clear,   "clear_on_end"),
        ]:
            cb.blockSignals(True)
            cb.setChecked(bool(s.get(key, False)))
            cb.blockSignals(False)

    def apply(self, source):
        source.settings.update({
            "file":                self._file.text().strip(),
            "local_file":          self._file.text().strip(),   # OBS compat key
            "loop":                self._loop.isChecked(),
            "looping":             self._loop.isChecked(),      # OBS compat key
            "restart_on_activate": self._restart.isChecked(),
            "clear_on_end":        self._clear.isChecked(),
            "clear_on_media_end":  self._clear.isChecked(),     # OBS compat key
        })


# ── Audio Input form ───────────────────────────────────────────────────────────

class _AudioInputForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._lbl("Audio Device"))
        self._device = QComboBox()
        self._device.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._device)

        refresh_btn = QPushButton("↺  Refresh Devices")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.clicked.connect(self._refresh_devices)
        self._layout.addWidget(refresh_btn)

        self._layout.addWidget(self._lbl("Volume"))
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        self._vol = QSlider(Qt.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(100)
        self._vol.valueChanged.connect(on_changed)
        self._vol_spin = QSpinBox()
        self._vol_spin.setRange(0, 100)
        self._vol_spin.setValue(100)
        self._vol_spin.setSuffix("%")
        self._vol_spin.setFixedWidth(62)
        self._vol_spin.setObjectName("TimerTransportBtn")
        self._vol.valueChanged.connect(lambda v: self._vol_spin.setValue(v))
        self._vol_spin.valueChanged.connect(lambda v: self._vol.setValue(v))
        vol_row.addWidget(self._vol, 1)
        vol_row.addWidget(self._vol_spin)
        self._layout.addLayout(vol_row)

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
        vol = int(source.volume * 100)
        self._vol.blockSignals(True)
        self._vol_spin.blockSignals(True)
        self._vol.setValue(vol)
        self._vol_spin.setValue(vol)
        self._vol.blockSignals(False)
        self._vol_spin.blockSignals(False)
        self._muted.blockSignals(True)
        self._muted.setChecked(source.muted)
        self._muted.blockSignals(False)

    def apply(self, source):
        source.settings["device_id"] = self._device.currentData() or "default"
        source.volume = self._vol.value() / 100.0
        source.muted  = self._muted.isChecked()


# ── Window Capture form ────────────────────────────────────────────────────────

class _WindowCaptureForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._lbl("Window / Application"))
        self._window = QComboBox()
        self._window.currentIndexChanged.connect(on_changed)
        self._layout.addWidget(self._window)

        refresh_btn = QPushButton("↺  Refresh Windows")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.clicked.connect(self._refresh_windows)
        self._layout.addWidget(refresh_btn)

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
        for title, ident in _list_windows():
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
        source.settings["window"]         = self._window.currentData() or ""
        source.settings["capture_cursor"] = self._cursor.isChecked()


# ── Display Capture form ───────────────────────────────────────────────────────

class _DisplayCaptureForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._lbl("Display"))
        self._display = QComboBox()
        self._display.currentIndexChanged.connect(on_changed)
        from PySide6.QtWidgets import QApplication
        for i, screen in enumerate(QApplication.screens()):
            self._display.addItem(
                f"Display {i+1} — {screen.name()} ({screen.size().width()}×{screen.size().height()})", i
            )
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
        source.settings["display"]        = self._display.currentData() or 0
        source.settings["capture_cursor"] = self._cursor.isChecked()


# ── Chat Overlay form ──────────────────────────────────────────────────────────

class _ChatOverlayForm(_BaseForm):
    def __init__(self, on_changed):
        super().__init__(on_changed)
        self._layout.addWidget(self._lbl("Overlay URL"))
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self._url = QLineEdit()
        self._url.setObjectName("OverlayTextField")
        self._url.setPlaceholderText("http://localhost:47892/chat")
        self._url.textChanged.connect(on_changed)
        url_row.addWidget(self._url, 1)
        open_btn = QPushButton("↗")
        open_btn.setObjectName("SecondaryButton")
        open_btn.setFixedWidth(32)
        open_btn.clicked.connect(lambda: webbrowser.open(self._url.text().strip()) if self._url.text().strip() else None)
        url_row.addWidget(open_btn)
        self._layout.addLayout(url_row)

        hint = QLabel("StreamShift overlay server runs on port 47892 by default.")
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        self._layout.addWidget(hint)

        self._layout.addWidget(self._lbl("Width × Height (px)"))
        wh_row = QHBoxLayout()
        wh_row.setSpacing(6)
        self._bw = QSpinBox(); self._bw.setRange(1, 9999); self._bw.setValue(400)
        self._bh = QSpinBox(); self._bh.setRange(1, 9999); self._bh.setValue(800)
        for w in (self._bw, self._bh):
            w.setObjectName("TimerTransportBtn")
            w.valueChanged.connect(on_changed)
        wh_row.addWidget(self._bw)
        wh_row.addWidget(QLabel("×"))
        wh_row.addWidget(self._bh)
        wh_row.addStretch(1)
        self._layout.addLayout(wh_row)
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
            "url":    self._url.text().strip(),
            "width":  self._bw.value(),
            "height": self._bh.value(),
        })


# ── factory ────────────────────────────────────────────────────────────────────

def _form_for(source_type: str, on_changed: Callable) -> _BaseForm:
    return {
        "image":           _ImageForm,
        "browser":         _BrowserForm,
        "text":            _TextForm,
        "color":           _ColorForm,
        "media":           _MediaForm,
        "audio_input":     _AudioInputForm,
        "window_capture":  _WindowCaptureForm,
        "display_capture": _DisplayCaptureForm,
        "chat_overlay":    _ChatOverlayForm,
    }.get(source_type, _BaseForm)(on_changed)


# ── window list helper ─────────────────────────────────────────────────────────

def _list_windows() -> list[tuple[str, str]]:
    result = []
    try:
        if sys.platform == "darwin":
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
            import ctypes, ctypes.wintypes
            buf = ctypes.create_unicode_buffer(512)
            titles: list[str] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def _cb(hwnd, lp):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    t = buf.value.strip()
                    if t:
                        titles.append(t)
                return True

            ctypes.windll.user32.EnumWindows(_cb, 0)
            result = [(t, t) for t in titles]
        else:
            try:
                out = subprocess.check_output(["wmctrl", "-l"], stderr=subprocess.DEVNULL, timeout=3).decode()
                for line in out.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) >= 4 and parts[3].strip() not in ("", "N/A"):
                        result.append((parts[3].strip(), parts[3].strip()))
            except FileNotFoundError:
                try:
                    ids = subprocess.check_output(
                        ["xdotool", "search", "--onlyvisible", "--name", ""],
                        stderr=subprocess.DEVNULL, timeout=3,
                    ).decode().split()
                    for wid in ids:
                        name = subprocess.check_output(
                            ["xdotool", "getwindowname", wid],
                            stderr=subprocess.DEVNULL, timeout=1,
                        ).decode().strip()
                        if name:
                            result.append((name, name))
                except Exception:
                    pass
    except Exception:
        pass
    return result
