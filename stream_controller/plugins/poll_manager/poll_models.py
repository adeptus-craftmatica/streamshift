from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"


class PollStatus(Enum):
    ACTIVE     = "ACTIVE"
    COMPLETED  = "COMPLETED"
    TERMINATED = "TERMINATED"
    ARCHIVED   = "ARCHIVED"
    MODERATED  = "MODERATED"


@dataclass
class PollChoice:
    choice_id: str
    title: str
    votes: int = 0
    channel_points_votes: int = 0
    bits_votes: int = 0

    @property
    def total_votes(self) -> int:
        return self.votes + self.channel_points_votes + self.bits_votes


@dataclass
class Poll:
    poll_id: str
    title: str
    choices: list[PollChoice]
    status: PollStatus
    duration: int
    started_at: str
    ended_at: Optional[str] = None

    @property
    def total_votes(self) -> int:
        return sum(c.total_votes for c in self.choices)

    @property
    def seconds_remaining(self) -> int:
        if self.status != PollStatus.ACTIVE:
            return 0
        try:
            start = datetime.datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
            return max(0, int(self.duration - elapsed))
        except Exception:
            return 0

    @property
    def winner(self) -> Optional[PollChoice]:
        if not self.choices:
            return None
        return max(self.choices, key=lambda c: c.total_votes)

    @classmethod
    def from_api(cls, data: dict) -> "Poll":
        choices = [
            PollChoice(
                choice_id=c["id"],
                title=c["title"],
                votes=c.get("votes", 0),
                channel_points_votes=c.get("channel_points_votes", 0),
                bits_votes=c.get("bits_votes", 0),
            )
            for c in data.get("choices", [])
        ]
        return cls(
            poll_id=data["id"],
            title=data["title"],
            choices=choices,
            status=PollStatus(data["status"]),
            duration=data["duration"],
            started_at=data["started_at"],
            ended_at=data.get("ended_at"),
        )


@dataclass
class PollTemplate:
    template_id: str
    name: str
    title: str
    choices: list[str]
    duration: int  # seconds


@dataclass
class PollState:
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    connection_error: str = ""
    active_poll: Optional[Poll] = None
    recent_polls: list[Poll] = field(default_factory=list)
