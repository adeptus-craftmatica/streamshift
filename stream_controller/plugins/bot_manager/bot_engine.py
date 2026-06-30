from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.request
import urllib.error
import uuid
from typing import Callable

from PySide6.QtCore import QObject, Signal, QMetaObject, Qt

from stream_controller.plugins.bot_manager.bot_database import BotDatabase
from stream_controller.plugins.bot_manager.bot_models import (
    BotActivity,
    BotConfig,
    BotRunState,
    RewardSelection,
)
from stream_controller.plugins.bot_manager.discord_bot_client import DiscordBotClient
from stream_controller.plugins.bot_manager.twitch_bot_client import TwitchBotClient
from stream_controller.plugins.bot_manager.twitch_eventsub_client import TwitchEventSubClient

logger = logging.getLogger(__name__)

_TWITCH_STREAMS_API = "https://api.twitch.tv/helix/streams"
_ACTIVE_CHAT_WINDOW = 600.0  # seconds (10 min)
_MAX_ACTIVITY = 50
_MAX_RESPONSE_LEN = 500
_UPTIME_CACHE_TTL = 15.0  # seconds


class _Signals(QObject):
    state_updated = Signal()


class BotEngine:
    """
    Orchestrates one bot instance. Owns TwitchBotClient and DiscordBotClient,
    handles command dispatch, timed messages, event responses, and activity logging.
    Uses Qt signals for thread-safe UI notification.
    """

    def __init__(self, bot_config: BotConfig, db: BotDatabase,
                 on_alert: Callable[[str, str, dict], None] | None = None) -> None:
        self._config = bot_config
        self._db = db
        self._on_alert_cb = on_alert
        self._state = BotRunState(bot_id=bot_config.bot_id)
        self._signals = _Signals()
        self._subscribers: list[Callable[[BotRunState], None]] = []
        self._uptime_cache: tuple[float, str] = (0.0, "")  # (fetched_ts, value)
        # username → (BotCommand, source, reward_name) for pending list selections
        self._pending_selections: dict[str, tuple] = {}

        self._twitch_client = TwitchBotClient(
            on_command=self._on_twitch_command,
            on_event=self._on_twitch_event,
            on_status=self._on_twitch_status,
            on_message_seen=self._on_message_seen,
            on_chat_message=self._on_chat_message,
        )
        self._discord_client = DiscordBotClient(
            on_message=self._on_discord_message,
            on_command=self._on_discord_command,
            on_status=self._on_discord_status,
        )
        self._eventsub_client = TwitchEventSubClient(
            on_redemption=self._on_channel_point_redemption,
            on_status=self._on_eventsub_status,
            on_event=self._on_eventsub_event,
        )
        self._signals.state_updated.connect(self._notify_subscribers, Qt.QueuedConnection)

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            return
        self._log_activity("system", f"Bot '{self._config.name}' starting…")
        self._twitch_client.connect(
            channel=self._config.twitch_channel,
            username=self._config.twitch_bot_username,
            oauth_token=self._config.twitch_oauth_token,
        )
        if self._config.discord_enabled and self._config.discord_bot_token:
            self._discord_client.connect(self._config.discord_bot_token)
        if self._config.twitch_broadcaster_token:
            self._eventsub_client.connect(
                channel=self._config.twitch_channel,
                broadcaster_token=self._config.twitch_broadcaster_token,
                client_id=self._config.twitch_client_id,
            )
        else:
            self._log_activity("system", "EventSub inactive — no broadcaster token. Use Twitch Setup → Step 4 to enable channel points tracking.")

    def stop(self) -> None:
        self._log_activity("system", f"Bot '{self._config.name}' stopping…")
        self._twitch_client.disconnect()
        self._discord_client.disconnect()
        self._eventsub_client.disconnect()
        self._state.twitch_connected = False
        self._state.discord_connected = False
        self._emit_state()

    def subscribe(self, cb: Callable[[BotRunState], None]) -> None:
        if cb not in self._subscribers:
            self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    @property
    def state(self) -> BotRunState:
        return self._state

    def tick(self) -> None:
        """Called by the plugin's QTimer (every 30 seconds) on the main thread."""
        now = time.time()
        timed_msgs = self._db.list_timed_messages()
        for tmsg in timed_msgs:
            if not tmsg.enabled:
                continue
            interval_secs = tmsg.interval_minutes * 60
            if interval_secs <= 0:
                continue
            if (now - tmsg.last_sent_ts) < interval_secs:
                continue
            if tmsg.only_when_active:
                if (now - self._state.last_chat_ts) > _ACTIVE_CHAT_WINDOW:
                    continue
            self.send_chat_message(tmsg.message)
            self._db.update_timed_last_sent(tmsg.msg_id, now)
            self._log_activity("timed", f"Timed message sent: {tmsg.message[:60]}")

    def send_chat_message(self, text: str) -> None:
        if self._twitch_client.is_connected:
            self._twitch_client.send_chat(self._config.twitch_channel, text)
            self._state.messages_sent += 1
            self._emit_state()

    def send_discord_message(self, text: str) -> None:
        if self._discord_client.is_connected and self._config.discord_announce_channel_id:
            self._discord_client.send_message(self._config.discord_announce_channel_id, text)
            self._state.messages_sent += 1
            self._emit_state()

    def update_config(self, new_config: BotConfig) -> None:
        was_running = self._twitch_client.is_connected
        if was_running:
            self.stop()
        self._config = new_config
        if was_running and new_config.enabled:
            self.start()

    def reload_commands(self) -> None:
        pass  # Commands are loaded fresh from DB on each dispatch; no cache to invalidate.

    # ── callbacks from Twitch client (background thread) ──────────────────────

    def _on_twitch_command(self, trigger: str, username: str, tags: dict) -> None:
        commands = self._db.list_commands()
        cmd = next((c for c in commands if c.trigger == trigger and c.enabled), None)
        if cmd is None:
            return

        now = time.time()
        last_used = self._db.get_command_last_used(trigger)
        if now - last_used < cmd.cooldown_seconds:
            return

        self._db.record_command_use(trigger)
        use_count = self._get_command_use_count(trigger)

        if cmd.command_type == "list" and cmd.list_items:
            self._post_list_to_chat(cmd, username)
            self._state.commands_handled += 1
            self._log_activity("command", f"{username}: {trigger} → [list: {cmd.list_title or trigger}]")
        else:
            response = self._format_response(
                cmd.response,
                user=username,
                tags=tags,
                trigger=trigger,
                use_count=use_count,
            )
            self.send_chat_message(response)
            self._state.commands_handled += 1
            self._log_activity("command", f"{username}: {trigger} → {response[:60]}")

        try:
            self._db.upsert_user_stat(username, tags.get("user-id", ""), message_delta=1)
        except Exception as exc:
            logger.debug("user stat update error: %s", exc)

    def _on_twitch_event(self, event_type: str, username: str, tags: dict) -> None:
        responses = self._db.list_event_responses()
        for resp in responses:
            if not resp.enabled or resp.event_type != event_type:
                continue
            if event_type in ("bits", "cheer"):
                bits_str = tags.get("bits", "0")
                bits = int(bits_str) if bits_str.isdigit() else 0
                if bits < resp.min_bits:
                    continue
            text = self._format_response(resp.response_template, user=username, tags=tags)
            self.send_chat_message(text)
            msg_preview = tags.get("message", "")
            log_suffix = f" — \"{msg_preview[:60]}\"" if msg_preview else ""
            self._log_activity("event", f"{event_type} from {username}: {text[:60]}{log_suffix}")
            break  # Only first matching response per event

        # Update user stats and log the event
        amount = 0
        try:
            if event_type in ("bits", "cheer"):
                bits_str = tags.get("bits", "0")
                amount = int(bits_str) if bits_str.isdigit() else 0
                self._db.upsert_user_stat(username, tags.get("user-id", ""), bits_delta=amount)
            elif event_type in ("sub", "resub"):
                amount = int(tags.get("msg-param-cumulative-months", 1))
                self._db.upsert_user_stat(username, tags.get("user-id", ""), subs_delta=1)
            elif event_type == "subgift":
                amount = int(tags.get("msg-param-sender-count", 1))
                self._db.upsert_user_stat(username, tags.get("user-id", ""), gifted_subs_delta=amount)
            elif event_type == "raid":
                amount = int(tags.get("msg-param-viewerCount", 0))
            self._db.log_event(event_type, username, tags.get("user-id", ""), amount=amount)
        except Exception as exc:
            logger.debug("event logging error: %s", exc)

        # Check for bits-linked list commands
        if event_type in ("bits", "cheer"):
            bits_str = tags.get("bits", "0")
            bits_count = int(bits_str) if bits_str.isdigit() else 0
            if bits_count > 0:
                self._check_bits_list_trigger(username, bits_count, tags)

        message_text = tags.get("message", "")
        ctx: dict = {"amount": amount}
        if message_text:
            ctx["input"] = message_text
        self._route_to_discord(event_type, username, ctx)

    def _on_twitch_status(self, status: str, msg: str) -> None:
        self._state.twitch_connected = (status == "connected")
        self._state.status_message = msg or status
        self._log_activity("system", f"Twitch: {status}{' — ' + msg if msg else ''}")
        self._emit_state()

    def _on_message_seen(self) -> None:
        self._state.last_chat_ts = time.time()

    # ── callbacks from Discord client (background thread) ─────────────────────

    def _on_discord_message(self, channel_id: str, username: str, content: str) -> None:
        pass  # No special handling beyond command detection

    def _on_discord_command(self, trigger: str, username: str, channel_id: str) -> None:
        commands = self._db.list_commands()
        cmd = next((c for c in commands if c.trigger == trigger and c.enabled), None)
        if cmd is None:
            return

        last_used = self._db.get_command_last_used(trigger)
        if time.time() - last_used < cmd.cooldown_seconds:
            return

        self._db.record_command_use(trigger)
        use_count = self._get_command_use_count(trigger)
        response = self._format_response(cmd.response, user=username, tags={}, use_count=use_count)
        self._discord_client.send_message(channel_id, response)
        self._state.commands_handled += 1
        self._state.messages_sent += 1
        self._log_activity("command", f"[Discord] {username}: {trigger} → {response[:60]}")

    def _on_discord_status(self, status: str, msg: str) -> None:
        self._state.discord_connected = (status == "connected")
        self._state.status_message = msg or status
        self._log_activity("system", f"Discord: {status}{' — ' + msg if msg else ''}")
        self._emit_state()

    def _on_channel_point_redemption(
        self, username: str, user_id: str, reward_name: str, cost: int, input_text: str
    ) -> None:
        try:
            self._db.upsert_user_stat(username, user_id, channel_points_delta=cost)
            self._db.log_event(
                "channel_points", username, user_id,
                amount=cost,
                extra=json.dumps({"reward": reward_name, "input": input_text}),
            )
        except Exception as exc:
            logger.debug("channel points log error: %s", exc)
        activity_text = f"Channel Points: {username} redeemed '{reward_name}' ({cost:,} pts)"
        if input_text:
            activity_text += f" — \"{input_text}\""
        self._log_activity("event", activity_text)
        extra = {"reward": reward_name, "cost": cost, "amount": cost, "input": input_text}

        # Check for channel-point-linked list commands
        self._check_reward_list_trigger(username, user_id, reward_name, cost)

        # Fire any enabled channel_points event responses to Twitch chat
        tags = {"reward": reward_name, "cost": str(cost), "input": input_text or ""}
        for resp in self._db.list_event_responses():
            if resp.enabled and resp.event_type == "channel_points":
                text = self._format_response(resp.response_template, user=username, tags=tags)
                self.send_chat_message(text)
                break

        self._route_to_discord("channel_points", username, extra)
        if self._on_alert_cb is not None:
            try:
                self._on_alert_cb("channel_points", username, extra)
            except Exception as exc:
                logger.debug("on_alert_cb error: %s", exc)

    def _on_eventsub_status(self, status: str, msg: str) -> None:
        self._log_activity("system", f"EventSub: {status}{' — ' + msg if msg else ''}")

    def _on_eventsub_event(self, event_type: str, username: str, user_id: str, extra: dict) -> None:
        try:
            self._db.log_event(event_type, username, user_id)
        except Exception as exc:
            logger.debug("eventsub event log error: %s", exc)
        self._log_activity("event", f"{event_type}: {username}")
        self._route_to_discord(event_type, username, extra)
        if self._on_alert_cb is not None:
            try:
                self._on_alert_cb(event_type, username, extra)
            except Exception as exc:
                logger.debug("on_alert_cb error: %s", exc)

    def _post_list_to_chat(self, cmd, username: str = "") -> None:
        title = cmd.list_title or cmd.trigger
        items_str = " | ".join(f"{i+1}. {item}" for i, item in enumerate(cmd.list_items))
        msg = f"{title}: {items_str}"
        if username:
            msg = f"@{username} — {msg}"
        self.send_chat_message(msg[:500])

    def _check_reward_list_trigger(
        self, username: str, user_id: str, reward_name: str, cost: int
    ) -> None:
        name_lower = reward_name.strip().lower()
        commands = self._db.list_commands()
        for cmd in commands:
            if cmd.command_type != "list" or not cmd.list_items:
                continue
            if not cmd.linked_reward:
                continue
            if cmd.linked_reward.strip().lower() == name_lower:
                self._post_list_to_chat(cmd, username)
                self._pending_selections[username.lower()] = (cmd, "channel_points", reward_name)
                self._log_activity(
                    "event",
                    f"List shown to {username} for reward '{reward_name}' ({cmd.trigger}) — awaiting selection",
                )
                break

    def _check_bits_list_trigger(self, username: str, bits: int, tags: dict) -> None:
        commands = self._db.list_commands()
        for cmd in commands:
            if cmd.command_type != "list" or not cmd.list_items:
                continue
            if cmd.linked_bits <= 0 or bits < cmd.linked_bits:
                continue
            self._post_list_to_chat(cmd, username)
            self._pending_selections[username.lower()] = (cmd, "bits", f"{bits} bits")
            self._log_activity(
                "event",
                f"List shown to {username} for {bits} bits ({cmd.trigger}) — awaiting selection",
            )
            break

    def _on_chat_message(self, username: str, text: str, tags: dict) -> None:
        """Called for every PRIVMSG. Captures selection if user has a pending list."""
        key = username.lower()
        pending = self._pending_selections.get(key)
        if pending is None:
            return
        if text.startswith("!"):
            return  # ignore commands — wait for plain text

        cmd, source, reward_name = pending
        sel = RewardSelection(
            selection_id=uuid.uuid4().hex,
            bot_id=self._config.bot_id,
            username=username,
            user_id=tags.get("user-id", ""),
            source=source,
            reward_name=reward_name,
            command_trigger=cmd.trigger,
            selection=text.strip()[:200],
            ts=time.time(),
            status="pending",
        )
        try:
            self._db.save_selection(sel)
        except Exception as exc:
            logger.warning("save_selection error: %s", exc)
        del self._pending_selections[key]
        self._log_activity(
            "event",
            f"{username} selected '{sel.selection[:60]}' for {reward_name}",
        )
        self.send_chat_message(
            f"@{username} — Got it! Your selection '{sel.selection[:60]}' has been recorded. ✅"
        )

    def _route_to_discord(self, event_type: str, username: str, ctx: dict) -> None:
        try:
            routes = self._db.list_discord_routes()
        except Exception:
            return
        _defaults = {
            "sub":            "{user} just subscribed! 🎉",
            "resub":          "{user} resubscribed for {amount} months! 🔄",
            "subgift":        "{user} gifted {amount} sub(s)! 🎁",
            "raid":           "{user} raided with {amount} viewers! ⚔️",
            "bits":           "{user} just cheered {amount} bits! 💎 {input}",
            "channel_points": "{user} redeemed '{reward}' for {cost} points! 🏆 {input}",
            "follow":         "{user} just followed! ❤️",
        }
        for route in routes:
            if not route.enabled:
                continue
            if route.event_type not in (event_type, "all"):
                continue
            if not route.channel_id:
                logger.debug("discord route for %s has no channel_id — skipping", event_type)
                continue
            try:
                template = route.message_template.strip() or _defaults.get(event_type, "{user}: {amount}")
                msg = self._format_response(template, user=username, tags=ctx)
                if not msg.strip():
                    continue
                logger.info("Discord route: %s → channel %s: %r", event_type, route.channel_id, msg[:80])
                self._discord_client.send_message(route.channel_id, msg)
            except Exception as exc:
                logger.warning("discord route error: %s", exc)

    # ── variable substitution ─────────────────────────────────────────────────

    def _format_response(
        self,
        template: str,
        user: str = "",
        tags: dict | None = None,
        trigger: str = "",
        use_count: int = 0,
    ) -> str:
        tags = tags or {}
        result = template

        result = result.replace("{user}", user)
        result = result.replace("{channel}", self._config.twitch_channel)
        result = result.replace("{count}", str(use_count))

        if "{uptime}" in result:
            result = result.replace("{uptime}", self._get_uptime())

        if "{commands}" in result:
            enabled_triggers = [
                c.trigger for c in self._db.list_commands() if c.enabled
            ]
            result = result.replace("{commands}", ", ".join(sorted(enabled_triggers)))

        # Event-specific variables
        viewers = tags.get("msg-param-viewerCount", "?")
        result = result.replace("{viewers}", str(viewers))

        months = tags.get("msg-param-cumulative-months", tags.get("msg-param-months", "1"))
        result = result.replace("{months}", str(months))

        bits = tags.get("bits", "0")
        result = result.replace("{amount}", str(bits))

        reward = tags.get("reward", "")
        result = result.replace("{reward}", str(reward))
        cost = tags.get("cost", "")
        result = result.replace("{cost}", str(cost))
        input_val = tags.get("input", "")
        result = result.replace("{input}", str(input_val))

        # Config-sourced variables (stored in bot settings via dedicated keys)
        result = result.replace("{discord_url}", self._config.discord_url or "(no Discord URL set)")
        result = result.replace("{merch_url}", self._config.merch_url or "(no merch URL set)")
        result = result.replace("{socials}", self._config.socials or "(no socials set)")

        return result[:_MAX_RESPONSE_LEN]

    def _get_uptime(self) -> str:
        fetched_ts, cached_val = self._uptime_cache
        if time.time() - fetched_ts < _UPTIME_CACHE_TTL:
            return cached_val
        val = self._fetch_uptime()
        self._uptime_cache = (time.time(), val)
        return val

    def _fetch_uptime(self) -> str:
        token = self._config.twitch_oauth_token
        client_id = self._config.twitch_client_id
        channel = self._config.twitch_channel
        if not token or not client_id or not channel:
            return "unknown"

        tok = token if token.startswith("oauth:") else f"oauth:{token}"
        bearer = tok.replace("oauth:", "")
        url = f"{_TWITCH_STREAMS_API}?user_login={channel}"
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Client-Id": client_id,
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ssl_ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                data = body.get("data", [])
                if not data:
                    return "offline"
                started_at_str = data[0].get("started_at", "")
                if not started_at_str:
                    return "unknown"

                from datetime import datetime, timezone
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = int((now - started_at).total_seconds())
                hours, remainder = divmod(elapsed, 3600)
                minutes = remainder // 60
                if hours > 0:
                    return f"{hours}h {minutes}m"
                return f"{minutes}m"
        except Exception as exc:
            logger.debug("uptime fetch failed: %s", exc)
            return "unknown"

    def _get_command_use_count(self, trigger: str) -> int:
        row = self._db._conn.execute(
            "SELECT use_count FROM command_stats WHERE trigger = ?", (trigger,)
        ).fetchone()
        return int(row["use_count"]) if row else 0

    # ── activity log ──────────────────────────────────────────────────────────

    def _log_activity(self, kind: str, text: str) -> None:
        entry = BotActivity(ts=time.time(), bot_id=self._config.bot_id, kind=kind, text=text)
        self._state.activity.append(entry)
        if len(self._state.activity) > _MAX_ACTIVITY:
            self._state.activity = self._state.activity[-_MAX_ACTIVITY:]
        self._emit_state()

    # ── Qt signal helpers ─────────────────────────────────────────────────────

    def _emit_state(self) -> None:
        """Thread-safe: emit signal so Qt delivers it on the main thread."""
        self._signals.state_updated.emit()

    def _notify_subscribers(self) -> None:
        """Runs on the main thread via QueuedConnection."""
        for cb in list(self._subscribers):
            try:
                cb(self._state)
            except Exception as exc:
                logger.warning("Bot subscriber error: %s", exc)
