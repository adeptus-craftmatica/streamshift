from __future__ import annotations

"""
First-time setup wizard for StreamShift.

Walks the user through:
  1. Welcome
  2. Twitch app — Client ID + channel name (written to all three Twitch plugins)
  3. Twitch authorization — single combined OAuth, token written to all plugins
  4. OBS WebSocket — host / port / password with a live connection test
  5. Done

Completion is recorded in QSettings so the wizard never shows again unless
the user explicitly re-opens it from the main menu.
"""

import json
import logging
import threading
import urllib.request
import urllib.error

from PySide6.QtCore import Qt, QSettings, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from stream_controller.core.twitch_auth import TwitchAuthFlow
from stream_controller.core.ssl_helper import make_ssl_context

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "setup_wizard_complete"

# Combined scopes for all Twitch-enabled plugins
_ALL_SCOPES = "+".join([
    "chat:read",
    "chat:edit",
    "channel:moderate",
    "moderator:manage:banned_users",
    "moderator:manage:chat_messages",
    "moderator:read:chatters",
    "channel:manage:broadcast",
    "channel:read:subscriptions",
    "bits:read",
    "moderator:read:followers",
])

_SSL = make_ssl_context()


def is_setup_complete() -> bool:
    return bool(QSettings("StreamShift", "StreamController").value(_SETTINGS_KEY, False, type=bool))


def mark_setup_complete() -> None:
    QSettings("StreamShift", "StreamController").setValue(_SETTINGS_KEY, True)


def reset_setup() -> None:
    """Call from settings to allow the user to re-run the wizard."""
    QSettings("StreamShift", "StreamController").setValue(_SETTINGS_KEY, False)


# ── Internal signal carrier ───────────────────────────────────────────────────

class _WizSignals(QObject):
    auth_ok  = Signal(str, str)   # token, username
    auth_err = Signal(str)
    obs_ok   = Signal()
    obs_err  = Signal(str)


# ── Step indicator ────────────────────────────────────────────────────────────

class _StepDots(QWidget):
    def __init__(self, total: int, parent=None) -> None:
        super().__init__(parent)
        self._total  = total
        self._current = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        self._dots: list[QLabel] = []
        for _ in range(total):
            d = QLabel("●")
            d.setFixedWidth(16)
            d.setAlignment(Qt.AlignCenter)
            self._dots.append(d)
            lay.addWidget(d)
        lay.addStretch(1)
        self._refresh()

    def set_step(self, idx: int) -> None:
        self._current = idx
        self._refresh()

    def _refresh(self) -> None:
        for i, d in enumerate(self._dots):
            if i == self._current:
                d.setStyleSheet("color: #7c3aed; font-size: 14px;")
            elif i < self._current:
                d.setStyleSheet("color: #22c55e; font-size: 10px;")
            else:
                d.setStyleSheet("color: #334155; font-size: 10px;")


# ── Individual pages ──────────────────────────────────────────────────────────

def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(32, 24, 32, 16)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    s = QLabel(subtitle)
    s.setObjectName("CardDescription")
    s.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(s)
    lay.addSpacing(8)
    return w, lay


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setObjectName("Separator")
    return f


def _field(label: str, placeholder: str = "", password: bool = False) -> tuple[QLabel, QLineEdit]:
    lbl = QLabel(label)
    lbl.setObjectName("MetaText")
    inp = QLineEdit()
    inp.setObjectName("ChatSendInput")
    inp.setPlaceholderText(placeholder)
    if password:
        inp.setEchoMode(QLineEdit.Password)
    return lbl, inp


def _status_label() -> QLabel:
    lbl = QLabel("")
    lbl.setObjectName("MetaText")
    lbl.setWordWrap(True)
    return lbl


# ── The Wizard ────────────────────────────────────────────────────────────────

class SetupWizard(QDialog):
    """Modal setup wizard shown on first launch."""

    # Page indices
    _P_WELCOME = 0
    _P_TWITCH  = 1
    _P_AUTH    = 2
    _P_OBS     = 3
    _P_DONE    = 4
    _TOTAL     = 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("StreamShift — First-Time Setup")
        self.setMinimumSize(620, 500)
        self.setMaximumSize(700, 580)
        self.setModal(True)

        self._sigs = _WizSignals()
        self._sigs.auth_ok.connect(self._on_auth_ok)
        self._sigs.auth_err.connect(self._on_auth_err)
        self._sigs.obs_ok.connect(self._on_obs_ok)
        self._sigs.obs_err.connect(self._on_obs_err)

        self._token    = ""
        self._username = ""
        self._obs_ok   = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Step dots
        self._dots = _StepDots(self._TOTAL)
        root.addWidget(self._dots)
        root.addWidget(_divider())

        # Page stack
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._stack, 1)

        root.addWidget(_divider())

        # Nav buttons
        nav = QHBoxLayout()
        nav.setContentsMargins(24, 12, 24, 16)
        self._back_btn = QPushButton("← Back")
        self._back_btn.setObjectName("SecondaryButton")
        self._back_btn.clicked.connect(self._go_back)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setObjectName("SecondaryButton")
        self._skip_btn.clicked.connect(self._skip)
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.setMinimumWidth(100)
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._skip_btn)
        nav.addStretch(1)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        self._build_pages()
        self._go_to(self._P_WELCOME)

    # ── Page builders ─────────────────────────────────────────────────────────

    def _build_pages(self) -> None:
        self._stack.addWidget(self._build_welcome())
        self._stack.addWidget(self._build_twitch())
        self._stack.addWidget(self._build_auth())
        self._stack.addWidget(self._build_obs())
        self._stack.addWidget(self._build_done())

    def _build_welcome(self) -> QWidget:
        w, lay = _page(
            "Welcome to StreamShift",
            "Let's get you connected in a few quick steps. You'll set up your Twitch "
            "integration, OBS connection, and have everything ready to go live."
        )
        cards = [
            ("🎮", "Twitch",   "Authorize once to enable chat, stream info, and stats."),
            ("🎬", "OBS",      "Connect to OBS WebSocket to control scenes and go live."),
            ("✅", "All done", "Everything saves securely and you're ready to stream."),
        ]
        for icon, title, desc in cards:
            card = QFrame()
            card.setObjectName("Card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(12)
            ic = QLabel(icon)
            ic.setFixedWidth(28)
            ic.setStyleSheet("font-size: 20px;")
            body = QVBoxLayout()
            body.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("CardTitle")
            d = QLabel(desc)
            d.setObjectName("CardDescription")
            d.setWordWrap(True)
            body.addWidget(t)
            body.addWidget(d)
            cl.addWidget(ic, 0, Qt.AlignTop)
            cl.addLayout(body, 1)
            lay.addWidget(card)

        lay.addStretch(1)

        self._dont_show_chk = QCheckBox("Don't show this wizard on startup again")
        lay.addWidget(self._dont_show_chk)

        return w

    def _build_twitch(self) -> QWidget:
        w, lay = _page(
            "Twitch App Setup",
            "Create a free Twitch Developer app to get your Client ID. One app works "
            "for all StreamShift features — you only need to do this once."
        )

        how = QFrame()
        how.setObjectName("Card")
        hl = QVBoxLayout(how)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(4)
        steps_lbl = QLabel(
            "1.  Go to <b>dev.twitch.tv/console/apps</b> and click <b>Register Your Application</b>.<br>"
            "2.  Name: anything (e.g. StreamShift). Category: Other.<br>"
            "3.  OAuth Redirect URL: <b>http://localhost:47893/callback</b><br>"
            "4.  Copy the <b>Client ID</b> shown on the app page and paste it below."
        )
        steps_lbl.setObjectName("CardDescription")
        steps_lbl.setWordWrap(True)
        steps_lbl.setTextFormat(Qt.RichText)
        hl.addWidget(steps_lbl)
        lay.addWidget(how)
        lay.addSpacing(6)

        lbl_cid, self._cid_input = _field("Client ID", "Paste your Twitch Client ID here…")
        lbl_ch,  self._ch_input  = _field("Your Twitch channel name", "e.g.  yourchannel")
        for lbl, inp in ((lbl_cid, self._cid_input), (lbl_ch, self._ch_input)):
            lay.addWidget(lbl)
            lay.addWidget(inp)

        self._twitch_status = _status_label()
        lay.addWidget(self._twitch_status)
        lay.addStretch(1)
        return w

    def _build_auth(self) -> QWidget:
        w, lay = _page(
            "Authorize with Twitch",
            "Click the button below to open Twitch in your browser. Log in with the "
            "account you stream from and click Authorize. StreamShift requests all "
            "permissions it needs in one go — chat, stream info, and viewer stats."
        )

        self._auth_btn = QPushButton("🔐  Authorize with Twitch")
        self._auth_btn.setObjectName("PrimaryButton")
        self._auth_btn.setMinimumHeight(44)
        self._auth_btn.clicked.connect(self._start_auth)
        lay.addWidget(self._auth_btn)

        self._auth_status = _status_label()
        lay.addWidget(self._auth_status)
        lay.addStretch(1)

        hint = QLabel(
            "Twitch will show every permission being granted. "
            "No credentials are ever sent to StreamShift servers — "
            "the token goes directly from Twitch to this app on your machine."
        )
        hint.setObjectName("CardDescription")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _build_obs(self) -> QWidget:
        w, lay = _page(
            "OBS WebSocket  (optional)",
            "StreamShift can control OBS to switch scenes and start/stop your stream. "
            "Enable WebSocket in OBS → Tools → WebSocket Server Settings, then enter "
            "the details below. You can skip this and set it up later in Settings."
        )

        lbl_host, self._obs_host = _field("Host", "localhost")
        lbl_port, self._obs_port = _field("Port", "4455")
        lbl_pw,   self._obs_pw   = _field("Password", "OBS WebSocket password…", password=True)
        self._obs_port.setText("4455")
        self._obs_host.setText("localhost")

        for lbl, inp in ((lbl_host, self._obs_host), (lbl_port, self._obs_port), (lbl_pw, self._obs_pw)):
            lay.addWidget(lbl)
            lay.addWidget(inp)

        test_btn = QPushButton("Test Connection")
        test_btn.setObjectName("SecondaryButton")
        test_btn.clicked.connect(self._test_obs)
        lay.addWidget(test_btn)

        self._obs_status = _status_label()
        lay.addWidget(self._obs_status)
        lay.addStretch(1)
        return w

    def _build_done(self) -> QWidget:
        w, lay = _page(
            "You're all set! 🎉",
            "StreamShift is connected and ready. Here's a summary of what was configured:"
        )
        self._done_summary = QLabel("")
        self._done_summary.setObjectName("CardDescription")
        self._done_summary.setWordWrap(True)
        self._done_summary.setTextFormat(Qt.RichText)
        lay.addWidget(self._done_summary)
        lay.addStretch(1)

        tip = QLabel(
            "💡 Tip: You can re-run this wizard any time from <b>Help → Setup Wizard</b>."
        )
        tip.setObjectName("CardDescription")
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.RichText)
        lay.addWidget(tip)
        return w

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_to(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        self._dots.set_step(idx)
        self._back_btn.setVisible(idx > self._P_WELCOME)
        self._skip_btn.setVisible(idx == self._P_OBS)

        if idx == self._P_DONE:
            self._next_btn.setText("Launch StreamShift")
            self._skip_btn.hide()
        elif idx == self._P_WELCOME:
            self._next_btn.setText("Get Started →")
        else:
            self._next_btn.setText("Next →")

        if idx == self._P_DONE:
            self._build_done_summary()

    def reject(self) -> None:
        """Close / Escape: honour the 'Don't show again' checkbox."""
        if self._dont_show_chk.isChecked():
            mark_setup_complete()
        super().reject()

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx == self._P_TWITCH and not self._validate_twitch_page():
            return
        if idx == self._P_AUTH and not self._token:
            self._auth_status.setText("Please authorize with Twitch before continuing.")
            self._auth_status.setStyleSheet("color: #ef4444;")
            return
        if idx == self._P_DONE:
            mark_setup_complete()
            self.accept()
            return
        self._go_to(idx + 1)

    def _go_back(self) -> None:
        self._go_to(self._stack.currentIndex() - 1)

    def _skip(self) -> None:
        # Only the OBS page is skippable
        self._go_to(self._P_DONE)

    # ── Twitch page validation ────────────────────────────────────────────────

    def _validate_twitch_page(self) -> bool:
        cid = self._cid_input.text().strip()
        ch  = self._ch_input.text().strip().lstrip("#").lower()
        if not cid:
            self._twitch_status.setText("Client ID is required.")
            self._twitch_status.setStyleSheet("color: #ef4444;")
            return False
        if not ch:
            self._twitch_status.setText("Channel name is required.")
            self._twitch_status.setStyleSheet("color: #ef4444;")
            return False
        self._twitch_status.setText("")
        self._save_twitch_app_settings(cid, ch)
        return True

    def _save_twitch_app_settings(self, client_id: str, channel: str) -> None:
        """Write client_id and channel to all Twitch-enabled plugin repos."""
        try:
            from stream_controller.plugins.chat_manager.chat_repository import ChatRepository
            r = ChatRepository()
            r.set("client_id", client_id)
            r.set("channel", channel)
        except Exception as e:
            logger.warning("wizard: chat_manager repo write failed: %s", e)
        try:
            from stream_controller.plugins.stream_info.info_repository import InfoRepository
            r = InfoRepository()
            r.set("client_id", client_id)
        except Exception as e:
            logger.warning("wizard: stream_info repo write failed: %s", e)
        try:
            from stream_controller.plugins.stream_stats.stats_repository import StatsRepository
            r = StatsRepository()
            r.set("client_id", client_id)
            r.set("channel", channel)
        except Exception as e:
            logger.warning("wizard: stream_stats repo write failed: %s", e)

    # ── Auth page ─────────────────────────────────────────────────────────────

    def _start_auth(self) -> None:
        cid = self._cid_input.text().strip()
        if not cid:
            self._auth_status.setText("Go back and enter your Client ID first.")
            self._auth_status.setStyleSheet("color: #ef4444;")
            return
        self._auth_btn.setEnabled(False)
        self._auth_status.setText("Waiting for Twitch… (check your browser)")
        self._auth_status.setStyleSheet("color: #f59e0b;")
        flow = TwitchAuthFlow(
            client_id=cid,
            scopes=_ALL_SCOPES,
            on_complete=self._sigs.auth_ok.emit,
            on_error=self._sigs.auth_err.emit,
        )
        flow.start()

    def _resolve_username(self, token: str, client_id: str) -> None:
        def _worker():
            try:
                req = urllib.request.Request("https://api.twitch.tv/helix/users")
                req.add_header("Authorization", f"Bearer {token}")
                req.add_header("Client-Id", client_id)
                with urllib.request.urlopen(req, timeout=8, context=_SSL) as r:
                    data = json.loads(r.read())
                    login = (data.get("data") or [{}])[0].get("login", "")
                self._sigs.auth_ok.emit(token, login)
            except Exception:
                self._sigs.auth_ok.emit(token, "")
        # Already on main thread from signal; run network in background
        threading.Thread(target=_worker, daemon=True).start()

    def _finish_auth(self, token: str, username: str) -> None:
        self._token    = token
        self._username = username
        display = f"✓ Authorized as @{username}" if username else "✓ Authorized"
        self._auth_status.setText(display)
        self._auth_status.setStyleSheet("color: #22c55e;")
        self._auth_btn.setText("✓  Authorized — Re-authorize")
        self._auth_btn.setEnabled(True)
        self._save_auth(token, username)

    def _on_auth_ok(self, token: str, username: str) -> None:
        if not username:
            # Need to resolve from Helix
            self._token = token
            self._resolve_username(token, self._cid_input.text().strip())
        else:
            self._finish_auth(token, username)

    def _on_auth_err(self, msg: str) -> None:
        self._auth_status.setText(f"Error: {msg}")
        self._auth_status.setStyleSheet("color: #ef4444;")
        self._auth_btn.setEnabled(True)

    def _save_auth(self, token: str, username: str) -> None:
        """Write token and username to all Twitch plugin repos."""
        try:
            from stream_controller.plugins.chat_manager.chat_repository import ChatRepository
            r = ChatRepository()
            r.set("oauth_token", token)
            if username:
                r.set("username", username)
        except Exception as e:
            logger.warning("wizard: chat_manager token write failed: %s", e)
        try:
            from stream_controller.plugins.stream_info.info_repository import InfoRepository
            r = InfoRepository()
            r.set("oauth_token", token)
        except Exception as e:
            logger.warning("wizard: stream_info token write failed: %s", e)
        try:
            from stream_controller.plugins.stream_stats.stats_repository import StatsRepository
            r = StatsRepository()
            r.set("oauth_token", token)
            if username:
                r.set("channel", username)
        except Exception as e:
            logger.warning("wizard: stream_stats token write failed: %s", e)

    # ── OBS page ──────────────────────────────────────────────────────────────

    def _test_obs(self) -> None:
        host = self._obs_host.text().strip() or "localhost"
        port_str = self._obs_port.text().strip() or "4455"
        pw   = self._obs_pw.text()
        try:
            port = int(port_str)
        except ValueError:
            self._obs_status.setText("Port must be a number.")
            self._obs_status.setStyleSheet("color: #ef4444;")
            return

        self._obs_status.setText("Testing connection…")
        self._obs_status.setStyleSheet("color: #f59e0b;")

        def _worker():
            try:
                from obsws_python import ReqClient
                c = ReqClient(host=host, port=port, password=pw, timeout=5)
                c.disconnect()
                self._sigs.obs_ok.emit()
            except Exception as exc:
                self._sigs.obs_err.emit(str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_obs_ok(self) -> None:
        self._obs_ok = True
        self._obs_status.setText("✓ Connected to OBS successfully")
        self._obs_status.setStyleSheet("color: #22c55e;")
        self._save_obs()

    def _on_obs_err(self, msg: str) -> None:
        self._obs_ok = False
        self._obs_status.setText(f"✗ Could not connect: {msg}")
        self._obs_status.setStyleSheet("color: #ef4444;")

    def _save_obs(self) -> None:
        host = self._obs_host.text().strip() or "localhost"
        pw   = self._obs_pw.text()
        try:
            port = int(self._obs_port.text().strip() or "4455")
        except ValueError:
            port = 4455
        try:
            from stream_controller.plugins.scene_manager.scene_repository import SceneRepository
            r = SceneRepository()
            r.set("host",     host)
            r.set("port",     port)
            r.set("password", pw)
        except Exception as e:
            logger.warning("wizard: scene_manager obs write failed: %s", e)
        try:
            from stream_controller.plugins.stream_info.info_repository import InfoRepository
            r = InfoRepository()
            r.set("obs_host",     host)
            r.set("obs_port",     port)
            r.set("obs_password", pw)
        except Exception as e:
            logger.warning("wizard: stream_info obs write failed: %s", e)

    # ── Done page ─────────────────────────────────────────────────────────────

    def _build_done_summary(self) -> None:
        lines = []
        if self._token:
            who = f" as <b>@{self._username}</b>" if self._username else ""
            lines.append(f"✅  Twitch authorized{who}")
            lines.append("✅  Chat, Stream Info, and Stream Stats connected")
        else:
            lines.append("⚠️  Twitch not authorized — open each plugin's Settings tab to connect")
        if self._obs_ok:
            lines.append(f"✅  OBS WebSocket connected ({self._obs_host.text()}:{self._obs_port.text()})")
        else:
            lines.append("ℹ️  OBS not connected — set it up in Scene Manager → Settings")
        self._done_summary.setText("<br>".join(lines))
