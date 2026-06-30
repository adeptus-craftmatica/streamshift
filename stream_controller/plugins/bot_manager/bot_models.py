from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotConfig:
    bot_id: str
    name: str
    icon: str
    enabled: bool
    twitch_channel: str
    twitch_bot_username: str
    twitch_oauth_token: str
    twitch_client_id: str
    discord_bot_token: str
    discord_guild_id: str
    discord_announce_channel_id: str
    discord_enabled: bool
    created_at: str
    discord_client_id: str = ""
    discord_url: str = ""
    merch_url: str = ""
    socials: str = ""
    twitch_broadcaster_token: str = ""

    def to_dict(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "name": self.name,
            "icon": self.icon,
            "enabled": self.enabled,
            "twitch_channel": self.twitch_channel,
            "twitch_bot_username": self.twitch_bot_username,
            "twitch_oauth_token": self.twitch_oauth_token,
            "twitch_client_id": self.twitch_client_id,
            "discord_bot_token": self.discord_bot_token,
            "discord_guild_id": self.discord_guild_id,
            "discord_announce_channel_id": self.discord_announce_channel_id,
            "discord_enabled": self.discord_enabled,
            "created_at": self.created_at,
            "discord_client_id": self.discord_client_id,
            "discord_url": self.discord_url,
            "merch_url": self.merch_url,
            "socials": self.socials,
            "twitch_broadcaster_token": self.twitch_broadcaster_token,
        }

    @staticmethod
    def from_dict(d: dict) -> "BotConfig":
        return BotConfig(
            bot_id=d.get("bot_id", ""),
            name=d.get("name", ""),
            icon=d.get("icon", "🤖"),
            enabled=d.get("enabled", False),
            twitch_channel=d.get("twitch_channel", ""),
            twitch_bot_username=d.get("twitch_bot_username", ""),
            twitch_oauth_token=d.get("twitch_oauth_token", ""),
            twitch_client_id=d.get("twitch_client_id", ""),
            discord_bot_token=d.get("discord_bot_token", ""),
            discord_guild_id=d.get("discord_guild_id", ""),
            discord_announce_channel_id=d.get("discord_announce_channel_id", ""),
            discord_enabled=d.get("discord_enabled", False),
            created_at=d.get("created_at", ""),
            discord_client_id=d.get("discord_client_id", ""),
            discord_url=d.get("discord_url", ""),
            merch_url=d.get("merch_url", ""),
            socials=d.get("socials", ""),
            twitch_broadcaster_token=d.get("twitch_broadcaster_token", ""),
        )


@dataclass
class BotCommand:
    command_id: str
    bot_id: str
    trigger: str
    response: str
    cooldown_seconds: int
    enabled: bool
    is_builtin: bool
    command_type: str = "text"        # "text" or "list"
    list_title: str = ""
    list_items: list = field(default_factory=list)
    linked_reward: str = ""           # channel-point reward name that triggers showing this list
    linked_bits: int = 0              # bits threshold that triggers showing this list

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "bot_id": self.bot_id,
            "trigger": self.trigger,
            "response": self.response,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "is_builtin": self.is_builtin,
            "command_type": self.command_type,
            "list_title": self.list_title,
            "list_items": self.list_items,
            "linked_reward": self.linked_reward,
            "linked_bits": self.linked_bits,
        }

    @staticmethod
    def from_dict(d: dict) -> "BotCommand":
        return BotCommand(
            command_id=d.get("command_id", uuid.uuid4().hex),
            bot_id=d.get("bot_id", ""),
            trigger=d.get("trigger", ""),
            response=d.get("response", ""),
            cooldown_seconds=d.get("cooldown_seconds", 5),
            enabled=d.get("enabled", True),
            is_builtin=d.get("is_builtin", False),
            command_type=d.get("command_type", "text"),
            list_title=d.get("list_title", ""),
            list_items=d.get("list_items", []),
            linked_reward=d.get("linked_reward", ""),
            linked_bits=d.get("linked_bits", 0),
        )


@dataclass
class RewardSelection:
    """A viewer's selection after being shown a list (via bits or channel points)."""
    selection_id: str
    bot_id: str
    username: str
    user_id: str
    source: str           # "bits" or "channel_points"
    reward_name: str      # the reward/trigger that was matched
    command_trigger: str  # the !command whose list was shown
    selection: str        # what the viewer typed
    ts: float
    status: str = "pending"  # "pending" or "confirmed"

    def to_dict(self) -> dict:
        return {
            "selection_id": self.selection_id,
            "bot_id": self.bot_id,
            "username": self.username,
            "user_id": self.user_id,
            "source": self.source,
            "reward_name": self.reward_name,
            "command_trigger": self.command_trigger,
            "selection": self.selection,
            "ts": self.ts,
            "status": self.status,
        }

    @staticmethod
    def from_dict(d: dict) -> "RewardSelection":
        return RewardSelection(
            selection_id=d.get("selection_id", uuid.uuid4().hex),
            bot_id=d.get("bot_id", ""),
            username=d.get("username", ""),
            user_id=d.get("user_id", ""),
            source=d.get("source", ""),
            reward_name=d.get("reward_name", ""),
            command_trigger=d.get("command_trigger", ""),
            selection=d.get("selection", ""),
            ts=d.get("ts", 0.0),
            status=d.get("status", "pending"),
        )


@dataclass
class TimedMessage:
    msg_id: str
    bot_id: str
    message: str
    interval_minutes: int
    enabled: bool
    only_when_active: bool
    last_sent_ts: float

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "bot_id": self.bot_id,
            "message": self.message,
            "interval_minutes": self.interval_minutes,
            "enabled": self.enabled,
            "only_when_active": self.only_when_active,
            "last_sent_ts": self.last_sent_ts,
        }

    @staticmethod
    def from_dict(d: dict) -> "TimedMessage":
        return TimedMessage(
            msg_id=d.get("msg_id", uuid.uuid4().hex),
            bot_id=d.get("bot_id", ""),
            message=d.get("message", ""),
            interval_minutes=d.get("interval_minutes", 30),
            enabled=d.get("enabled", True),
            only_when_active=d.get("only_when_active", True),
            last_sent_ts=d.get("last_sent_ts", 0.0),
        )


@dataclass
class EventResponse:
    resp_id: str
    bot_id: str
    event_type: str
    response_template: str
    enabled: bool
    min_bits: int

    def to_dict(self) -> dict:
        return {
            "resp_id": self.resp_id,
            "bot_id": self.bot_id,
            "event_type": self.event_type,
            "response_template": self.response_template,
            "enabled": self.enabled,
            "min_bits": self.min_bits,
        }

    @staticmethod
    def from_dict(d: dict) -> "EventResponse":
        return EventResponse(
            resp_id=d.get("resp_id", uuid.uuid4().hex),
            bot_id=d.get("bot_id", ""),
            event_type=d.get("event_type", ""),
            response_template=d.get("response_template", ""),
            enabled=d.get("enabled", True),
            min_bits=d.get("min_bits", 0),
        )


@dataclass
class BotActivity:
    """Recent activity log entry."""
    ts: float
    bot_id: str
    kind: str   # "command", "timed", "event", "system"
    text: str


@dataclass
class BotRunState:
    """Runtime state of a bot (not persisted)."""
    bot_id: str = ""
    twitch_connected: bool = False
    discord_connected: bool = False
    messages_sent: int = 0
    commands_handled: int = 0
    last_chat_ts: float = 0.0
    status_message: str = ""   # last human-readable status / error
    activity: list = field(default_factory=list)  # list[BotActivity], max 50


@dataclass
class UserStat:
    """Per-user lifetime stats tracked across all streams."""
    user_id: str
    username: str
    bits_total: int = 0
    subs_total: int = 0
    gifted_subs_total: int = 0
    channel_points_total: int = 0
    messages_total: int = 0
    first_seen_ts: float = 0.0
    last_seen_ts: float = 0.0


@dataclass
class EventLog:
    """Immutable record of a viewer event (sub, bits, raid, channel points, etc.)."""
    event_id: str
    event_type: str      # 'sub' 'resub' 'subgift' 'raid' 'bits' 'channel_points' 'follow'
    username: str
    user_id: str = ""
    amount: int = 0      # bits amount, months, viewer count, point cost
    extra: str = ""      # JSON string for reward name, input text, etc.
    ts: float = 0.0
    stream_date: str = ""  # YYYY-MM-DD


@dataclass
class DiscordRoute:
    """Trigger a Discord message when a Twitch event fires."""
    route_id: str
    event_type: str      # same values as EventLog.event_type, or 'all'
    channel_id: str = ""
    message_template: str = ""
    enabled: bool = True


# ---------------------------------------------------------------------------
# Default built-in commands (bot_id="" — filled in when creating a bot)
# ---------------------------------------------------------------------------

DEFAULT_COMMANDS: list[BotCommand] = [
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!commands",
        response="Available commands: {commands}",
        cooldown_seconds=10,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!list",
        response="Available commands: {commands}",
        cooldown_seconds=10,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!uptime",
        response="Stream has been live for {uptime}.",
        cooldown_seconds=30,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!discord",
        response="Join our Discord: {discord_url}",
        cooldown_seconds=10,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!merch",
        response="Check out our merch: {merch_url}",
        cooldown_seconds=10,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!socials",
        response="Follow us: {socials}",
        cooldown_seconds=10,
        enabled=True,
        is_builtin=True,
    ),
    BotCommand(
        command_id=uuid.uuid4().hex,
        bot_id="",
        trigger="!lurk",
        response="Thanks for lurking, {user}! See you around 👀",
        cooldown_seconds=5,
        enabled=True,
        is_builtin=True,
    ),
]
