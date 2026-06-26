from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MsgType(Enum):
    CHAT           = "chat"
    BITS           = "bits"
    CHANNEL_POINTS = "channel_points"
    SUB            = "sub"
    RESUB          = "resub"
    SUBGIFT        = "subgift"
    SUBMYSTERYGIFT = "submysterygift"
    RAID           = "raid"
    RITUAL         = "ritual"
    ANNOUNCEMENT   = "announcement"


# Human-readable label + icon for each event type
MSG_TYPE_META: dict[MsgType, tuple[str, str]] = {
    MsgType.CHAT:           ("Chat",          ""),
    MsgType.BITS:           ("Bits",          "💎"),
    MsgType.CHANNEL_POINTS: ("Channel Points","⭐"),
    MsgType.SUB:            ("New Sub",       "🎉"),
    MsgType.RESUB:          ("Resub",         "🔄"),
    MsgType.SUBGIFT:        ("Gift Sub",      "🎁"),
    MsgType.SUBMYSTERYGIFT: ("Mystery Gifts", "🎁"),
    MsgType.RAID:           ("Raid",          "⚔"),
    MsgType.RITUAL:         ("New Chatter",   "👋"),
    MsgType.ANNOUNCEMENT:   ("Announcement",  "📢"),
}


@dataclass
class ChatMessage:
    msg_id: str
    ts: datetime
    username: str
    display_name: str
    color: str          # "#RRGGBB" or ""
    badges: list[str]
    text: str           # chat text OR decoded system-msg for events
    channel: str
    msg_type: MsgType = MsgType.CHAT
    bits: int = 0
    system_text: str = ""   # original system-msg for events (display alongside user text)
    is_mod: bool = False
    is_sub: bool = False
    is_broadcaster: bool = False
    deleted: bool = False
    highlighted: bool = False

    @property
    def safe_color(self) -> str:
        return self.color if self.color else "#9b9b9b"

    @property
    def is_event(self) -> bool:
        return self.msg_type != MsgType.CHAT

    @property
    def event_icon(self) -> str:
        return MSG_TYPE_META.get(self.msg_type, ("", ""))[1]

    @property
    def event_label(self) -> str:
        return MSG_TYPE_META.get(self.msg_type, ("Chat", ""))[0]

    @property
    def badge_labels(self) -> list[str]:
        labels = []
        for b in self.badges:
            name = b.split("/")[0]
            if name == "broadcaster":
                labels.append("🎙")
            elif name == "moderator":
                labels.append("⚔")
            elif name == "subscriber":
                labels.append("★")
            elif name == "vip":
                labels.append("💎")
        return labels

    def to_dict(self) -> dict:
        return {
            "id": self.msg_id,
            "ts": self.ts.isoformat(),
            "username": self.username,
            "display_name": self.display_name,
            "color": self.safe_color,
            "badges": self.badge_labels,
            "text": self.text,
            "msg_type": self.msg_type.value,
            "event_icon": self.event_icon,
            "event_label": self.event_label,
            "bits": self.bits,
            "system_text": self.system_text,
            "is_mod": self.is_mod,
            "is_sub": self.is_sub,
            "is_broadcaster": self.is_broadcaster,
            "deleted": self.deleted,
            "highlighted": self.highlighted,
        }


@dataclass
class ChatState:
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    channel: str = ""
    error_message: str = ""
    viewer_count: int = 0
    slow_mode: int = 0
    sub_only: bool = False
    emote_only: bool = False
    follower_only: int = -1


def decode_system_msg(raw: str) -> str:
    """Twitch encodes spaces as \\s in system-msg tag values."""
    return raw.replace("\\s", " ").replace("\\n", "\n").replace("\\:", ":")
