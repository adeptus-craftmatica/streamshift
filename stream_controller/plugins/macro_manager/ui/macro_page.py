from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from stream_controller.plugins.macro_manager.macro_steps import STEP_TYPE_BY_ID, STEP_TYPES
from stream_controller.ui.theme import create_card

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext
    from stream_controller.plugins.macro_manager.macro_engine import MacroEngine
    from stream_controller.plugins.macro_manager.macro_models import Macro, MacroStep

logger = logging.getLogger(__name__)

# ── on_error mapping ──────────────────────────────────────────────────────────
_ON_ERROR_LABELS = ["Skip and continue", "Abort macro", "Retry once"]
_ON_ERROR_VALUES = ["skip", "abort", "retry"]


def _on_error_label(value: str) -> str:
    try:
        return _ON_ERROR_LABELS[_ON_ERROR_VALUES.index(value)]
    except ValueError:
        return "Skip and continue"


def _on_error_value(label: str) -> str:
    try:
        return _ON_ERROR_VALUES[_ON_ERROR_LABELS.index(label)]
    except ValueError:
        return "skip"


# ── Step summary ──────────────────────────────────────────────────────────────

def _step_summary(step: MacroStep) -> str:
    t = step.step_type
    p = step.params
    if t == "services.connect":
        ids = p.get("services", [])
        names = _service_ids_to_labels(ids)
        return f"⚡ Connect → {', '.join(names) if names else '(none)'}"
    if t == "services.disconnect":
        ids = p.get("services", [])
        names = _service_ids_to_labels(ids)
        return f"✕ Disconnect → {', '.join(names) if names else '(none)'}"
    if t == "stream_info.update":
        title = p.get("title", "")
        return f"ℹ️ Stream Info → {title}"
    if t == "obs.start_stream":
        return "📡 Go Live"
    if t == "obs.stop_stream":
        return "📡 End Stream"
    if t == "obs.switch_scene":
        return f"🎬 Switch Scene → {p.get('scene_name', '')}"
    if t == "obs.toggle_source":
        visible = p.get("visible", True)
        return f"👁 {p.get('source_name', '')} → {'Show' if visible else 'Hide'}"
    if t == "obs.set_mute":
        muted = p.get("muted", False)
        return f"🔇 {p.get('source_name', '')} → {'Mute' if muted else 'Unmute'}"
    if t == "obs.set_volume":
        return f"🔊 {p.get('source_name', '')} → {p.get('volume_db', 0)}dB"
    if t == "obs.start_recording":
        return "⏺ Start Recording"
    if t == "obs.stop_recording":
        return "⏹ Stop Recording"
    if t == "flow.condition":
        pred = p.get("predicate_type", "")
        then_n = len(getattr(step, "then_steps", []))
        else_n = len(getattr(step, "else_steps", []))
        return f"⚡ If {pred} → {then_n} then / {else_n} else"
    if t == "flow.repeat":
        count = p.get("count", 1)
        body_n = len(getattr(step, "body_steps", []))
        return f"🔁 Repeat {count}× ({body_n} steps)"
    if t == "flow.wait_until":
        pred = p.get("predicate_type", "")
        timeout = p.get("timeout_seconds", 30)
        return f"⏳ Wait until {pred} (timeout {timeout}s)"
    if t == "flow.delay_random":
        return f"⏱ Random delay {p.get('min_ms', 0)}–{p.get('max_ms', 0)}ms"
    if t == "variable.set":
        return f"𝑥 {p.get('name', '')} = {p.get('value', '')}"
    if t == "variable.clear":
        return f"𝑥 Clear {p.get('name', '')}"
    if t == "http.request":
        url = p.get("url", "")
        method = p.get("method", "GET")
        preview = url[:40] + "..." if len(url) > 40 else url
        return f"⇄ {method} {preview}"
    if t == "notify.desktop":
        title = p.get("title", "")
        msg = p.get("message", "")
        preview = msg[:30] + "..." if len(msg) > 30 else msg
        return f"🔔 {title}: {preview}"
    if t == "chat.announcement":
        msg = p.get("message", "")
        preview = msg[:30] + "..." if len(msg) > 30 else msg
        return f"📢 Announcement: {preview}"
    if t == "chat.shoutout":
        return f"📣 Shoutout @{p.get('username', '')}"
    if t == "chat.timeout":
        return f"🚫 Timeout {p.get('username', '')} ({p.get('duration_seconds', 0)}s)"
    if t == "music.choose":
        paths = p.get("track_paths", [])
        count = len(paths)
        parts = []
        if p.get("shuffle"): parts.append("shuffle")
        if p.get("repeat"):  parts.append("repeat")
        suffix = f" ({', '.join(parts)})" if parts else ""
        style = p.get("overlay_style", "None")
        if style and style != "None": suffix += f" [{style}]"
        return f"🎵 Choose Tracks → {count} track{'s' if count != 1 else ''}{suffix}"
    if t == "music.play_playlist":
        pl_id = p.get("playlist_id", "")
        parts = []
        if p.get("shuffle"): parts.append("shuffle")
        style = p.get("overlay_style", "None")
        if style and style != "None": parts.append(style)
        suffix = f" ({', '.join(parts)})" if parts else ""
        return f"🎵 Play Playlist → {pl_id[:20]}{suffix}"
    if t == "music.play":
        paths = p.get("file_paths", [])
        count = len(paths)
        suffix = ""
        if p.get("repeat"):
            suffix += " (repeat)"
        if p.get("shuffle"):
            suffix += " (shuffle)"
        return f"🎵 Play → {count} track{'s' if count != 1 else ''}{suffix}"
    if t == "music.play_chosen":
        return "🎵 Play Chosen Tracks"
    if t == "music.stop":
        return "🎵 Stop Music"
    if t == "timer.create":
        label = p.get("label", "")
        mode = p.get("mode", "Countdown")
        src = p.get("duration_source", "Manual")
        return f"⏱ Create Timer → {label} ({mode}, {src})"
    if t == "timer.start":
        return f"⏱ Start Timer → {p.get('timer_id', '')}"
    if t == "timer.stop":
        return f"⏱ Stop Timer → {p.get('timer_id', '')}"
    if t == "timer.reset":
        return f"⏱ Reset Timer → {p.get('timer_id', '')}"
    if t == "chat.send":
        msg = p.get("message", "")
        preview = msg[:40] + "…" if len(msg) > 40 else msg
        return f"💬 Chat → {preview}"
    if t == "chat.raid":
        return f"🚀 Raid → {p.get('target', '')}"
    if t == "delay":
        return f"⏳ Wait {p.get('delay_ms', 500)} ms"
    if t == "action":
        return f"⚡ Run Action → {p.get('action_id', '')}"
    return step.label or t


_SERVICE_LABEL_MAP = {
    "obs_studio": "OBS",
    "scene_manager": "Scenes",
    "bot_manager": "Bots",
    "chat_manager": "Chat",
    "stream_stats": "Stats",
    "stream_info": "Info",
    "pngtuber": "PNGtuber",
}


def _service_ids_to_labels(ids: list[str]) -> list[str]:
    return [_SERVICE_LABEL_MAP.get(sid, sid) for sid in ids]


# ── Macro serialization helpers ────────────────────────────────────────────────

def _step_to_dict(step: MacroStep) -> dict:
    return {
        "step_id": step.step_id,
        "step_type": step.step_type,
        "params": step.params,
        "label": step.label,
        "on_error": step.on_error,
        "then_steps": [_step_to_dict(s) for s in step.then_steps],
        "else_steps": [_step_to_dict(s) for s in step.else_steps],
        "body_steps": [_step_to_dict(s) for s in step.body_steps],
    }


def _step_from_dict(d: dict) -> MacroStep:
    from stream_controller.plugins.macro_manager.macro_models import MacroStep
    return MacroStep(
        step_id=d.get("step_id", uuid.uuid4().hex[:12]),
        step_type=d.get("step_type", ""),
        params=d.get("params", {}),
        label=d.get("label", ""),
        on_error=d.get("on_error", "skip"),
        then_steps=[_step_from_dict(s) for s in d.get("then_steps", [])],
        else_steps=[_step_from_dict(s) for s in d.get("else_steps", [])],
        body_steps=[_step_from_dict(s) for s in d.get("body_steps", [])],
    )


def _macro_to_dict(macro: Macro) -> dict:
    return {
        "macro_id": macro.macro_id,
        "name": macro.name,
        "icon": macro.icon,
        "description": macro.description,
        "hotkey": macro.hotkey,
        "show_on_stage": macro.show_on_stage,
        "created_at": macro.created_at,
        "steps": [_step_to_dict(s) for s in macro.steps],
    }


def _macro_from_dict(d: dict, new_id: bool = False) -> Macro:
    from stream_controller.plugins.macro_manager.macro_models import Macro
    macro_id = uuid.uuid4().hex[:12] if new_id else d.get("macro_id", uuid.uuid4().hex[:12])
    return Macro(
        macro_id=macro_id,
        name=d.get("name", "Imported Macro"),
        icon=d.get("icon", "▶"),
        description=d.get("description", ""),
        hotkey="" if new_id else d.get("hotkey", ""),
        show_on_stage=d.get("show_on_stage", True),
        created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
        steps=[_step_from_dict(s) for s in d.get("steps", [])],
    )


# ── Widgets ───────────────────────────────────────────────────────────────────

class _ServiceMultiWidget(QWidget):
    _SERVICES = [
        ("OBS Studio",    "obs_studio"),
        ("Scene Manager", "scene_manager"),
        ("Bots",          "bot_manager"),
        ("Chat",          "chat_manager"),
        ("Stream Stats",  "stream_stats"),
        ("Stream Info",   "stream_info"),
        ("PNGtuber",      "pngtuber"),
    ]

    def __init__(self, default_ids: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._checks: dict[str, QCheckBox] = {}
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (label, sid) in enumerate(self._SERVICES):
            cb = QCheckBox(label)
            cb.setObjectName("OverlayCheckBox")
            cb.setChecked(sid in default_ids)
            self._checks[sid] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

    def get_selected(self) -> list[str]:
        return [sid for sid, cb in self._checks.items() if cb.isChecked()]

    def set_selected(self, ids: list[str]) -> None:
        for sid, cb in self._checks.items():
            cb.setChecked(sid in ids)


class _BranchEditorWidget(QWidget):
    """Inline branch list with Add / Remove for flow.condition / flow.repeat."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: list[MacroStep] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        hdr = QLabel(title)
        hdr.setObjectName("MusicFieldLabel")
        layout.addWidget(hdr)

        self._list = QListWidget()
        self._list.setObjectName("MacroStepsList")
        self._list.setMaximumHeight(100)
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn = QPushButton("＋ Add Step")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(self._add_step)
        rem_btn = QPushButton("✕ Remove")
        rem_btn.setObjectName("TimerDangerBtn")
        rem_btn.setFixedHeight(24)
        rem_btn.clicked.connect(self._remove_step)
        btn_row.addWidget(add_btn, 1)
        btn_row.addWidget(rem_btn, 1)
        layout.addLayout(btn_row)

    def _add_step(self) -> None:
        dlg = _StepPickerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            step = dlg.result_step
            if step:
                self._steps.append(step)
                self._refresh_list()

    def _remove_step(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        for s in self._steps:
            self._list.addItem(QListWidgetItem(_step_summary(s)))

    def get_steps(self) -> list[MacroStep]:
        return list(self._steps)

    def set_steps(self, steps: list[MacroStep]) -> None:
        self._steps = list(steps)
        self._refresh_list()


class _StepPickerDialog(QDialog):
    """Minimal dialog that lets the user pick a step type and fill params."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Branch Step")
        self.setMinimumSize(400, 520)
        self.result_step: MacroStep | None = None

        self._selected_type_id: str | None = None
        self._param_widgets: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        search = QLineEdit()
        search.setObjectName("OverlayTextField")
        search.setPlaceholderText("Search step types…")
        search.textChanged.connect(self._filter)
        root.addWidget(search)

        self._type_list = QListWidget()
        self._type_list.setObjectName("MacroActionList")
        self._type_list.setMaximumHeight(160)
        self._type_list.currentItemChanged.connect(self._on_type_selected)
        root.addWidget(self._type_list)

        from PySide6.QtWidgets import QScrollArea as _SA
        scroll = _SA()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._param_frame = QWidget()
        self._param_layout = QVBoxLayout(self._param_frame)
        self._param_layout.setContentsMargins(4, 4, 4, 4)
        self._param_layout.setSpacing(6)
        self._param_layout.addStretch(1)
        scroll.setWidget(self._param_frame)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate_types("")

    def _populate_types(self, query: str) -> None:
        self._type_list.blockSignals(True)
        self._type_list.clear()
        current_cat: str | None = None
        for category, type_id, label, _params in STEP_TYPES:
            if query and query not in label.lower() and query not in category.lower():
                continue
            if category != current_cat:
                current_cat = category
                hdr = QListWidgetItem(f"── {category} ──")
                hdr.setFlags(Qt.NoItemFlags)
                hdr.setForeground(Qt.gray)
                hdr.setSizeHint(QSize(0, 20))
                self._type_list.addItem(hdr)
            item = QListWidgetItem(f"  {label}")
            item.setData(Qt.UserRole, type_id)
            item.setSizeHint(QSize(0, 26))
            self._type_list.addItem(item)
        self._type_list.blockSignals(False)

    def _filter(self, text: str) -> None:
        self._populate_types(text.lower())

    def _on_type_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            return
        type_id = current.data(Qt.UserRole)
        if type_id is None:
            return
        self._selected_type_id = type_id
        self._rebuild_params(type_id)

    def _rebuild_params(self, type_id: str) -> None:
        while self._param_layout.count():
            item = self._param_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._param_widgets.clear()

        entry = STEP_TYPE_BY_ID.get(type_id)
        if not entry:
            self._param_layout.addStretch(1)
            return
        _cat, _tid, _lbl, param_schema = entry

        for param in param_schema:
            key = param["key"]
            ptype = param["type"]
            plabel = param.get("label", key)
            widget: QWidget

            if ptype == "multiline_text":
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                widget = QPlainTextEdit()
                widget.setObjectName("OverlayTextField")
                widget.setMaximumHeight(70)
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            if ptype == "service_multi":
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                widget = _ServiceMultiWidget(param.get("default", []))
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(plabel.upper())
            lbl.setObjectName("MusicFieldLabel")
            lbl.setMinimumWidth(90)
            row.addWidget(lbl)

            if ptype == "text":
                widget = QLineEdit()
                widget.setObjectName("OverlayTextField")
                widget.setPlaceholderText(param.get("placeholder", plabel))
                row.addWidget(widget, 1)
            elif ptype == "bool":
                widget = QCheckBox()
                widget.setObjectName("OverlayCheckBox")
                row.addWidget(widget)
                row.addStretch(1)
            elif ptype == "number":
                widget = QSpinBox()
                widget.setMinimum(param.get("min", 0))
                widget.setMaximum(param.get("max", 99999))
                widget.setValue(param.get("default", 0))
                row.addWidget(widget, 1)
            elif ptype == "number_float":
                widget = QDoubleSpinBox()
                widget.setMinimum(param.get("min", 0.0))
                widget.setMaximum(param.get("max", 99999.0))
                widget.setValue(param.get("default", 0.0))
                widget.setDecimals(1)
                row.addWidget(widget, 1)
            elif ptype == "choice":
                widget = QComboBox()
                for opt in param.get("options", []):
                    widget.addItem(opt)
                default = param.get("default", "")
                idx = widget.findText(default)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                row.addWidget(widget, 1)
            else:
                widget = QLineEdit()
                widget.setObjectName("OverlayTextField")
                row.addWidget(widget, 1)

            self._param_widgets[key] = widget
            container = QWidget()
            container.setLayout(row)
            self._param_layout.addWidget(container)

        self._param_layout.addStretch(1)

    def _collect_params(self) -> dict:
        type_id = self._selected_type_id
        if not type_id:
            return {}
        entry = STEP_TYPE_BY_ID.get(type_id)
        if not entry:
            return {}
        _cat, _tid, _lbl, param_schema = entry
        params: dict = {}
        for param in param_schema:
            key = param["key"]
            ptype = param["type"]
            widget = self._param_widgets.get(key)
            if widget is None:
                continue
            if ptype == "text":
                params[key] = widget.text()
            elif ptype == "multiline_text":
                params[key] = widget.toPlainText()
            elif ptype == "bool":
                params[key] = widget.isChecked()
            elif ptype in ("number", "number_float"):
                params[key] = widget.value()
            elif ptype == "choice":
                params[key] = widget.currentText()
            elif ptype == "service_multi":
                params[key] = widget.get_selected()
        return params

    def _accept(self) -> None:
        from stream_controller.plugins.macro_manager.macro_models import MacroStep
        type_id = self._selected_type_id
        if not type_id:
            self.reject()
            return
        entry = STEP_TYPE_BY_ID.get(type_id)
        label = entry[2] if entry else type_id
        self.result_step = MacroStep(
            step_id=uuid.uuid4().hex[:12],
            step_type=type_id,
            params=self._collect_params(),
            label=label,
        )
        self.accept()


# ── Main page ─────────────────────────────────────────────────────────────────

class MacroPage(QWidget):
    def __init__(
        self,
        engine: MacroEngine,
        app_context: AppContext,
        on_macros_changed: Callable[[], None],
    ) -> None:
        super().__init__()
        self._engine = engine
        self._app_context = app_context
        self._on_macros_changed = on_macros_changed
        self._current_macro_id: str | None = None
        self._param_widgets: dict[str, QWidget] = {}
        self._selected_step_type_id: str | None = None
        self._editing_step_row: int = -1  # -1 = adding new; >=0 = editing existing

        # Nested branch editors (only present for flow.condition / flow.repeat)
        self._then_editor: _BranchEditorWidget | None = None
        self._else_editor: _BranchEditorWidget | None = None
        self._body_editor: _BranchEditorWidget | None = None

        # on_error combo — created once and reused
        self._on_error_combo: QComboBox | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_macros_column())
        splitter.addWidget(self._build_metadata_column())
        splitter.addWidget(self._build_steps_column())
        splitter.addWidget(self._build_library_column())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 4)
        splitter.setStretchFactor(3, 5)

        root.addWidget(splitter, 1)

        self._refresh_macro_list()
        self._clear_editor()

    # ── Column 1: macro list ──────────────────────────────────────────────────

    def _build_macros_column(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(180)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        card, body = create_card("Macros", "")
        card.layout().setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)

        self._macro_list = QListWidget()
        self._macro_list.setObjectName("MacroList")
        self._macro_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._macro_list.currentItemChanged.connect(self._on_macro_selected)
        body.addWidget(self._macro_list, 1)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._new_macro)
        dup_btn = QPushButton("Duplicate")
        dup_btn.setObjectName("TimerTransportBtn")
        dup_btn.clicked.connect(self._duplicate_macro)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("TimerDangerBtn")
        del_btn.clicked.connect(self._delete_selected_macro)
        btn_row.addWidget(new_btn, 1)
        btn_row.addWidget(dup_btn, 1)
        btn_row.addWidget(del_btn, 1)
        body.addLayout(btn_row)

        io_row = QHBoxLayout()
        exp_btn = QPushButton("Export…")
        exp_btn.setObjectName("TimerTransportBtn")
        exp_btn.clicked.connect(self._export_macro)
        imp_btn = QPushButton("Import…")
        imp_btn.setObjectName("TimerTransportBtn")
        imp_btn.clicked.connect(self._import_macro)
        io_row.addWidget(exp_btn, 1)
        io_row.addWidget(imp_btn, 1)
        body.addLayout(io_row)

        layout.addWidget(card, 1)
        return container

    # ── Column 2: macro metadata ──────────────────────────────────────────────

    def _build_metadata_column(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(220)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_details_card(), 1)
        return container

    def _build_details_card(self) -> QFrame:
        card, body = create_card("Macro Details", "")
        card.layout().setContentsMargins(14, 12, 14, 12)
        body.setSpacing(10)

        body.addWidget(self._field_label("NAME"))
        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("OverlayTextField")
        self._name_edit.setPlaceholderText("Macro name")
        body.addWidget(self._name_edit)

        icon_row = QHBoxLayout()
        icon_col = QVBoxLayout()
        icon_col.setSpacing(4)
        icon_col.addWidget(self._field_label("ICON"))
        self._icon_edit = QLineEdit()
        self._icon_edit.setObjectName("OverlayTextField")
        self._icon_edit.setMaxLength(3)
        self._icon_edit.setPlaceholderText("▶")
        icon_col.addWidget(self._icon_edit)
        icon_row.addLayout(icon_col)
        icon_row.addStretch(1)
        body.addLayout(icon_row)

        body.addWidget(self._field_label("DESCRIPTION"))
        self._desc_edit = QLineEdit()
        self._desc_edit.setObjectName("OverlayTextField")
        self._desc_edit.setPlaceholderText("Optional description")
        body.addWidget(self._desc_edit)

        body.addWidget(self._field_label("HOTKEY"))
        hotkey_row = QHBoxLayout()
        self._hotkey_edit = QKeySequenceEdit()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("TimerTransportBtn")
        clear_btn.clicked.connect(self._hotkey_edit.clear)
        hotkey_row.addWidget(self._hotkey_edit, 1)
        hotkey_row.addWidget(clear_btn)
        body.addLayout(hotkey_row)

        self._stage_cb = QCheckBox("Show on Stage")
        self._stage_cb.setObjectName("OverlayCheckBox")
        body.addWidget(self._stage_cb)

        body.addStretch(1)

        save_btn = QPushButton("Save Macro")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_macro)
        body.addWidget(save_btn)

        return card

    # ── Column 3: steps list ──────────────────────────────────────────────────

    def _build_steps_column(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(220)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_steps_card(), 1)
        return container

    def _build_steps_card(self) -> QFrame:
        card, body = create_card("Steps", "")
        card.layout().setContentsMargins(14, 12, 14, 12)
        body.setSpacing(8)

        self._steps_list = QListWidget()
        self._steps_list.setObjectName("MacroStepsList")
        self._steps_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._steps_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._steps_list.currentItemChanged.connect(self._on_existing_step_selected)
        body.addWidget(self._steps_list, 1)

        hint = QLabel("Click a step to edit it  ·  Drag to reorder")
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        body.addWidget(hint)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        for label, obj_name, slot in [
            ("↑ Up",    "TimerTransportBtn", self._step_move_up),
            ("↓ Down",  "TimerTransportBtn", self._step_move_down),
            ("✕ Remove","TimerDangerBtn",    self._step_remove),
        ]:
            btn = QPushButton(label)
            btn.setObjectName(obj_name)
            btn.clicked.connect(slot)
            ctrl_row.addWidget(btn, 1)
        body.addLayout(ctrl_row)

        return card

    # ── Column 4: step library ────────────────────────────────────────────────

    def _build_library_column(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(240)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_step_library_card(), 1)
        layout.addWidget(self._build_chat_pool_card())
        return container

    def _build_chat_pool_card(self) -> QFrame:
        from stream_controller.plugins.macro_manager.chat_pool import ChatMessagePool
        card, body = create_card("Chat Message Pool", "")
        card.layout().setContentsMargins(14, 12, 14, 12)
        body.setSpacing(6)

        hint = QLabel("Messages stored here are available to 'Send Chat Messages Over Time' steps.")
        hint.setStyleSheet("font-size:10px; color:#475569;")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._pool_list = QListWidget()
        self._pool_list.setObjectName("MacroActionList")
        self._pool_list.setMaximumHeight(160)
        self._pool_list.setSelectionMode(QListWidget.SingleSelection)
        body.addWidget(self._pool_list)

        self._pool_input = QLineEdit()
        self._pool_input.setObjectName("OverlayTextField")
        self._pool_input.setPlaceholderText("New message…")
        self._pool_input.returnPressed.connect(self._pool_add)
        body.addWidget(self._pool_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setFixedHeight(26)
        add_btn.clicked.connect(self._pool_add)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("Remove")
        del_btn.setObjectName("SecondaryButton")
        del_btn.setFixedHeight(26)
        del_btn.clicked.connect(self._pool_remove)
        btn_row.addWidget(del_btn)
        body.addLayout(btn_row)

        self._pool_reload()
        return card

    def _pool_reload(self) -> None:
        from stream_controller.plugins.macro_manager.chat_pool import ChatMessagePool
        self._pool_list.clear()
        for msg in ChatMessagePool.load():
            item = QListWidgetItem(msg)
            item.setToolTip(msg)
            self._pool_list.addItem(item)

    def _pool_add(self) -> None:
        from stream_controller.plugins.macro_manager.chat_pool import ChatMessagePool
        text = self._pool_input.text().strip()
        if not text:
            return
        ChatMessagePool.add(text)
        self._pool_input.clear()
        self._pool_reload()

    def _pool_remove(self) -> None:
        from stream_controller.plugins.macro_manager.chat_pool import ChatMessagePool
        item = self._pool_list.currentItem()
        if item:
            ChatMessagePool.remove(item.text())
            self._pool_reload()

    def _build_step_library_card(self) -> QFrame:
        card, body = create_card("Step Library", "")
        card.layout().setContentsMargins(14, 12, 14, 12)
        body.setSpacing(8)

        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("OverlayTextField")
        self._search_edit.setPlaceholderText("Search step types…")
        self._search_edit.textChanged.connect(self._filter_step_types)
        body.addWidget(self._search_edit)

        self._step_type_list = QListWidget()
        self._step_type_list.setObjectName("MacroActionList")
        self._step_type_list.setMinimumHeight(160)
        self._step_type_list.setMaximumHeight(280)
        self._step_type_list.currentItemChanged.connect(self._on_step_type_selected)
        body.addWidget(self._step_type_list)

        from PySide6.QtWidgets import QScrollArea as _SA
        param_scroll = _SA()
        param_scroll.setWidgetResizable(True)
        param_scroll.setFrameShape(QFrame.NoFrame)
        param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        param_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        param_scroll.setMinimumHeight(40)

        self._param_frame = QWidget()
        self._param_frame.setObjectName("MacroParamFrame")
        self._param_layout = QVBoxLayout(self._param_frame)
        self._param_layout.setContentsMargins(6, 6, 6, 6)
        self._param_layout.setSpacing(8)
        self._param_layout.addStretch(1)
        param_scroll.setWidget(self._param_frame)
        body.addWidget(param_scroll, 1)

        lib_btn_row = QHBoxLayout()
        lib_btn_row.setSpacing(8)
        self._add_step_btn = QPushButton("Add Step")
        self._add_step_btn.setObjectName("PrimaryButton")
        self._add_step_btn.clicked.connect(self._add_step)
        delay_btn = QPushButton("Quick Delay…")
        delay_btn.setObjectName("TimerTransportBtn")
        delay_btn.clicked.connect(self._quick_delay)
        lib_btn_row.addWidget(self._add_step_btn, 1)
        lib_btn_row.addWidget(delay_btn, 1)
        body.addLayout(lib_btn_row)

        self._populate_step_type_list()
        return card

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("MusicFieldLabel")
        return lbl

    # ── Macro list helpers ─────────────────────────────────────────────────────

    def _refresh_macro_list(self) -> None:
        self._macro_list.blockSignals(True)
        self._macro_list.clear()
        for macro in self._engine.repo.list_macros():
            count = len(macro.steps)
            text = f"{macro.icon}  {macro.name}  ({count} step{'s' if count != 1 else ''})"
            if macro.hotkey:
                text += f"  [{macro.hotkey}]"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, macro.macro_id)
            self._macro_list.addItem(item)
        self._macro_list.blockSignals(False)

    def _on_macro_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            self._clear_editor()
            return
        macro_id = current.data(Qt.UserRole)
        macro = self._engine.repo.get_macro(macro_id)
        if macro is None:
            self._clear_editor()
            return
        self._current_macro_id = macro_id
        self._load_macro_into_editor(macro)

    def _new_macro(self) -> None:
        from stream_controller.plugins.macro_manager.macro_models import Macro

        macro_id = uuid.uuid4().hex[:12]
        macro = Macro(
            macro_id=macro_id,
            name="New Macro",
            icon="▶",
            description="",
            steps=[],
            hotkey="",
            show_on_stage=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._engine.repo.save_macro(macro)
        self._refresh_macro_list()
        self._on_macros_changed()
        for i in range(self._macro_list.count()):
            if self._macro_list.item(i).data(Qt.UserRole) == macro_id:
                self._macro_list.setCurrentRow(i)
                break

    def _delete_selected_macro(self) -> None:
        item = self._macro_list.currentItem()
        if item is None:
            return
        macro_id = item.data(Qt.UserRole)
        macro = self._engine.repo.get_macro(macro_id)
        name = macro.name if macro else macro_id
        answer = QMessageBox.question(
            self,
            "Delete Macro",
            f"Delete macro '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._engine.repo.delete_macro(macro_id)
        self._current_macro_id = None
        self._refresh_macro_list()
        self._on_macros_changed()
        self._clear_editor()

    def _duplicate_macro(self) -> None:
        item = self._macro_list.currentItem()
        if item is None:
            return
        macro_id = item.data(Qt.UserRole)
        original = self._engine.repo.get_macro(macro_id)
        if original is None:
            return
        new_id = uuid.uuid4().hex[:12]
        from stream_controller.plugins.macro_manager.macro_models import Macro
        dup = Macro(
            macro_id=new_id,
            name=original.name + " (Copy)",
            icon=original.icon,
            description=original.description,
            steps=copy.deepcopy(original.steps),
            hotkey="",
            show_on_stage=original.show_on_stage,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._engine.repo.save_macro(dup)
        self._refresh_macro_list()
        self._on_macros_changed()
        for i in range(self._macro_list.count()):
            if self._macro_list.item(i).data(Qt.UserRole) == new_id:
                self._macro_list.setCurrentRow(i)
                break

    def _export_macro(self) -> None:
        if self._current_macro_id is None:
            QMessageBox.information(self, "Export Macro", "Select a macro first.")
            return
        macro = self._engine.repo.get_macro(self._current_macro_id)
        if macro is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Macro",
            f"{macro.name}.streamshift-macro.json",
            "StreamShift Macro (*.streamshift-macro.json)",
        )
        if not path:
            return
        try:
            data = _macro_to_dict(macro)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _import_macro(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Macro",
            "",
            "StreamShift Macro (*.streamshift-macro.json);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            macro = _macro_from_dict(data, new_id=True)
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not parse file:\n{exc}")
            return
        self._engine.repo.save_macro(macro)
        self._refresh_macro_list()
        self._on_macros_changed()
        for i in range(self._macro_list.count()):
            if self._macro_list.item(i).data(Qt.UserRole) == macro.macro_id:
                self._macro_list.setCurrentRow(i)
                break

    # ── Editor helpers ─────────────────────────────────────────────────────────

    def _clear_editor(self) -> None:
        self._current_macro_id = None
        self._name_edit.clear()
        self._icon_edit.clear()
        self._desc_edit.clear()
        self._hotkey_edit.clear()
        self._stage_cb.setChecked(True)
        self._steps_list.clear()

    def _load_macro_into_editor(self, macro: Macro) -> None:
        from PySide6.QtGui import QKeySequence

        self._name_edit.setText(macro.name)
        self._icon_edit.setText(macro.icon)
        self._desc_edit.setText(macro.description)
        self._hotkey_edit.setKeySequence(QKeySequence.fromString(macro.hotkey))
        self._stage_cb.setChecked(macro.show_on_stage)
        self._steps_list.clear()
        for step in macro.steps:
            self._steps_list.addItem(self._make_step_item(step))

    def _make_step_item(self, step: MacroStep) -> QListWidgetItem:
        item = QListWidgetItem(_step_summary(step))
        item.setData(Qt.UserRole, step)
        return item

    def _commit_step_edit_if_active(self) -> None:
        """If a step is currently being edited (mode is 'Save Changes'), commit it first."""
        if self._editing_step_row >= 0:
            self._add_step()

    def _save_macro(self) -> None:
        from stream_controller.plugins.macro_manager.macro_models import Macro

        if self._current_macro_id is None:
            return

        # Commit any in-progress step edit before collecting steps
        self._commit_step_edit_if_active()

        existing = self._engine.repo.get_macro(self._current_macro_id)
        created_at = existing.created_at if existing else datetime.now(timezone.utc).isoformat()

        steps = []
        for i in range(self._steps_list.count()):
            step = self._steps_list.item(i).data(Qt.UserRole)
            steps.append(step)

        hotkey = self._hotkey_edit.keySequence().toString()
        macro = Macro(
            macro_id=self._current_macro_id,
            name=self._name_edit.text().strip() or "Macro",
            icon=self._icon_edit.text().strip() or "▶",
            description=self._desc_edit.text().strip(),
            steps=steps,
            hotkey=hotkey,
            show_on_stage=self._stage_cb.isChecked(),
            created_at=created_at,
        )
        self._engine.repo.save_macro(macro)
        self._refresh_macro_list()
        self._on_macros_changed()

    # ── Step controls ──────────────────────────────────────────────────────────

    def _step_move_up(self) -> None:
        row = self._steps_list.currentRow()
        if row <= 0:
            return
        item = self._steps_list.takeItem(row)
        self._steps_list.insertItem(row - 1, item)
        self._steps_list.setCurrentRow(row - 1)

    def _step_move_down(self) -> None:
        row = self._steps_list.currentRow()
        if row < 0 or row >= self._steps_list.count() - 1:
            return
        item = self._steps_list.takeItem(row)
        self._steps_list.insertItem(row + 1, item)
        self._steps_list.setCurrentRow(row + 1)

    def _step_remove(self) -> None:
        row = self._steps_list.currentRow()
        if row < 0:
            return
        self._steps_list.takeItem(row)

    def _on_existing_step_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            self._editing_step_row = -1
            self._add_step_btn.setText("Add Step")
            return
        step = current.data(Qt.UserRole)
        if step is None:
            return
        row = self._steps_list.row(current)
        self._editing_step_row = row

        self._step_type_list.blockSignals(True)
        for i in range(self._step_type_list.count()):
            item = self._step_type_list.item(i)
            if item.data(Qt.UserRole) == step.step_type:
                self._step_type_list.setCurrentItem(item)
                break
        self._step_type_list.blockSignals(False)

        self._selected_step_type_id = step.step_type
        self._rebuild_param_editor(step.step_type)
        self._populate_params_from_step(step)
        self._add_step_btn.setText("Save Changes")

    def _populate_params_from_step(self, step) -> None:
        entry = STEP_TYPE_BY_ID.get(step.step_type)
        if not entry:
            return
        _cat, _tid, _label, param_schema = entry
        p = step.params

        for param in param_schema:
            key = param["key"]
            ptype = param["type"]
            widget = self._param_widgets.get(key)
            if widget is None:
                continue
            val = p.get(key)
            if val is None:
                continue
            try:
                if ptype == "raid_target_picker":
                    widget.set_target(str(val))
                elif ptype == "service_multi":
                    widget.set_selected(val)
                elif ptype == "library_multi_picker":
                    widget.set_paths(val)
                elif ptype in ("text",):
                    widget.setText(str(val))
                elif ptype == "multiline_text":
                    widget.setPlainText(str(val))
                elif ptype == "bool":
                    widget.setChecked(bool(val))
                elif ptype in ("number", "number_float"):
                    widget.setValue(val)
                elif ptype == "choice":
                    idx = widget.findText(str(val))
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
                elif ptype in ("scene_picker", "timer_picker", "action_picker",
                               "library_track_picker", "library_playlist_picker"):
                    if isinstance(widget, QComboBox):
                        idx = widget.findData(str(val))
                        if idx >= 0:
                            widget.setCurrentIndex(idx)
                        else:
                            idx = widget.findText(str(val))
                            if idx >= 0:
                                widget.setCurrentIndex(idx)
                    elif hasattr(widget, "setText"):
                        widget.setText(str(val))
                elif ptype == "file_list":
                    widget.set_paths(val)
            except Exception:
                pass

        # Populate nested branch editors
        if self._then_editor is not None:
            self._then_editor.set_steps(getattr(step, "then_steps", []))
        if self._else_editor is not None:
            self._else_editor.set_steps(getattr(step, "else_steps", []))
        if self._body_editor is not None:
            self._body_editor.set_steps(getattr(step, "body_steps", []))

        # Populate on_error combo
        if self._on_error_combo is not None:
            on_error = getattr(step, "on_error", "skip")
            lbl = _on_error_label(on_error)
            idx = self._on_error_combo.findText(lbl)
            if idx >= 0:
                self._on_error_combo.setCurrentIndex(idx)

    # ── Step library ───────────────────────────────────────────────────────────

    def _populate_step_type_list(self, query: str = "") -> None:
        self._step_type_list.blockSignals(True)
        self._step_type_list.clear()

        current_category: str | None = None
        for category, type_id, label, _params in STEP_TYPES:
            if query and query not in label.lower() and query not in category.lower():
                continue
            if category != current_category:
                current_category = category
                header = QListWidgetItem(f"── {category} ──")
                header.setFlags(Qt.NoItemFlags)
                header.setForeground(Qt.gray)
                header.setSizeHint(QSize(0, 20))
                self._step_type_list.addItem(header)
            item = QListWidgetItem(f"  {label}")
            item.setData(Qt.UserRole, type_id)
            item.setSizeHint(QSize(0, 26))
            self._step_type_list.addItem(item)

        self._step_type_list.blockSignals(False)

    def _filter_step_types(self, text: str) -> None:
        self._populate_step_type_list(text.lower())

    def _on_step_type_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            return
        type_id = current.data(Qt.UserRole)
        if type_id is None:
            return
        self._selected_step_type_id = type_id
        self._rebuild_param_editor(type_id)
        # User clicked a type manually — exit edit mode
        if self._editing_step_row >= 0:
            self._editing_step_row = -1
            self._steps_list.blockSignals(True)
            self._steps_list.clearSelection()
            self._steps_list.blockSignals(False)
            self._add_step_btn.setText("Add Step")

    def _rebuild_param_editor(self, type_id: str) -> None:
        # Clear nested editor refs before destroying widgets
        self._then_editor = None
        self._else_editor = None
        self._body_editor = None
        self._on_error_combo = None

        while self._param_layout.count():
            item = self._param_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._param_widgets.clear()

        entry = STEP_TYPE_BY_ID.get(type_id)
        if not entry:
            self._param_layout.addStretch(1)
            return
        _cat, _tid, _label, param_schema = entry

        for param in param_schema:
            key = param["key"]
            ptype = param["type"]
            plabel = param.get("label", key)

            widget: QWidget

            if ptype == "raid_target_picker":
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                widget = _RaidTargetWidget(self)
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            if ptype == "library_multi_picker":
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                widget = _LibraryMultiPickerWidget(self._app_context, self)
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            if ptype == "service_multi":
                default_ids = param.get("default", [])
                widget = _ServiceMultiWidget(default_ids, self)
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            if ptype == "multiline_text":
                lbl = QLabel(plabel.upper())
                lbl.setObjectName("MusicFieldLabel")
                self._param_layout.addWidget(lbl)
                widget = QPlainTextEdit()
                widget.setObjectName("OverlayTextField")
                widget.setPlaceholderText(param.get("placeholder", plabel))
                widget.setMaximumHeight(80)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._param_layout.addWidget(widget)
                self._param_widgets[key] = widget
                continue

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(plabel.upper())
            lbl.setObjectName("MusicFieldLabel")
            lbl.setMinimumWidth(90)
            lbl.setMaximumWidth(150)
            lbl.setWordWrap(False)
            row.addWidget(lbl)

            if ptype == "text":
                widget = QLineEdit()
                widget.setObjectName("OverlayTextField")
                widget.setPlaceholderText(param.get("placeholder", plabel))
                row.addWidget(widget, 1)
            elif ptype == "bool":
                widget = QCheckBox()
                widget.setObjectName("OverlayCheckBox")
                row.addWidget(widget)
                row.addStretch(1)
            elif ptype == "number":
                widget = QSpinBox()
                widget.setMinimum(param.get("min", 0))
                widget.setMaximum(param.get("max", 99999))
                widget.setValue(param.get("default", 0))
                row.addWidget(widget, 1)
            elif ptype == "number_float":
                widget = QDoubleSpinBox()
                widget.setMinimum(param.get("min", 0.0))
                widget.setMaximum(param.get("max", 99999.0))
                widget.setValue(param.get("default", 0.0))
                widget.setDecimals(1)
                row.addWidget(widget, 1)
            elif ptype == "choice":
                widget = QComboBox()
                for opt in param.get("options", []):
                    widget.addItem(opt)
                default = param.get("default", "")
                idx = widget.findText(default)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                row.addWidget(widget, 1)
            elif ptype == "scene_picker":
                widget = self._make_scene_picker()
                row.addWidget(widget, 1)
            elif ptype == "timer_picker":
                widget = self._make_timer_picker(optional=param.get("optional", False))
                row.addWidget(widget, 1)
            elif ptype == "action_picker":
                widget = self._make_action_picker()
                row.addWidget(widget, 1)
            elif ptype == "library_track_picker":
                widget = self._make_library_track_picker()
                row.addWidget(widget, 1)
            elif ptype == "library_playlist_picker":
                widget = self._make_library_playlist_picker()
                row.addWidget(widget, 1)
            elif ptype == "file_list":
                widget = _FileListWidget(self._app_context, self)
                row.addWidget(widget, 1)
            else:
                widget = QLineEdit()
                widget.setObjectName("OverlayTextField")
                row.addWidget(widget, 1)

            self._param_widgets[key] = widget
            container = QWidget()
            container.setLayout(row)
            container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._param_layout.addWidget(container)

        # ── Nested branch editors for flow.condition / flow.repeat ────────────
        if type_id == "flow.condition":
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            self._param_layout.addWidget(sep)

            self._then_editor = _BranchEditorWidget("Then branch (runs when condition is true)")
            self._param_layout.addWidget(self._then_editor)

            self._else_editor = _BranchEditorWidget("Else branch (runs when condition is false)")
            self._param_layout.addWidget(self._else_editor)

        elif type_id == "flow.repeat":
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            self._param_layout.addWidget(sep)

            self._body_editor = _BranchEditorWidget("Repeat body (steps to repeat)")
            self._param_layout.addWidget(self._body_editor)

        # ── on_error per-step ─────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        self._param_layout.addWidget(sep2)

        err_row = QHBoxLayout()
        err_row.setContentsMargins(0, 0, 0, 0)
        err_lbl = QLabel("ON ERROR")
        err_lbl.setObjectName("MusicFieldLabel")
        err_lbl.setMinimumWidth(90)
        err_row.addWidget(err_lbl)
        self._on_error_combo = QComboBox()
        for lbl_text in _ON_ERROR_LABELS:
            self._on_error_combo.addItem(lbl_text)
        err_row.addWidget(self._on_error_combo, 1)
        err_container = QWidget()
        err_container.setLayout(err_row)
        self._param_layout.addWidget(err_container)

        self._param_layout.addStretch(1)

    def _make_scene_picker(self) -> QWidget:
        combo = QComboBox()
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("scene_manager")
            if lp and lp.instance and hasattr(lp.instance, "_client") and lp.instance._client:
                state = lp.instance._client.state
                for scene in state.scenes:
                    name = scene.name if hasattr(scene, "name") else str(scene)
                    if name and not getattr(scene, "is_group", False):
                        combo.addItem(name, name)
        except Exception:
            pass
        if combo.count() == 0:
            edit = QLineEdit()
            edit.setObjectName("OverlayTextField")
            edit.setPlaceholderText("Scene name (connect OBS to see list)")
            return edit
        return combo

    def _make_timer_picker(self, optional: bool = False) -> QWidget:
        combo = QComboBox()
        if optional:
            combo.addItem("Create new…", "")
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("timer_manager")
            if lp and lp.instance and hasattr(lp.instance, "_engine") and lp.instance._engine:
                for t in lp.instance._engine.timers:
                    combo.addItem(t.label or t.timer_id, t.timer_id)
        except Exception:
            pass
        if combo.count() == 0 or (combo.count() == 1 and optional):
            if not optional:
                edit = QLineEdit()
                edit.setObjectName("OverlayTextField")
                edit.setPlaceholderText("Timer ID")
                return edit
        return combo

    def _make_library_track_picker(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.lineEdit().setPlaceholderText("Search track…")
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("music_manager")
            if lp and lp.instance and lp.instance._library:
                tracks = sorted(
                    lp.instance._library.tracks,
                    key=lambda t: (t.display_artist.lower(), t.display_title.lower()),
                )
                for track in tracks:
                    label = f"{track.display_title}  —  {track.display_artist}"
                    combo.addItem(label, str(track.path))
        except Exception:
            pass
        if combo.count() == 0:
            combo.addItem("(No library tracks found)")
        return combo

    def _make_library_playlist_picker(self) -> QComboBox:
        combo = QComboBox()
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("music_manager")
            if lp and lp.instance and lp.instance._playlists:
                for pl in lp.instance._playlists.playlists:
                    combo.addItem(f"{pl.name}  ({pl.track_count} tracks)", pl.playlist_id)
        except Exception:
            pass
        if combo.count() == 0:
            combo.addItem("(No playlists found)")
        return combo

    def _make_action_picker(self) -> QWidget:
        combo = QComboBox()
        try:
            for action in self._app_context.action_registry.list_actions():
                combo.addItem(f"{action.icon or ''} {action.title}".strip(), action.action_id)
        except Exception:
            pass
        if combo.count() == 0:
            edit = QLineEdit()
            edit.setObjectName("OverlayTextField")
            edit.setPlaceholderText("Action ID")
            return edit
        return combo

    def _collect_params(self, type_id: str) -> dict:
        entry = STEP_TYPE_BY_ID.get(type_id)
        if not entry:
            return {}
        _cat, _tid, _label, param_schema = entry
        params: dict = {}
        for param in param_schema:
            key = param["key"]
            ptype = param["type"]
            widget = self._param_widgets.get(key)
            if widget is None:
                continue
            if ptype == "raid_target_picker":
                params[key] = widget.get_target()
            elif ptype == "library_multi_picker":
                params[key] = widget.get_paths()
            elif ptype == "service_multi":
                params[key] = widget.get_selected()
            elif ptype == "text":
                params[key] = widget.text()
            elif ptype == "multiline_text":
                params[key] = widget.toPlainText()
            elif ptype == "bool":
                params[key] = widget.isChecked()
            elif ptype == "number":
                params[key] = widget.value()
            elif ptype == "number_float":
                params[key] = widget.value()
            elif ptype == "choice":
                params[key] = widget.currentText()
            elif ptype in ("scene_picker", "timer_picker"):
                if isinstance(widget, QComboBox):
                    data = widget.currentData()
                    params[key] = data if data is not None else widget.currentText()
                else:
                    params[key] = widget.text()
            elif ptype == "action_picker":
                if isinstance(widget, QComboBox):
                    params[key] = widget.currentData() or widget.currentText()
                else:
                    params[key] = widget.text()
            elif ptype == "library_track_picker":
                params[key] = widget.currentData() or ""
            elif ptype == "library_playlist_picker":
                params[key] = widget.currentData() or ""
            elif ptype == "file_list":
                params[key] = widget.get_paths()
        return params

    def _collect_on_error(self) -> str:
        if self._on_error_combo is not None:
            return _on_error_value(self._on_error_combo.currentText())
        return "skip"

    def _add_step(self) -> None:
        from stream_controller.plugins.macro_manager.macro_models import MacroStep

        type_id = self._selected_step_type_id
        if not type_id:
            return
        entry = STEP_TYPE_BY_ID.get(type_id)
        if not entry:
            return
        _cat, _tid, label, _params = entry
        params = self._collect_params(type_id)
        on_error = self._collect_on_error()

        # Collect nested branches
        then_steps = self._then_editor.get_steps() if self._then_editor is not None else []
        else_steps = self._else_editor.get_steps() if self._else_editor is not None else []
        body_steps = self._body_editor.get_steps() if self._body_editor is not None else []

        if self._editing_step_row >= 0:
            row = self._editing_step_row
            existing_item = self._steps_list.item(row)
            if existing_item is not None:
                old_step = existing_item.data(Qt.UserRole)
                step = MacroStep(
                    step_id=old_step.step_id,
                    step_type=type_id,
                    params=params,
                    label=label,
                    on_error=on_error,
                    then_steps=then_steps,
                    else_steps=else_steps,
                    body_steps=body_steps,
                )
                updated_item = self._make_step_item(step)
                self._steps_list.takeItem(row)
                self._steps_list.insertItem(row, updated_item)
                self._steps_list.setCurrentRow(row)
        else:
            step = MacroStep(
                step_id=uuid.uuid4().hex[:12],
                step_type=type_id,
                params=params,
                label=label,
                on_error=on_error,
                then_steps=then_steps,
                else_steps=else_steps,
                body_steps=body_steps,
            )
            self._steps_list.addItem(self._make_step_item(step))

    def _quick_delay(self) -> None:
        from stream_controller.plugins.macro_manager.macro_models import MacroStep

        ms, ok = QInputDialog.getInt(
            self,
            "Quick Delay",
            "Delay duration (milliseconds):",
            500,
            0,
            60000,
            100,
        )
        if not ok:
            return
        step = MacroStep(
            step_id=uuid.uuid4().hex[:12],
            step_type="delay",
            params={"delay_ms": ms},
            label=f"Wait {ms} ms",
        )
        self._steps_list.addItem(self._make_step_item(step))


class _LibraryMultiPickerWidget(QWidget):
    def __init__(self, app_context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_context = app_context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._list = QListWidget()
        self._list.setObjectName("MacroFileList")
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setMinimumHeight(80)
        self._list.setMaximumHeight(160)
        layout.addWidget(self._list)

        self._dur_lbl = QLabel("")
        self._dur_lbl.setObjectName("MusicFieldLabel")
        layout.addWidget(self._dur_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        add_btn = QPushButton("Add Tracks…")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_tracks)

        rem_btn = QPushButton("Remove")
        rem_btn.setObjectName("TimerDangerBtn")
        rem_btn.clicked.connect(self._remove_selected)

        clr_btn = QPushButton("Clear")
        clr_btn.setObjectName("TimerTransportBtn")
        clr_btn.clicked.connect(self._clear)

        btn_row.addWidget(add_btn, 2)
        btn_row.addWidget(rem_btn, 1)
        btn_row.addWidget(clr_btn, 1)
        layout.addLayout(btn_row)

    def _add_tracks(self) -> None:
        dlg = _LibraryPickerDialog(self._app_context, self)
        if dlg._list.count() == 0:
            QMessageBox.information(
                self,
                "Library Empty",
                "No tracks found in your Music Manager library.\n"
                "Add a music folder in the Music Manager page first.",
            )
            return
        if dlg.exec() == QDialog.Accepted:
            import os
            existing = self.get_paths()
            for path in dlg.selected_paths():
                if path not in existing:
                    item = QListWidgetItem(os.path.basename(path))
                    item.setData(Qt.UserRole, path)
                    item.setSizeHint(QSize(0, 26))
                    self._list.addItem(item)
            self._update_duration()

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)
            self._update_duration()

    def _clear(self) -> None:
        self._list.clear()
        self._update_duration()

    def _update_duration(self) -> None:
        paths = self.get_paths()
        if not paths:
            self._dur_lbl.setText("")
            return
        total = 0.0
        for p in paths:
            try:
                from mutagen import File as MutagenFile
                f = MutagenFile(p)
                if f and f.info:
                    total += f.info.length
            except Exception:
                pass
        m, s = divmod(int(total), 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
        n = len(paths)
        self._dur_lbl.setText(f"{n} track{'s' if n != 1 else ''}  •  {dur} total")

    def set_paths(self, paths: list[str]) -> None:
        self._clear()
        import os
        for path in paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setSizeHint(QSize(0, 26))
            self._list.addItem(item)
        self._update_duration()

    def get_paths(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.UserRole)
            for i in range(self._list.count())
        ]


class _LibraryPickerDialog(QDialog):
    def __init__(self, app_context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pick Tracks from Library")
        self.setMinimumSize(520, 420)
        self._app_context = app_context
        self._all_tracks: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        search = QLineEdit()
        search.setObjectName("OverlayTextField")
        search.setPlaceholderText("Search by title or artist…")
        search.textChanged.connect(self._filter)
        root.addWidget(search)

        self._list = QListWidget()
        self._list.setObjectName("MacroFileList")
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        root.addWidget(self._list, 1)

        hint = QLabel("Hold Cmd/Ctrl to select multiple tracks.")
        hint.setObjectName("CardDescription")
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_tracks()
        self._filter("")

    def _load_tracks(self) -> None:
        try:
            lp = self._app_context.plugin_manager._loaded_plugins.get("music_manager")
            if lp and lp.instance and lp.instance._library:
                self._all_tracks = lp.instance._library.tracks
        except Exception:
            self._all_tracks = []

    def _filter(self, query: str) -> None:
        q = query.strip().lower()
        self._list.clear()
        for track in sorted(self._all_tracks, key=lambda t: (t.display_artist.lower(), t.display_title.lower())):
            if q and q not in track.display_title.lower() and q not in track.display_artist.lower():
                continue
            label = f"{track.display_title}  —  {track.display_artist}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(track.path))
            item.setSizeHint(QSize(0, 28))
            self._list.addItem(item)

    def selected_paths(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self._list.selectedItems()]


class _RaidTargetWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        self._combo.lineEdit().setPlaceholderText("Type a channel name…")
        self._reload_targets()
        layout.addWidget(self._combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        save_btn = QPushButton("Save to List")
        save_btn.setObjectName("TimerTransportBtn")
        save_btn.clicked.connect(self._save_current)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("TimerDangerBtn")
        remove_btn.clicked.connect(self._remove_current)

        btn_row.addWidget(save_btn, 1)
        btn_row.addWidget(remove_btn, 1)
        layout.addLayout(btn_row)

    def _reload_targets(self) -> None:
        from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore as _RaidTargetStore
        current = self._combo.currentText()
        self._combo.blockSignals(True)
        self._combo.clear()
        for name in _RaidTargetStore.load():
            self._combo.addItem(name)
        self._combo.setCurrentText(current)
        self._combo.blockSignals(False)

    def _save_current(self) -> None:
        from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore as _RaidTargetStore
        name = self._combo.currentText().strip().lstrip("@").lower()
        if name:
            _RaidTargetStore.add(name)
            self._reload_targets()
            self._combo.setCurrentText(name)

    def _remove_current(self) -> None:
        from stream_controller.plugins.macro_manager.raid_store import RaidTargetStore as _RaidTargetStore
        name = self._combo.currentText().strip().lower()
        if name:
            _RaidTargetStore.remove(name)
            self._reload_targets()

    def get_target(self) -> str:
        return self._combo.currentText().strip().lstrip("@").lower()

    def set_target(self, value: str) -> None:
        self._reload_targets()
        self._combo.setCurrentText(value)


class _FileListWidget(QWidget):
    def __init__(self, app_context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_context = app_context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._list = QListWidget()
        self._list.setObjectName("MacroFileList")
        self._list.setMaximumHeight(110)
        self._paths: list[str] = []
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        lib_btn = QPushButton("From Library")
        lib_btn.setObjectName("PrimaryButton")
        lib_btn.clicked.connect(self._pick_from_library)

        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("TimerTransportBtn")
        browse_btn.clicked.connect(self._browse_files)

        rem_btn = QPushButton("Remove")
        rem_btn.setObjectName("TimerDangerBtn")
        rem_btn.clicked.connect(self._remove_selected)

        btn_row.addWidget(lib_btn, 2)
        btn_row.addWidget(browse_btn, 1)
        btn_row.addWidget(rem_btn, 1)
        layout.addLayout(btn_row)

    def _pick_from_library(self) -> None:
        dlg = _LibraryPickerDialog(self._app_context, self)
        if dlg._list.count() == 0:
            QMessageBox.information(
                self,
                "Library Empty",
                "No tracks found in your Music Manager library.\n"
                "Add a folder in the Music Manager page first.",
            )
            return
        if dlg.exec() == QDialog.Accepted:
            import os
            for path in dlg.selected_paths():
                if path not in self._paths:
                    self._paths.append(path)
                    self._list.addItem(os.path.basename(path))

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files",
            "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac *.aac *.m4a)",
        )
        import os
        for path in paths:
            if path not in self._paths:
                self._paths.append(path)
                self._list.addItem(os.path.basename(path))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)
            self._paths.pop(row)

    def get_paths(self) -> list[str]:
        return list(self._paths)

    def set_paths(self, paths: list[str]) -> None:
        import os
        self._list.clear()
        self._paths = list(paths)
        for p in paths:
            self._list.addItem(os.path.basename(p))
