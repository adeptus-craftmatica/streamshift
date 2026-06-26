from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)


class ServiceCard(QFrame):
    """A single service row with status dot, name, and connect/disconnect buttons."""

    def __init__(self, icon: str, name: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#64748b; font-size:16px;")
        self._dot.setFixedWidth(20)
        lay.addWidget(self._dot)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:18px;")
        icon_lbl.setFixedWidth(26)
        lay.addWidget(icon_lbl)

        self._name_lbl = QLabel(name)
        self._name_lbl.setObjectName("CardTitle")
        lay.addWidget(self._name_lbl, 1)

        self._status_lbl = QLabel("Not connected")
        self._status_lbl.setObjectName("MetaText")
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._status_lbl)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.setFixedWidth(100)
        lay.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.setFixedWidth(100)
        self._disconnect_btn.setVisible(False)
        lay.addWidget(self._disconnect_btn)

    def set_status(self, connected: bool, connecting: bool = False, label: str = "") -> None:
        if connecting:
            color = "#f59e0b"
            text = label or "Connecting…"
        elif connected:
            color = "#22c55e"
            text = label or "Connected"
        else:
            color = "#64748b"
            text = label or "Not connected"

        self._dot.setStyleSheet(f"color:{color}; font-size:16px;")
        self._status_lbl.setText(text)
        self._connect_btn.setVisible(not connected and not connecting)
        self._disconnect_btn.setVisible(connected)

    def on_connect(self, fn) -> None:
        self._connect_btn.clicked.connect(fn)

    def on_disconnect(self, fn) -> None:
        self._disconnect_btn.clicked.connect(fn)


class QuickConnectPage(QWidget):
    def __init__(self, app_context: "AppContext") -> None:
        super().__init__()
        self._ctx = app_context

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        # Header actions
        hdr = QHBoxLayout()
        title = QLabel("Services")
        title.setObjectName("CardTitle")
        hdr.addWidget(title, 1)

        self._connect_all_btn = QPushButton("⚡  Connect All")
        self._connect_all_btn.setObjectName("PrimaryButton")
        self._connect_all_btn.clicked.connect(self._connect_all)
        hdr.addWidget(self._connect_all_btn)

        self._disconnect_all_btn = QPushButton("✕  Disconnect All")
        self._disconnect_all_btn.setObjectName("SecondaryButton")
        self._disconnect_all_btn.clicked.connect(self._disconnect_all)
        hdr.addWidget(self._disconnect_all_btn)

        root.addLayout(hdr)

        desc = QLabel(
            "Connect or disconnect all your streaming services at once, "
            "or manage each one individually below."
        )
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # Service cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._cards_layout = QVBoxLayout(inner)
        self._cards_layout.setSpacing(10)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # Build service cards
        self._bots_card = self._add_card("🤖", "Bots (Twitch + Discord)")
        self._bots_card.on_connect(self._connect_bots)
        self._bots_card.on_disconnect(self._disconnect_bots)

        self._chat_card = self._add_card("💬", "Twitch Chat")
        self._chat_card.on_connect(self._connect_chat)
        self._chat_card.on_disconnect(self._disconnect_chat)

        self._stats_card = self._add_card("📊", "Stream Stats")
        self._stats_card.on_connect(self._connect_stats)
        self._stats_card.on_disconnect(self._disconnect_stats)

        self._info_card = self._add_card("ℹ️", "Stream Info")
        self._info_card.on_connect(self._connect_info)
        self._info_card.on_disconnect(self._disconnect_info)

        self._obs_card = self._add_card("🎬", "OBS Studio")
        self._obs_card.on_connect(self._connect_obs)
        self._obs_card.on_disconnect(self._disconnect_obs)

        self._pngtuber_card = self._add_card("🎭", "PNGtuber")
        self._pngtuber_card.on_connect(self._connect_pngtuber)
        self._pngtuber_card.on_disconnect(self._disconnect_pngtuber)

        # Poll status every 2 seconds
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()
        self._refresh_status()

    def _add_card(self, icon: str, name: str) -> ServiceCard:
        card = ServiceCard(icon, name)
        # Insert before the stretch
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        return card

    # ── Plugin accessors ──────────────────────────────────────────────────────

    def _get_plugin(self, plugin_id: str):
        try:
            lp = self._ctx.plugin_manager._loaded_plugins.get(plugin_id)
            return lp.instance if lp else None
        except Exception:
            return None

    # ── Bots ─────────────────────────────────────────────────────────────────

    def _connect_bots(self) -> None:
        plugin = self._get_plugin("bot_manager")
        if plugin and hasattr(plugin, "start_all_bots"):
            plugin.start_all_bots(on_alert=self._on_bot_alert)

    def _on_bot_alert(self, event_type: str, username: str, extra: dict) -> None:
        """Bridge EventSub events (follows, channel points, subs, bits, raids) into
        ChatStateManager so they appear in the Alerts tile and Live Chat tile."""
        try:
            from datetime import datetime
            import uuid
            from stream_controller.plugins.chat_manager.chat_models import ChatMessage, MsgType
            chat_plugin = self._get_plugin("chat_manager")
            if not chat_plugin:
                return
            mgr = getattr(chat_plugin, "_chat_state", None)
            if not mgr:
                return

            _type_map = {
                "sub":            MsgType.SUB,
                "resub":          MsgType.RESUB,
                "subgift":        MsgType.SUBGIFT,
                "giftsub":        MsgType.SUBGIFT,
                "raid":           MsgType.RAID,
                "bits":           MsgType.BITS,
                "channel_points": MsgType.CHANNEL_POINTS,
                "follow":         MsgType.RITUAL,  # closest alert type
            }
            msg_type = _type_map.get(event_type, MsgType.SUB)

            _labels = {
                "sub":            f"{username} just subscribed! 🎉",
                "resub":          f"{username} resubscribed! 🔄",
                "subgift":        f"{username} gifted a sub! 🎁",
                "giftsub":        f"{username} gifted a sub! 🎁",
                "raid":           f"{username} raided with {extra.get('viewers', '?')} viewers! ⚔",
                "bits":           f"{username} cheered {extra.get('amount', '?')} bits! 💎",
                "channel_points": f"{username} redeemed '{extra.get('reward', 'reward')}' 🏆",
                "follow":         f"{username} just followed! ❤️",
            }
            text = _labels.get(event_type, f"{username}: {event_type}")

            msg = ChatMessage(
                msg_id=uuid.uuid4().hex,
                ts=datetime.now(),
                username=username,
                display_name=username,
                color="",
                badges=[],
                text=text,
                system_text=text,
                channel=mgr.state.channel or "",
                msg_type=msg_type,
                is_sub=event_type in ("sub", "resub", "subgift", "giftsub"),
            )
            # ChatStateManager._on_message runs on the main thread via the signal
            mgr._on_message(msg)
        except Exception as exc:
            logger.debug("alert bridge error: %s", exc)

    def _disconnect_bots(self) -> None:
        plugin = self._get_plugin("bot_manager")
        if plugin and hasattr(plugin, "stop_all_bots"):
            plugin.stop_all_bots()

    def _bot_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("bot_manager")
        if not plugin:
            return False, "Plugin not loaded"
        engines = getattr(plugin, "_engines", {})
        repo = getattr(plugin, "_repo", None)
        total = len(repo.list_bots()) if repo else len(engines)
        if not total:
            return False, "No bots configured"
        connected = [e for e in engines.values() if e.state.twitch_connected or e.state.discord_connected]
        if connected:
            return True, f"{len(connected)}/{total} bots connected"
        connecting = [e for e in engines.values()]  # engines exist but not yet connected
        if connecting:
            return False, f"Connecting… ({len(connecting)}/{total})"
        return False, f"0/{total} bots connected"

    # ── Chat ─────────────────────────────────────────────────────────────────

    def _connect_chat(self) -> None:
        plugin = self._get_plugin("chat_manager")
        if not plugin:
            return
        state = getattr(plugin, "_chat_state", None)
        if state and hasattr(state, "connect"):
            state.connect()

    def _disconnect_chat(self) -> None:
        plugin = self._get_plugin("chat_manager")
        if not plugin:
            return
        state = getattr(plugin, "_chat_state", None)
        if state and hasattr(state, "disconnect"):
            state.disconnect()

    def _chat_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("chat_manager")
        if not plugin:
            return False, "Plugin not loaded"
        mgr = getattr(plugin, "_chat_state", None)
        if not mgr:
            return False, "Not configured"
        try:
            from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus
            chat_state = mgr.state
            s = chat_state.status
            if s == ConnectionStatus.CONNECTED:
                channel = chat_state.channel or ""
                return True, f"Connected{' to #' + channel if channel else ''}"
            elif s == ConnectionStatus.CONNECTING:
                return False, "Connecting…"
            else:
                return False, "Not connected"
        except Exception:
            return False, "Unknown"

    # ── Stream Stats ──────────────────────────────────────────────────────────

    def _connect_stats(self) -> None:
        plugin = self._get_plugin("stream_stats")
        if plugin and hasattr(plugin, "do_connect"):
            plugin.do_connect()

    def _disconnect_stats(self) -> None:
        plugin = self._get_plugin("stream_stats")
        if plugin and hasattr(plugin, "do_disconnect"):
            plugin.do_disconnect()

    def _stats_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("stream_stats")
        if not plugin:
            return False, "Plugin not loaded"
        try:
            from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus
            engine = getattr(plugin, "_engine", None)
            if engine is None:
                return False, "Not initialised"
            live = getattr(engine, "live", None)
            status = getattr(live, "status", None) if live else None
            if status == ConnectionStatus.CONNECTED:
                return True, "Connected"
            elif status == ConnectionStatus.CONNECTING:
                return False, "Connecting…"
            elif status == ConnectionStatus.ERROR:
                error = getattr(live, "error", "") if live else ""
                return False, f"Error: {error[:40]}" if error else "Error"
            else:
                return False, "Not connected"
        except Exception:
            return False, "Unknown"

    # ── Stream Info ───────────────────────────────────────────────────────────

    def _connect_info(self) -> None:
        plugin = self._get_plugin("stream_info")
        if not plugin:
            return
        token = plugin.repo.get("oauth_token") if hasattr(plugin, "repo") and plugin.repo else ""
        if not token:
            # No token — show error state; user must authorize in Stream Info → Settings
            from stream_controller.plugins.stream_info.info_models import ConnectionStatus
            plugin._state.twitch_status = ConnectionStatus.ERROR
            plugin._state.error = "Authorize in Stream Info → Settings first."
            plugin._signals.state_changed.emit()
            return
        if hasattr(plugin, "do_connect"):
            plugin.do_connect()

    def _disconnect_info(self) -> None:
        plugin = self._get_plugin("stream_info")
        if plugin and hasattr(plugin, "do_disconnect"):
            plugin.do_disconnect()

    def _info_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("stream_info")
        if not plugin:
            return False, "Plugin not loaded"
        try:
            from stream_controller.plugins.stream_info.info_models import ConnectionStatus
            state = getattr(plugin, "_state", None)
            if state is None:
                return False, "Not initialised"
            status = getattr(state, "twitch_status", None)
            if status == ConnectionStatus.CONNECTED:
                info = getattr(state, "info", None)
                title = getattr(info, "title", "") or "" if info else ""
                return True, f"Connected · {title[:30]}" if title else "Connected"
            elif status == ConnectionStatus.CONNECTING:
                return False, "Connecting…"
            elif status == ConnectionStatus.ERROR:
                error = getattr(state, "error", "") or ""
                return False, f"Error: {error[:40]}" if error else "Error"
            else:
                return False, "Not connected"
        except Exception:
            return False, "Unknown"

    # ── OBS ──────────────────────────────────────────────────────────────────

    def _connect_obs(self) -> None:
        plugin = self._get_plugin("obs_studio")
        if plugin and hasattr(plugin, "connect"):
            plugin.connect()

    def _disconnect_obs(self) -> None:
        plugin = self._get_plugin("obs_studio")
        if plugin and hasattr(plugin, "disconnect"):
            plugin.disconnect()

    def _obs_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("obs_studio")
        if not plugin:
            return False, "Plugin not loaded"
        try:
            connected = plugin._is_connected() if hasattr(plugin, "_is_connected") else False
            return connected, "Connected" if connected else "Not connected"
        except Exception:
            return False, "Unknown"

    # ── Aggregate ─────────────────────────────────────────────────────────────

    # ── PNGtuber ──────────────────────────────────────────────────────────────

    def _connect_pngtuber(self) -> None:
        plugin = self._get_plugin("pngtuber")
        if plugin and hasattr(plugin, "start"):
            plugin.start()

    def _disconnect_pngtuber(self) -> None:
        plugin = self._get_plugin("pngtuber")
        if plugin and hasattr(plugin, "stop"):
            plugin.stop()

    def _pngtuber_status(self) -> tuple[bool, str]:
        plugin = self._get_plugin("pngtuber")
        if not plugin:
            return False, "Plugin not loaded"
        try:
            st = plugin.get_state()
            running = st.get("running", False)
            state = st.get("state", "idle")
            return running, state.capitalize() if running else "Stopped"
        except Exception:
            return False, "Unknown"

    # ── Aggregate ─────────────────────────────────────────────────────────────

    def _connect_all(self) -> None:
        self._connect_bots()
        self._connect_chat()
        self._connect_stats()
        self._connect_info()
        self._connect_obs()
        self._connect_pngtuber()
        QTimer.singleShot(1000, self._refresh_status)

    def _disconnect_all(self) -> None:
        self._disconnect_bots()
        self._disconnect_chat()
        self._disconnect_stats()
        self._disconnect_info()
        self._disconnect_obs()
        self._disconnect_pngtuber()
        QTimer.singleShot(500, self._refresh_status)

    def _refresh_status(self) -> None:
        bot_conn, bot_lbl = self._bot_status()
        self._bots_card.set_status(bot_conn, label=bot_lbl)

        chat_conn, chat_lbl = self._chat_status()
        connecting = "Connecting" in chat_lbl
        self._chat_card.set_status(chat_conn, connecting=connecting, label=chat_lbl)

        stats_conn, stats_lbl = self._stats_status()
        stats_connecting = "Connecting" in stats_lbl
        self._stats_card.set_status(stats_conn, connecting=stats_connecting, label=stats_lbl)

        info_conn, info_lbl = self._info_status()
        info_connecting = "Connecting" in info_lbl
        self._info_card.set_status(info_conn, connecting=info_connecting, label=info_lbl)

        obs_conn, obs_lbl = self._obs_status()
        self._obs_card.set_status(obs_conn, label=obs_lbl)

        png_conn, png_lbl = self._pngtuber_status()
        self._pngtuber_card.set_status(png_conn, label=png_lbl)
