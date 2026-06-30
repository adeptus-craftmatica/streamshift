from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_SERVICES = [
    ("obs_studio",   "🎬", "OBS"),
    ("scene_manager","🎭", "Scenes"),
    ("bot_manager",  "🤖", "Bots"),
    ("chat_manager", "💬", "Chat"),
    ("stream_stats", "📊", "Stats"),
    ("stream_info",  "ℹ️",  "Info"),
]


class QuickConnectTile(QFrame):
    """Compact stage-view card for connecting all services."""

    def __init__(self, app_context: AppContext) -> None:
        super().__init__()
        self._ctx = app_context
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("⚡  Quick Connect")
        title.setObjectName("CardTitle")
        title_row.addWidget(title, 1)
        root.addLayout(title_row)

        # Status dots row
        self._dots: dict[str, QLabel] = {}
        dots_row = QHBoxLayout()
        dots_row.setSpacing(8)
        for plugin_id, icon, short in _SERVICES:
            col = QVBoxLayout()
            col.setSpacing(2)
            dot = QLabel("●")
            dot.setStyleSheet("color:#64748b; font-size:14px;")
            dot.setAlignment(Qt.AlignCenter)
            lbl = QLabel(icon)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setToolTip(short)
            col.addWidget(dot)
            col.addWidget(lbl)
            dots_row.addLayout(col)
            self._dots[plugin_id] = dot
        dots_row.addStretch(1)
        root.addLayout(dots_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._connect_btn = QPushButton("Connect All")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.clicked.connect(self._connect_all)
        self._disconnect_btn = QPushButton("Disconnect All")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.clicked.connect(self._disconnect_all)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        root.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self.destroyed.connect(self._timer.stop)
        self._refresh()

    def _get_plugin(self, plugin_id: str):
        try:
            lp = self._ctx.plugin_manager._loaded_plugins.get(plugin_id)
            return lp.instance if lp else None
        except Exception:
            return None

    def _set_dot(self, plugin_id: str, connected: bool, connecting: bool = False) -> None:
        dot = self._dots.get(plugin_id)
        if dot is None:
            return
        if connecting:
            color = "#f59e0b"
        elif connected:
            color = "#22c55e"
        else:
            color = "#64748b"
        dot.setStyleSheet(f"color:{color}; font-size:14px;")

    def _refresh(self) -> None:
        # OBS
        obs = self._get_plugin("obs_studio")
        obs_conn = False
        try:
            obs_conn = obs._is_connected() if obs and hasattr(obs, "_is_connected") else False
        except Exception:
            pass
        self._set_dot("obs_studio", obs_conn)

        # Scene manager — has its own connection, not just OBS
        scene = self._get_plugin("scene_manager")
        scene_conn = False
        scene_connecting = False
        try:
            if scene:
                from stream_controller.plugins.scene_manager.scene_models import ConnectionStatus as SC
                client = getattr(scene, "_client", None)
                if client:
                    s = client.state.status
                    scene_conn = s == SC.CONNECTED
                    scene_connecting = s == SC.CONNECTING
        except Exception:
            pass
        self._set_dot("scene_manager", scene_conn, scene_connecting)

        # Bots
        bot = self._get_plugin("bot_manager")
        bot_conn = False
        try:
            if bot:
                engines = getattr(bot, "_engines", {})
                bot_conn = any(
                    e.state.twitch_connected or e.state.discord_connected
                    for e in engines.values()
                )
        except Exception:
            pass
        self._set_dot("bot_manager", bot_conn)

        # Chat
        chat = self._get_plugin("chat_manager")
        chat_conn = False
        chat_connecting = False
        try:
            if chat:
                from stream_controller.plugins.chat_manager.chat_models import ConnectionStatus
                state = getattr(chat, "_chat_state", None)
                if state:
                    s = state.state.status
                    chat_conn = s == ConnectionStatus.CONNECTED
                    chat_connecting = s == ConnectionStatus.CONNECTING
        except Exception:
            pass
        self._set_dot("chat_manager", chat_conn, chat_connecting)

        # Stats
        stats = self._get_plugin("stream_stats")
        stats_conn = False
        try:
            if stats:
                from stream_controller.plugins.stream_stats.stats_models import ConnectionStatus as SC
                engine = getattr(stats, "_engine", None)
                live = getattr(engine, "live", None) if engine else None
                stats_conn = getattr(live, "status", None) == SC.CONNECTED
        except Exception:
            pass
        self._set_dot("stream_stats", stats_conn)

        # Info
        info = self._get_plugin("stream_info")
        info_conn = False
        try:
            if info:
                from stream_controller.plugins.stream_info.info_models import ConnectionStatus as IC
                state = getattr(info, "_state", None)
                info_conn = getattr(state, "twitch_status", None) == IC.CONNECTED
        except Exception:
            pass
        self._set_dot("stream_info", info_conn)

    def _connect_all(self) -> None:
        qcp = self._get_qcp()
        if qcp:
            qcp._connect_all()
        else:
            self._connect_all_direct()
        QTimer.singleShot(1000, self._refresh)

    def _disconnect_all(self) -> None:
        qcp = self._get_qcp()
        if qcp:
            qcp._disconnect_all()
        else:
            self._disconnect_all_direct()
        QTimer.singleShot(500, self._refresh)

    def _get_qcp(self):
        """Return the QuickConnectPage instance if available (reuse its logic)."""
        try:
            lp = self._ctx.plugin_manager._loaded_plugins.get("quick_connect")
            if lp and lp.instance:
                return getattr(lp.instance, "_page", None)
        except Exception:
            pass
        return None

    def _connect_all_direct(self) -> None:
        obs = self._get_plugin("obs_studio")
        if obs and hasattr(obs, "connect"):
            obs.connect()
        scene = self._get_plugin("scene_manager")
        if scene and hasattr(scene, "do_connect"):
            scene.do_connect()
        bot = self._get_plugin("bot_manager")
        if bot and hasattr(bot, "start_all_bots"):
            bot.start_all_bots()
        chat = self._get_plugin("chat_manager")
        state = getattr(chat, "_chat_state", None) if chat else None
        if state and hasattr(state, "connect"):
            state.connect()
        stats = self._get_plugin("stream_stats")
        if stats and hasattr(stats, "do_connect"):
            stats.do_connect()
        info = self._get_plugin("stream_info")
        if info and hasattr(info, "do_connect"):
            info.do_connect()

    def _disconnect_all_direct(self) -> None:
        obs = self._get_plugin("obs_studio")
        if obs and hasattr(obs, "disconnect"):
            obs.disconnect()
        scene = self._get_plugin("scene_manager")
        if scene and hasattr(scene, "_client") and scene._client:
            scene._client.disconnect()
        bot = self._get_plugin("bot_manager")
        if bot and hasattr(bot, "stop_all_bots"):
            bot.stop_all_bots()
        chat = self._get_plugin("chat_manager")
        state = getattr(chat, "_chat_state", None) if chat else None
        if state and hasattr(state, "disconnect"):
            state.disconnect()
        stats = self._get_plugin("stream_stats")
        if stats and hasattr(stats, "do_disconnect"):
            stats.do_disconnect()
        info = self._get_plugin("stream_info")
        if info and hasattr(info, "do_disconnect"):
            info.do_disconnect()
