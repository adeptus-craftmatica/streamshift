from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
)

if TYPE_CHECKING:
    from stream_controller.plugins.social_manager.plugin import SocialManagerPlugin
    from stream_controller.plugins.social_manager.social_repository import SocialRepository
    from stream_controller.plugins.social_manager.bluesky_client import BlueSkyClient

logger = logging.getLogger(__name__)

_PLACEHOLDER_HELP = (
    "Available placeholders: {title} · {category} · {url} · "
    "{bluesky_handle} · {instagram_handle} · {twitter_handle}"
)


class _Signals(QObject):
    post_done = Signal(bool, str)  # success, message


class SocialPage(QWidget):
    def __init__(
        self,
        plugin: "SocialManagerPlugin",
        repo: "SocialRepository",
        client: "BlueSkyClient",
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._repo = repo
        self._client = client
        self._sig = _Signals(self)
        self._sig.post_done.connect(self._on_post_done)
        self._image_path = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_compose_tab(), "Compose")
        tabs.addTab(self._build_templates_tab(), "Templates")
        tabs.addTab(self._build_accounts_tab(), "Accounts")
        tabs.addTab(self._build_handles_tab(), "Handles & Bot")
        root.addWidget(tabs)

        self._refresh_connection_status()

    # ── Compose tab ───────────────────────────────────────────────────────────

    def _build_compose_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 12, 0, 16)
        lay.setSpacing(16)

        # Platform selection
        plat_group = QGroupBox("Post to")
        plat_lay = QHBoxLayout(plat_group)
        self._bsky_check = QCheckBox("Bluesky")
        self._bsky_check.setChecked(True)
        plat_lay.addWidget(self._bsky_check)
        plat_lay.addStretch(1)
        lay.addWidget(plat_group)

        # Text editor
        text_group = QGroupBox("Message")
        text_lay = QVBoxLayout(text_group)
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("What's happening on stream?")
        self._text_edit.setMinimumHeight(100)
        self._text_edit.setMaximumHeight(160)
        self._char_lbl = QLabel("0 / 300")
        self._char_lbl.setObjectName("MetaText")
        self._char_lbl.setAlignment(Qt.AlignRight)
        self._text_edit.textChanged.connect(self._on_text_changed)
        text_lay.addWidget(self._text_edit)
        text_lay.addWidget(self._char_lbl)

        hint = QLabel(_PLACEHOLDER_HELP)
        hint.setObjectName("MetaText")
        hint.setWordWrap(True)
        text_lay.addWidget(hint)
        lay.addWidget(text_group)

        # Template loader
        tmpl_row = QHBoxLayout()
        tmpl_lbl = QLabel("Load template:")
        tmpl_lbl.setObjectName("MetaText")
        self._tmpl_combo_compose = _TemplateCombo(self._repo)
        load_tmpl_btn = QPushButton("Load")
        load_tmpl_btn.setObjectName("SecondaryButton")
        load_tmpl_btn.clicked.connect(self._load_template_to_compose)
        tmpl_row.addWidget(tmpl_lbl)
        tmpl_row.addWidget(self._tmpl_combo_compose, 1)
        tmpl_row.addWidget(load_tmpl_btn)
        lay.addLayout(tmpl_row)

        # Image attach
        img_group = QGroupBox("Attach Image (optional)")
        img_lay = QVBoxLayout(img_group)
        img_row = QHBoxLayout()
        self._img_path_lbl = QLabel("No image selected")
        self._img_path_lbl.setObjectName("MetaText")
        self._img_path_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        browse_img_btn = QPushButton("Browse…")
        browse_img_btn.setObjectName("SecondaryButton")
        browse_img_btn.clicked.connect(self._browse_image)
        clear_img_btn = QPushButton("✕")
        clear_img_btn.setObjectName("SecondaryButton")
        clear_img_btn.setFixedSize(28, 28)
        clear_img_btn.setToolTip("Remove image")
        clear_img_btn.clicked.connect(self._clear_image)
        img_row.addWidget(self._img_path_lbl, 1)
        img_row.addWidget(browse_img_btn)
        img_row.addWidget(clear_img_btn)
        img_lay.addLayout(img_row)
        self._img_thumb = QLabel()
        self._img_thumb.setFixedHeight(80)
        self._img_thumb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._img_thumb.hide()
        img_lay.addWidget(self._img_thumb)
        lay.addWidget(img_group)

        # Status + post button
        self._post_status_lbl = QLabel()
        self._post_status_lbl.setWordWrap(True)
        self._post_status_lbl.hide()
        lay.addWidget(self._post_status_lbl)

        self._post_btn = QPushButton("Post Now")
        self._post_btn.setObjectName("PrimaryButton")
        self._post_btn.clicked.connect(self._post_now)
        lay.addWidget(self._post_btn)

        lay.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    # ── Templates tab ─────────────────────────────────────────────────────────

    def _build_templates_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 16)
        lay.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("<b>Saved templates</b>"))
        top_row.addStretch(1)
        new_btn = QPushButton("＋ New Template")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._new_template)
        top_row.addWidget(new_btn)
        lay.addLayout(top_row)

        self._tmpl_list = QListWidget()
        self._tmpl_list.setAlternatingRowColors(False)
        self._tmpl_list.currentItemChanged.connect(self._on_tmpl_selected)
        lay.addWidget(self._tmpl_list, 1)

        # Editor
        editor_group = QGroupBox("Edit template")
        editor_lay = QFormLayout(editor_group)

        self._tmpl_name_edit = QLineEdit()
        self._tmpl_name_edit.setPlaceholderText("Template name")
        editor_lay.addRow("Name:", self._tmpl_name_edit)

        self._tmpl_text_edit = QPlainTextEdit()
        self._tmpl_text_edit.setMinimumHeight(90)
        self._tmpl_text_edit.setMaximumHeight(140)
        self._tmpl_text_edit.setPlaceholderText("Post text — use {title}, {url}, etc.")
        editor_lay.addRow("Text:", self._tmpl_text_edit)

        img_tmpl_row = QHBoxLayout()
        self._tmpl_img_edit = QLineEdit()
        self._tmpl_img_edit.setPlaceholderText("Optional image path")
        browse_tmpl_img = QPushButton("Browse…")
        browse_tmpl_img.setObjectName("SecondaryButton")
        browse_tmpl_img.clicked.connect(self._browse_tmpl_image)
        img_tmpl_row.addWidget(self._tmpl_img_edit, 1)
        img_tmpl_row.addWidget(browse_tmpl_img)
        editor_lay.addRow("Image:", img_tmpl_row)

        tmpl_btn_row = QHBoxLayout()
        save_tmpl_btn = QPushButton("Save Template")
        save_tmpl_btn.setObjectName("PrimaryButton")
        save_tmpl_btn.clicked.connect(self._save_template)
        del_tmpl_btn = QPushButton("Delete")
        del_tmpl_btn.setObjectName("SecondaryButton")
        del_tmpl_btn.clicked.connect(self._delete_template)
        tmpl_btn_row.addWidget(save_tmpl_btn)
        tmpl_btn_row.addWidget(del_tmpl_btn)
        tmpl_btn_row.addStretch(1)
        editor_lay.addRow("", tmpl_btn_row)

        lay.addWidget(editor_group)

        self._populate_templates()
        return w

    # ── Accounts tab ─────────────────────────────────────────────────────────

    def _build_accounts_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 16)
        lay.setSpacing(16)

        bsky_group = QGroupBox("Bluesky")
        form = QFormLayout(bsky_group)

        handle_row = QHBoxLayout()
        self._bsky_handle_edit = QLineEdit()
        self._bsky_handle_edit.setPlaceholderText("yourname.bsky.social")
        self._bsky_handle_edit.setText(self._repo.get("bluesky_handle") or "")
        handle_row.addWidget(self._bsky_handle_edit, 1)
        form.addRow("Handle:", handle_row)

        pw_row = QHBoxLayout()
        self._bsky_pw_edit = QLineEdit()
        self._bsky_pw_edit.setEchoMode(QLineEdit.Password)
        self._bsky_pw_edit.setPlaceholderText("App password (not your real password)")
        # Don't pre-fill; user must re-enter to see/change
        pw_row.addWidget(self._bsky_pw_edit, 1)
        form.addRow("App password:", pw_row)

        pw_hint = QLabel(
            "Generate an app password at: Settings → Privacy and Security → App Passwords"
        )
        pw_hint.setObjectName("MetaText")
        pw_hint.setWordWrap(True)
        form.addRow("", pw_hint)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save && Connect")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_and_connect_bluesky)
        disconnect_btn = QPushButton("Disconnect")
        disconnect_btn.setObjectName("SecondaryButton")
        disconnect_btn.clicked.connect(self._disconnect_bluesky)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(disconnect_btn)
        btn_row.addStretch(1)
        form.addRow("", btn_row)

        self._bsky_status_lbl = QLabel()
        self._bsky_status_lbl.setWordWrap(True)
        form.addRow("Status:", self._bsky_status_lbl)

        lay.addWidget(bsky_group)
        lay.addStretch(1)
        self._refresh_connection_status()
        return w

    # ── Handles & Bot tab ─────────────────────────────────────────────────────

    def _build_handles_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 12, 0, 16)
        lay.setSpacing(16)

        handles_group = QGroupBox("Your Social Handles")
        form = QFormLayout(handles_group)

        handles = self._repo.get("social_handles") or {}
        self._handle_edits: dict[str, QLineEdit] = {}
        for platform, placeholder in [
            ("bluesky", "@yourname.bsky.social"),
            ("instagram", "@yourinstagram"),
            ("twitter", "@yourhandle"),
        ]:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setText(handles.get(platform, ""))
            edit.textChanged.connect(lambda v, p=platform: self._on_handle_changed(p, v))
            self._handle_edits[platform] = edit
            form.addRow(platform.title() + ":", edit)

        lay.addWidget(handles_group)

        # Bot commands
        bot_group = QGroupBox("Chat Bot Commands")
        bot_lay = QVBoxLayout(bot_group)

        info = QLabel(
            "These commands are registered with the Bot Manager. When a viewer types "
            "!bluesky or !instagram in chat, the bot responds automatically.\n\n"
            "Use {bluesky_url}, {instagram_handle}, {twitter_handle} as placeholders."
        )
        info.setObjectName("MetaText")
        info.setWordWrap(True)
        bot_lay.addWidget(info)

        self._bot_cmd_widgets: list[dict] = []
        self._bot_cmd_container = QVBoxLayout()
        bot_lay.addLayout(self._bot_cmd_container)

        add_cmd_btn = QPushButton("＋ Add Command")
        add_cmd_btn.setObjectName("SecondaryButton")
        add_cmd_btn.clicked.connect(self._add_bot_command)
        bot_lay.addWidget(add_cmd_btn)

        save_cmds_btn = QPushButton("Save Commands")
        save_cmds_btn.setObjectName("PrimaryButton")
        save_cmds_btn.clicked.connect(self._save_bot_commands)
        bot_lay.addWidget(save_cmds_btn)

        lay.addWidget(bot_group)
        lay.addStretch(1)
        scroll.setWidget(inner)

        self._populate_bot_commands()
        return scroll

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        text = self._text_edit.toPlainText()
        count = len(text)
        colour = "#f87171" if count > 300 else "#94a3b8"
        self._char_lbl.setText(f"{count} / 300")
        self._char_lbl.setStyleSheet(f"color:{colour};")

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.webp)"
        )
        if path:
            self._set_compose_image(path)

    def _clear_image(self) -> None:
        self._image_path = ""
        self._img_path_lbl.setText("No image selected")
        self._img_thumb.hide()

    def _set_compose_image(self, path: str) -> None:
        self._image_path = path
        self._img_path_lbl.setText(Path(path).name)
        pix = QPixmap(path)
        if not pix.isNull():
            self._img_thumb.setPixmap(
                pix.scaled(120, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._img_thumb.show()

    def _load_template_to_compose(self) -> None:
        tmpl = self._tmpl_combo_compose.current_template()
        if not tmpl:
            return
        text = self._plugin.resolve_template(tmpl.get("text", ""))
        self._text_edit.setPlainText(text)
        img = tmpl.get("image_path", "")
        if img and Path(img).exists():
            self._set_compose_image(img)
        else:
            self._clear_image()

    def _post_now(self) -> None:
        text = self._text_edit.toPlainText().strip()
        if not text:
            self._show_post_status("Enter some text first.", error=True)
            return
        if len(text) > 300:
            self._show_post_status("Text is over 300 characters.", error=True)
            return
        if not self._bsky_check.isChecked():
            self._show_post_status("Select at least one platform.", error=True)
            return

        self._post_btn.setEnabled(False)
        self._show_post_status("Posting…", error=False)

        image = self._image_path if self._image_path and Path(self._image_path).exists() else ""

        def _worker():
            try:
                if not self._client.connected:
                    raise RuntimeError("Not connected to Bluesky. Go to Accounts and connect first.")
                if image:
                    self._client.post_with_image(text, image)
                else:
                    self._client.post_text(text)
                self._sig.post_done.emit(True, "Posted successfully!")
            except Exception as exc:
                self._sig.post_done.emit(False, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_post_done(self, success: bool, msg: str) -> None:
        self._post_btn.setEnabled(True)
        self._show_post_status(msg, error=not success)
        if success:
            QTimer.singleShot(4000, lambda: self._post_status_lbl.hide())

    def _show_post_status(self, msg: str, *, error: bool) -> None:
        colour = "#f87171" if error else "#4ade80"
        self._post_status_lbl.setStyleSheet(f"color:{colour};")
        self._post_status_lbl.setText(msg)
        self._post_status_lbl.show()

    # ── Templates ─────────────────────────────────────────────────────────────

    def _populate_templates(self) -> None:
        self._tmpl_list.clear()
        for t in self._repo.list_templates():
            item = QListWidgetItem(t.get("name", "Untitled"))
            item.setData(Qt.UserRole, t.get("id", ""))
            self._tmpl_list.addItem(item)
        if self._tmpl_list.count():
            self._tmpl_list.setCurrentRow(0)
        self._tmpl_combo_compose.refresh()

    def _on_tmpl_selected(self, item: QListWidgetItem | None, _=None) -> None:
        if not item:
            return
        tid = item.data(Qt.UserRole)
        t = self._repo.get_template(tid)
        if not t:
            return
        self._tmpl_name_edit.setText(t.get("name", ""))
        self._tmpl_text_edit.setPlainText(t.get("text", ""))
        self._tmpl_img_edit.setText(t.get("image_path", ""))
        self._current_tmpl_id = tid

    def _new_template(self) -> None:
        tid = str(uuid.uuid4())[:8]
        t = {"id": tid, "name": "New Template", "text": "", "image_path": ""}
        self._repo.save_template(t)
        self._populate_templates()
        # Select the new one
        for i in range(self._tmpl_list.count()):
            if self._tmpl_list.item(i).data(Qt.UserRole) == tid:
                self._tmpl_list.setCurrentRow(i)
                break

    def _save_template(self) -> None:
        tid = getattr(self, "_current_tmpl_id", None)
        if not tid:
            return
        t = {
            "id": tid,
            "name": self._tmpl_name_edit.text().strip() or "Untitled",
            "text": self._tmpl_text_edit.toPlainText(),
            "image_path": self._tmpl_img_edit.text().strip(),
        }
        self._repo.save_template(t)
        self._populate_templates()

    def _delete_template(self) -> None:
        tid = getattr(self, "_current_tmpl_id", None)
        if not tid:
            return
        reply = QMessageBox.question(
            self, "Delete Template", "Delete this template?",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        self._repo.delete_template(tid)
        self._populate_templates()

    def _browse_tmpl_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.webp)"
        )
        if path:
            self._tmpl_img_edit.setText(path)

    # ── Bluesky account ───────────────────────────────────────────────────────

    def _save_and_connect_bluesky(self) -> None:
        handle = self._bsky_handle_edit.text().strip()
        pw = self._bsky_pw_edit.text().strip()
        if not handle or not pw:
            self._set_bsky_status("Enter both a handle and an app password.", error=True)
            return
        self._repo.set("bluesky_handle", handle)
        self._repo.set_secret("bluesky_app_password", pw)
        self._bsky_pw_edit.clear()

        self._set_bsky_status("Connecting…", error=False)

        def _worker():
            try:
                self._client.connect(handle, pw)
                self._sig.post_done.emit(True, f"Connected as @{self._client.handle}")
            except Exception as exc:
                self._sig.post_done.emit(False, f"Connection failed: {exc}")

        self._sig.post_done.disconnect()
        self._sig.post_done.connect(self._on_connect_done)
        threading.Thread(target=_worker, daemon=True).start()

    def _on_connect_done(self, success: bool, msg: str) -> None:
        self._set_bsky_status(msg, error=not success)
        self._repo.set("bluesky_enabled", success)
        # Re-wire post_done to normal handler
        self._sig.post_done.disconnect()
        self._sig.post_done.connect(self._on_post_done)

    def _disconnect_bluesky(self) -> None:
        self._client.disconnect()
        self._repo.set("bluesky_enabled", False)
        self._repo.delete_secret("bluesky_app_password")
        self._set_bsky_status("Disconnected.", error=False)

    def _set_bsky_status(self, msg: str, *, error: bool) -> None:
        if hasattr(self, "_bsky_status_lbl"):
            colour = "#f87171" if error else "#4ade80"
            self._bsky_status_lbl.setStyleSheet(f"color:{colour};")
            self._bsky_status_lbl.setText(msg)

    def _refresh_connection_status(self) -> None:
        if self._client.connected:
            self._set_bsky_status(f"Connected as @{self._client.handle}", error=False)
        else:
            self._set_bsky_status("Not connected", error=True)

    # ── Handles & bot commands ────────────────────────────────────────────────

    def _on_handle_changed(self, platform: str, value: str) -> None:
        handles = dict(self._repo.get("social_handles") or {})
        handles[platform] = value.strip()
        self._repo.set("social_handles", handles)

    def _populate_bot_commands(self) -> None:
        # Clear existing
        for entry in self._bot_cmd_widgets:
            entry["widget"].setParent(None)
        self._bot_cmd_widgets.clear()

        for cmd in self._repo.list_bot_commands():
            self._add_bot_command_row(cmd.get("command", ""), cmd.get("response", ""))

    def _add_bot_command(self) -> None:
        self._add_bot_command_row("", "")

    def _add_bot_command_row(self, command: str, response: str) -> None:
        w = QFrame()
        w.setFrameShape(QFrame.StyledPanel)
        row_lay = QFormLayout(w)
        cmd_edit = QLineEdit()
        cmd_edit.setPlaceholderText("instagram")
        cmd_edit.setText(command)
        resp_edit = QLineEdit()
        resp_edit.setPlaceholderText("Follow me on Instagram → {instagram_handle}")
        resp_edit.setText(response)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("SecondaryButton")
        del_btn.setFixedSize(28, 28)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("!"))
        header_row.addWidget(cmd_edit, 1)
        header_row.addWidget(del_btn)
        row_lay.addRow("Command:", header_row)
        row_lay.addRow("Response:", resp_edit)

        entry = {"widget": w, "cmd": cmd_edit, "resp": resp_edit}
        self._bot_cmd_widgets.append(entry)
        self._bot_cmd_container.addWidget(w)
        del_btn.clicked.connect(lambda: self._remove_bot_command_row(entry))

    def _remove_bot_command_row(self, entry: dict) -> None:
        entry["widget"].setParent(None)
        self._bot_cmd_widgets.remove(entry)

    def _save_bot_commands(self) -> None:
        commands = []
        for entry in self._bot_cmd_widgets:
            cmd = entry["cmd"].text().strip().lstrip("!")
            resp = entry["resp"].text().strip()
            if cmd and resp:
                commands.append({"command": cmd, "response": resp})
        self._repo.save_bot_commands(commands)
        self._plugin.sync_bot_commands()


class _TemplateCombo(QWidget):
    """Thin combo wrapper that always stays fresh."""

    def __init__(self, repo: "SocialRepository") -> None:
        from PySide6.QtWidgets import QComboBox
        super().__init__()
        self._repo = repo
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._combo = QComboBox()
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self._combo)
        self.refresh()

    def refresh(self) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        for t in self._repo.list_templates():
            self._combo.addItem(t.get("name", "Untitled"), t.get("id", ""))
        self._combo.blockSignals(False)

    def current_template(self) -> dict | None:
        tid = self._combo.currentData()
        if not tid:
            return None
        return self._repo.get_template(tid)
