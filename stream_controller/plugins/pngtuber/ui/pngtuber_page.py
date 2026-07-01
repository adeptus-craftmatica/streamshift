from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from stream_controller.constants import PNGTUBER_PORT
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.plugins.pngtuber.plugin import PngTuberPlugin
    from stream_controller.plugins.pngtuber.pngtuber_repository import PngTuberRepository
    from stream_controller.plugins.pngtuber.avatar_engine import AvatarEngine

logger = logging.getLogger(__name__)

_LAYERS = ["idle", "talking", "idle_blink", "talking_blink"]
_LAYER_LABELS = ["Idle", "Talking", "Idle + Blink", "Talk + Blink"]
_THUMB_SIZE = 52


class _LayerRow(QWidget):
    """Single image-layer picker: thumbnail + label + path + browse + clear."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet(
            "background:#0d1117; border:1px solid #1e293b; border-radius:4px; color:#475569; font-size:11px;"
        )
        self._thumb.setText("—")
        row.addWidget(self._thumb)

        right = QVBoxLayout()
        right.setSpacing(4)
        lbl = QLabel(label)
        lbl.setObjectName("MetaText")
        right.addWidget(lbl)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("No file selected…")
        edit_row.addWidget(self.edit, 1)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setObjectName("SecondaryButton")
        self.browse_btn.setFixedHeight(28)
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.setFixedSize(28, 28)
        self.clear_btn.setToolTip("Clear image")
        edit_row.addWidget(self.browse_btn)
        edit_row.addWidget(self.clear_btn)
        right.addLayout(edit_row)
        row.addLayout(right, 1)

        self.edit.textChanged.connect(self._update_thumb)
        self.clear_btn.clicked.connect(lambda: self.edit.clear())

    def set_path(self, path: str) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(path)
        self.edit.blockSignals(False)
        self._update_thumb(path)

    def _update_thumb(self, path: str) -> None:
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._thumb.setPixmap(
                    pix.scaled(_THUMB_SIZE, _THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText("—")


class _NewSetDialog(QDialog):
    """Dialog to name and create a brand-new empty avatar set."""

    def __init__(self, existing_sets: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Avatar Set")
        self.setMinimumWidth(400)
        self._existing = existing_sets

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lay.addWidget(QLabel("<b>Create a new avatar set</b>"))
        hint = QLabel(
            "Give your set a name. It starts empty — you can add expressions\n"
            "and assign images to each layer after creation."
        )
        hint.setObjectName("MetaText")
        lay.addWidget(hint)

        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. My Streamer Avatar")
        form.addRow("Set name:", self._name_edit)
        lay.addLayout(form)

        self._error_lbl = QLabel()
        self._error_lbl.setStyleSheet("color:#f87171;")
        self._error_lbl.hide()
        lay.addWidget(self._error_lbl)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._name_edit.textChanged.connect(lambda: self._error_lbl.hide())

    def set_name(self) -> str:
        return self._name_edit.text().strip()

    def _validate(self) -> None:
        name = self.set_name()
        if not name:
            self._error_lbl.setText("Please enter a name.")
            self._error_lbl.show()
            return
        if name in self._existing:
            self._error_lbl.setText(f'A set named "{name}" already exists.')
            self._error_lbl.show()
            return
        self.accept()


class PngTuberPage(QWidget):
    def __init__(
        self,
        plugin: "PngTuberPlugin",
        repo: "PngTuberRepository",
        engine: "AvatarEngine",
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._repo = repo
        self._engine = engine
        self._layer_rows: dict[str, _LayerRow] = {}
        self._preview_path = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_avatar_tab(), "Avatar")
        tabs.addTab(self._build_mic_tab(), "Microphone")
        root.addWidget(tabs)

        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()

        # Debounce auto-save so we don't write on every keystroke
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(800)
        self._auto_save_timer.timeout.connect(self._do_auto_save)

        self._refresh()

    # ── Avatar tab ────────────────────────────────────────────────────────────

    def _build_avatar_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # ── Avatar Set manager ────────────────────────────────────────────────
        set_group = QGroupBox("Avatar Set")
        set_lay = QVBoxLayout(set_group)
        set_lay.setSpacing(8)

        set_top = QHBoxLayout()
        self._set_combo = QComboBox()
        self._set_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._set_combo.setPlaceholderText("No sets saved yet")
        self._set_combo.currentTextChanged.connect(self._on_set_selected)
        set_top.addWidget(self._set_combo, 1)

        self._set_new_btn = QPushButton("＋ New Set")
        self._set_new_btn.setObjectName("PrimaryButton")
        self._set_new_btn.clicked.connect(self._new_set)
        set_top.addWidget(self._set_new_btn)

        # Kebab menu for secondary set actions
        self._set_menu_btn = QToolButton()
        self._set_menu_btn.setText("⋮")
        self._set_menu_btn.setFixedSize(32, 32)
        self._set_menu_btn.setToolTip("More set actions")
        self._set_menu_btn.setPopupMode(QToolButton.InstantPopup)
        set_menu = QMenu(self._set_menu_btn)
        set_menu.addAction("Save changes", self._save_set)
        set_menu.addAction("Duplicate…", self._duplicate_set)
        set_menu.addAction("Rename…", self._rename_set)
        set_menu.addSeparator()
        set_menu.addAction("Delete set", self._delete_set)
        self._set_menu_btn.setMenu(set_menu)
        set_top.addWidget(self._set_menu_btn)
        set_lay.addLayout(set_top)

        self._set_status_lbl = QLabel()
        self._set_status_lbl.setObjectName("MetaText")
        self._set_status_lbl.hide()
        set_lay.addWidget(self._set_status_lbl)

        lay.addWidget(set_group)

        # ── Expression selector ───────────────────────────────────────────────
        expr_group = QGroupBox("Expression")
        expr_lay = QVBoxLayout(expr_group)

        expr_top = QHBoxLayout()
        self._expr_combo = QComboBox()
        self._expr_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._expr_combo.currentTextChanged.connect(self._on_expr_selected)
        expr_top.addWidget(self._expr_combo, 1)
        add_expr_btn = QPushButton("＋ Add")
        add_expr_btn.setObjectName("PrimaryButton")
        add_expr_btn.clicked.connect(self._add_expression)
        expr_top.addWidget(add_expr_btn)
        rename_expr_btn = QPushButton("Rename…")
        rename_expr_btn.setObjectName("SecondaryButton")
        rename_expr_btn.clicked.connect(self._rename_expression)
        expr_top.addWidget(rename_expr_btn)
        del_expr_btn = QPushButton("Delete")
        del_expr_btn.setObjectName("SecondaryButton")
        del_expr_btn.clicked.connect(self._delete_expression)
        expr_top.addWidget(del_expr_btn)
        expr_lay.addLayout(expr_top)
        lay.addWidget(expr_group)

        # ── Image layers ──────────────────────────────────────────────────────
        images_group = QGroupBox("Images")
        img_lay = QVBoxLayout(images_group)
        img_lay.setSpacing(10)
        for layer, label in zip(_LAYERS, _LAYER_LABELS):
            row_w = _LayerRow(label, images_group)
            row_w.edit.textChanged.connect(lambda text, l=layer: self._on_layer_changed(l, text))
            row_w.browse_btn.clicked.connect(lambda checked=False, l=layer: self._browse_layer(l))
            self._layer_rows[layer] = row_w
            img_lay.addWidget(row_w)
        lay.addWidget(images_group)

        # ── Canvas + chroma ───────────────────────────────────────────────────
        canvas_group = QGroupBox("Canvas")
        canvas_form = QFormLayout(canvas_group)

        size_row = QHBoxLayout()
        self._width_spin = QSpinBox()
        self._width_spin.setRange(100, 4096)
        self._width_spin.setValue(self._repo.get("canvas_width"))
        self._width_spin.valueChanged.connect(lambda v: self._repo.set("canvas_width", v))
        self._height_spin = QSpinBox()
        self._height_spin.setRange(100, 4096)
        self._height_spin.setValue(self._repo.get("canvas_height"))
        self._height_spin.valueChanged.connect(lambda v: self._repo.set("canvas_height", v))
        size_row.addWidget(self._width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self._height_spin)
        size_row.addStretch(1)
        canvas_form.addRow("Size (px):", size_row)

        chroma_row = QHBoxLayout()
        self._chroma_btn = QPushButton()
        self._chroma_btn.setFixedSize(32, 32)
        self._chroma_btn.setToolTip("Click to pick chroma key colour")
        self._chroma_btn.clicked.connect(self._pick_chroma)
        # Create label first so _update_chroma_btn can set its text
        self._chroma_lbl = QLabel()
        self._chroma_lbl.setObjectName("MetaText")
        self._update_chroma_btn()
        chroma_row.addWidget(self._chroma_btn)
        chroma_row.addWidget(self._chroma_lbl)
        chroma_row.addStretch(1)
        canvas_form.addRow("Chroma key:", chroma_row)
        lay.addWidget(canvas_group)

        # ── OBS browser source URL ────────────────────────────────────────────
        url_group = QGroupBox("OBS Browser Source")
        url_lay = QHBoxLayout(url_group)
        url_lbl = QLabel(f"http://localhost:{PNGTUBER_PORT}/avatar")
        url_lbl.setObjectName("MetaText")
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("PrimaryButton")
        copy_btn.clicked.connect(self._copy_url)
        url_lay.addWidget(url_lbl, 1)
        url_lay.addWidget(copy_btn)
        lay.addWidget(url_group)

        lay.addStretch(1)
        scroll.setWidget(inner)

        # ── Right panel: live preview (fixed, no scroll) ──────────────────────
        right = QFrame()
        right.setFrameShape(QFrame.NoFrame)
        right.setFixedWidth(220)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 4, 0, 4)
        right_lay.setSpacing(8)

        preview_group = QGroupBox("Live Preview")
        preview_inner = QVBoxLayout(preview_group)
        preview_inner.setSpacing(6)
        self._preview_lbl = QLabel()
        self._preview_lbl.setAlignment(Qt.AlignCenter)
        self._preview_lbl.setFixedSize(196, 196)
        self._preview_lbl.setStyleSheet(
            "background:#0d1117; border:1px solid #1e293b; border-radius:6px;"
        )
        self._preview_lbl.setText("No image")
        self._preview_state_lbl = QLabel()
        self._preview_state_lbl.setAlignment(Qt.AlignCenter)
        self._preview_state_lbl.setObjectName("MetaText")
        self._preview_state_lbl.setWordWrap(True)
        preview_inner.addWidget(self._preview_lbl)
        preview_inner.addWidget(self._preview_state_lbl)
        right_lay.addWidget(preview_group)
        right_lay.addStretch(1)

        # Wrap scroll + right panel in a horizontal layout
        wrapper = QWidget()
        wrapper_lay = QHBoxLayout(wrapper)
        wrapper_lay.setContentsMargins(0, 0, 0, 0)
        wrapper_lay.setSpacing(0)
        wrapper_lay.addWidget(scroll, 1)
        wrapper_lay.addWidget(right)

        self._populate_sets()
        return wrapper

    # ── Mic tab ───────────────────────────────────────────────────────────────

    def _build_mic_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        form_group = QGroupBox("Microphone Settings")
        form = QFormLayout(form_group)

        self._device_combo = QComboBox()
        self._device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._populate_devices()
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        form.addRow("Input device:", self._device_combo)

        threshold_row = QHBoxLayout()
        self._threshold_slider = QSlider(Qt.Horizontal)
        self._threshold_slider.setRange(0, 100)
        self._threshold_slider.setValue(int(self._repo.get("mic_threshold") * 1000))
        self._threshold_lbl = QLabel(f"{self._repo.get('mic_threshold'):.3f}")
        self._threshold_lbl.setObjectName("MetaText")
        self._threshold_lbl.setFixedWidth(42)
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)
        threshold_row.addWidget(self._threshold_slider, 1)
        threshold_row.addWidget(self._threshold_lbl)
        form.addRow("Threshold:", threshold_row)

        hold_row = QHBoxLayout()
        self._hold_spin = QSpinBox()
        self._hold_spin.setRange(1, 60)
        self._hold_spin.setValue(self._repo.get("talk_hold_frames"))
        self._hold_spin.valueChanged.connect(
            lambda v: (self._repo.set("talk_hold_frames", v), setattr(self._engine, "talk_hold_frames", v))
        )
        hold_hint = QLabel("frames  (higher = jaw stays open longer)")
        hold_hint.setObjectName("MetaText")
        hold_row.addWidget(self._hold_spin)
        hold_row.addWidget(hold_hint)
        hold_row.addStretch(1)
        form.addRow("Talk hold:", hold_row)

        self._blink_check = QCheckBox("Enable random blinking")
        self._blink_check.setChecked(self._repo.get("blink_enabled"))
        self._blink_check.toggled.connect(
            lambda v: (self._repo.set("blink_enabled", v), setattr(self._engine, "blink_enabled", v))
        )
        form.addRow("", self._blink_check)
        lay.addWidget(form_group)

        level_group = QGroupBox("Mic Level")
        level_lay = QVBoxLayout(level_group)
        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setValue(0)
        self._level_bar.setTextVisible(False)
        self._level_bar.setFixedHeight(14)
        level_lay.addWidget(self._level_bar)
        lay.addWidget(level_group)

        self._start_stop_btn = QPushButton("Start Engine")
        self._start_stop_btn.setObjectName("PrimaryButton")
        self._start_stop_btn.clicked.connect(self._toggle_engine)
        lay.addWidget(self._start_stop_btn)

        lay.addStretch(1)
        return w

    # ── Set management ────────────────────────────────────────────────────────

    def _populate_sets(self) -> None:
        self._set_combo.blockSignals(True)
        self._set_combo.clear()
        for name in self._repo.list_sets():
            self._set_combo.addItem(name)
        active = self._repo.get("active_set") or ""
        idx = self._set_combo.findText(active)
        if idx >= 0:
            self._set_combo.setCurrentIndex(idx)
        self._set_combo.blockSignals(False)
        has_sets = self._set_combo.count() > 0
        self._set_menu_btn.setEnabled(has_sets)
        self._populate_expressions()

    def _on_set_selected(self, name: str) -> None:
        if not name:
            return
        self._repo.load_set(name)
        self._populate_expressions()
        self._width_spin.setValue(self._repo.get("canvas_width"))
        self._height_spin.setValue(self._repo.get("canvas_height"))
        self._blink_check.setChecked(self._repo.get("blink_enabled"))
        self._engine.blink_enabled = self._repo.get("blink_enabled")
        self._update_chroma_btn()
        self._flash_status(f"Loaded \"{name}\"")

    def _new_set(self) -> None:
        dlg = _NewSetDialog(self._repo.list_sets(), self)
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.set_name()
        # Reset working data to blank, then persist as new set
        self._repo.set("expressions", {
            "default": {"idle": "", "talking": "", "idle_blink": "", "talking_blink": ""}
        })
        self._repo.set("active_expression", "default")
        self._repo.save_set(name)
        self._populate_sets()
        idx = self._set_combo.findText(name)
        if idx >= 0:
            self._set_combo.blockSignals(True)
            self._set_combo.setCurrentIndex(idx)
            self._set_combo.blockSignals(False)
        self._populate_expressions()
        self._flash_status(f"Created \"{name}\"")

    def _save_set(self) -> None:
        name = self._set_combo.currentText()
        if not name:
            return
        self._repo.save_set(name)
        self._flash_status(f"Saved \"{name}\"")

    def _duplicate_set(self) -> None:
        source = self._set_combo.currentText()
        if not source:
            return
        dest, ok = QInputDialog.getText(
            self, "Duplicate Set", "Name for the copy:", text=f"{source} Copy"
        )
        if not ok or not dest.strip():
            return
        dest = dest.strip()
        if dest in self._repo.list_sets():
            QMessageBox.warning(self, "Duplicate Set", f'A set named "{dest}" already exists.')
            return
        self._repo.duplicate_set(source, dest)
        self._populate_sets()
        idx = self._set_combo.findText(dest)
        if idx >= 0:
            self._set_combo.setCurrentIndex(idx)
        self._flash_status(f"Duplicated as \"{dest}\"")

    def _rename_set(self) -> None:
        old = self._set_combo.currentText()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Rename Set", "New name:", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        self._repo.rename_set(old, new.strip())
        self._populate_sets()
        idx = self._set_combo.findText(new.strip())
        if idx >= 0:
            self._set_combo.setCurrentIndex(idx)

    def _delete_set(self) -> None:
        name = self._set_combo.currentText()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Set",
            f'Delete avatar set "{name}"? This cannot be undone.',
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        self._repo.delete_set(name)
        self._populate_sets()

    def _flash_status(self, msg: str) -> None:
        self._set_status_lbl.setText(msg)
        self._set_status_lbl.show()
        QTimer.singleShot(3000, self._set_status_lbl.hide)

    # ── Expression management ─────────────────────────────────────────────────

    def _populate_expressions(self) -> None:
        self._expr_combo.blockSignals(True)
        self._expr_combo.clear()
        for name in self._repo.list_expressions():
            self._expr_combo.addItem(name)
        active = self._repo.get("active_expression") or ""
        idx = self._expr_combo.findText(active)
        if idx >= 0:
            self._expr_combo.setCurrentIndex(idx)
        self._expr_combo.blockSignals(False)
        self._load_expression_layers(self._expr_combo.currentText())

    def _load_expression_layers(self, name: str) -> None:
        if not name:
            for row in self._layer_rows.values():
                row.set_path("")
            return
        layers = self._repo.get_expression(name)
        for layer, row in self._layer_rows.items():
            row.set_path(layers.get(layer, ""))

    def _on_expr_selected(self, name: str) -> None:
        self._repo.set("active_expression", name)
        self._load_expression_layers(name)

    def _add_expression(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Expression", "Expression name:")
        if ok and name.strip():
            name = name.strip()
            self._repo.set_expression(name, {"idle": "", "talking": "", "idle_blink": "", "talking_blink": ""})
            self._populate_expressions()
            idx = self._expr_combo.findText(name)
            if idx >= 0:
                self._expr_combo.setCurrentIndex(idx)
            self._schedule_auto_save()

    def _rename_expression(self) -> None:
        old = self._expr_combo.currentText()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Rename Expression", "New name:", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        new = new.strip()
        layers = self._repo.get_expression(old)
        self._repo.delete_expression(old)
        self._repo.set_expression(new, layers)
        self._populate_expressions()
        idx = self._expr_combo.findText(new)
        if idx >= 0:
            self._expr_combo.setCurrentIndex(idx)
        self._schedule_auto_save()

    def _delete_expression(self) -> None:
        name = self._expr_combo.currentText()
        if not name:
            return
        if len(self._repo.list_expressions()) <= 1:
            QMessageBox.warning(self, "Delete Expression", "You must keep at least one expression.")
            return
        self._repo.delete_expression(name)
        self._populate_expressions()
        self._schedule_auto_save()

    def _on_layer_changed(self, layer: str, text: str) -> None:
        name = self._expr_combo.currentText()
        if not name:
            return
        layers = dict(self._repo.get_expression(name))
        layers[layer] = text.strip()
        self._repo.set_expression(name, layers)
        self._schedule_auto_save()

    def _browse_layer(self, layer: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "",
            "Image Files (*.png *.jpg *.jpeg *.gif *.webp)"
        )
        if path:
            row = self._layer_rows.get(layer)
            if row:
                row.edit.setText(path)

    # ── Auto-save ─────────────────────────────────────────────────────────────

    def _schedule_auto_save(self) -> None:
        self._auto_save_timer.stop()
        self._auto_save_timer.start()

    def _do_auto_save(self) -> None:
        name = self._set_combo.currentText()
        if name:
            self._repo.save_set(name)

    # ── Canvas / chroma ───────────────────────────────────────────────────────

    def _update_chroma_btn(self) -> None:
        color = "#" + self._repo.get("chroma_color")
        self._chroma_btn.setStyleSheet(
            f"background:{color}; border:1px solid #1e293b; border-radius:4px;"
        )
        if hasattr(self, "_chroma_lbl"):
            self._chroma_lbl.setText(color.upper())

    def _pick_chroma(self) -> None:
        current = QColor("#" + self._repo.get("chroma_color"))
        color = QColorDialog.getColor(current, self, "Pick chroma key colour")
        if color.isValid():
            self._repo.set("chroma_color", color.name().lstrip("#"))
            self._update_chroma_btn()
            self._schedule_auto_save()

    # ── URL ───────────────────────────────────────────────────────────────────

    def _copy_url(self) -> None:
        QApplication.clipboard().setText(f"http://localhost:{PNGTUBER_PORT}/avatar")

    # ── Mic helpers ───────────────────────────────────────────────────────────

    def _populate_devices(self) -> None:
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        self._device_combo.addItem("Default", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self._device_combo.addItem(d["name"], i)
        except Exception:
            pass
        saved = self._repo.get("mic_device_index")
        for i in range(self._device_combo.count()):
            if self._device_combo.itemData(i) == saved:
                self._device_combo.setCurrentIndex(i)
                break
        self._device_combo.blockSignals(False)

    def _on_threshold_changed(self, val: int) -> None:
        threshold = val / 1000.0
        self._threshold_lbl.setText(f"{threshold:.3f}")
        self._repo.set("mic_threshold", threshold)
        self._engine.mic_threshold = threshold

    def _on_device_changed(self, idx: int) -> None:
        device = self._device_combo.itemData(idx)
        self._repo.set("mic_device_index", device)
        self._engine.mic_device_index = device

    def _toggle_engine(self) -> None:
        if self._engine.running:
            self._plugin.stop()
        else:
            self._plugin.start()

    # ── Polling / preview ─────────────────────────────────────────────────────

    def _refresh(self) -> None:
        st = self._plugin.get_state()
        running = st["running"]
        self._start_stop_btn.setText("Stop Engine" if running else "Start Engine")
        self._start_stop_btn.setObjectName("SecondaryButton" if running else "PrimaryButton")
        self._level_bar.setValue(int(st["level"] * 100))
        self._update_preview(st["expression"], st["state"])

    def _update_preview(self, expression: str, state: str) -> None:
        layers = self._repo.get_expression(expression)
        for layer in [state, "idle"]:
            p = layers.get(layer, "")
            if p and Path(p).exists():
                if p == self._preview_path:
                    return
                self._preview_path = p
                pix = QPixmap(p)
                if not pix.isNull():
                    self._preview_lbl.setPixmap(
                        pix.scaled(196, 196, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                    self._preview_state_lbl.setText(
                        f"{expression}\n{state.replace('_', ' ')}"
                    )
                    return
        if self._preview_path:
            self._preview_path = ""
            self._preview_lbl.setPixmap(QPixmap())
            self._preview_lbl.setText("No image")
            self._preview_state_lbl.setText("")
