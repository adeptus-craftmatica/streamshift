from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"


@dataclass
class LiveStats:
    followers_gained: int = 0
    total_followers:  int = 0
    bits_donated:     int = 0
    new_subs:         int = 0
    gifted_subs:      int = 0
    latest_follower:  str = ""
    session_active:   bool = False
    status:           ConnectionStatus = ConnectionStatus.DISCONNECTED
    error:            str = ""

    def to_dict(self) -> dict:
        return {
            "followers_gained": self.followers_gained,
            "total_followers":  self.total_followers,
            "bits_donated":     self.bits_donated,
            "new_subs":         self.new_subs,
            "gifted_subs":      self.gifted_subs,
            "latest_follower":  self.latest_follower,
            "session_active":   self.session_active,
            "status":           self.status.value,
            "error":            self.error,
        }


@dataclass
class SessionRecord:
    session_id:       str
    started_at:       str
    ended_at:         str
    stream_title:     str = ""
    followers_gained: int = 0
    total_followers:  int = 0
    bits_donated:     int = 0
    new_subs:         int = 0
    gifted_subs:      int = 0
    latest_follower:  str = ""

    def to_dict(self) -> dict:
        return {
            "session_id":       self.session_id,
            "started_at":       self.started_at,
            "ended_at":         self.ended_at,
            "stream_title":     self.stream_title,
            "followers_gained": self.followers_gained,
            "total_followers":  self.total_followers,
            "bits_donated":     self.bits_donated,
            "new_subs":         self.new_subs,
            "gifted_subs":      self.gifted_subs,
            "latest_follower":  self.latest_follower,
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionRecord":
        return SessionRecord(
            session_id=d.get("session_id", ""),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            stream_title=d.get("stream_title", ""),
            followers_gained=int(d.get("followers_gained", 0)),
            total_followers=int(d.get("total_followers", 0)),
            bits_donated=int(d.get("bits_donated", 0)),
            new_subs=int(d.get("new_subs", 0)),
            gifted_subs=int(d.get("gifted_subs", 0)),
            latest_follower=d.get("latest_follower", ""),
        )
