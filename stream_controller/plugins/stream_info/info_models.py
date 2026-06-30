from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"


class StreamStatus(Enum):
    OFFLINE  = "offline"
    STARTING = "starting"
    LIVE     = "live"
    STOPPING = "stopping"


@dataclass
class StreamInfo:
    title:          str = ""
    category_name:  str = ""
    category_id:    str = ""
    tags:           list[str] = field(default_factory=list)
    language:       str = "en"

    def to_dict(self) -> dict:
        return {
            "title":         self.title,
            "category_name": self.category_name,
            "category_id":   self.category_id,
            "tags":          self.tags,
            "language":      self.language,
        }


@dataclass
class InfoState:
    twitch_status:  ConnectionStatus = ConnectionStatus.DISCONNECTED
    stream_status:  StreamStatus     = StreamStatus.OFFLINE
    info:           StreamInfo       = field(default_factory=StreamInfo)
    pending_update: bool             = False
    error:          str              = ""
    broadcaster_id: str              = ""
    username:       str              = ""
