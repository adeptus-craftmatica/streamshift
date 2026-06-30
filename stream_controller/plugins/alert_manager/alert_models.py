from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AlertType(str, Enum):
    FOLLOWER   = "follower"
    SUBSCRIBER = "subscriber"
    GIFT_SUB   = "gift_sub"
    BITS       = "bits"
    RAID       = "raid"
    DONATION   = "donation"


@dataclass
class AlertConfig:
    alert_type: AlertType
    enabled: bool = True
    message_template: str = ""
    duration_ms: int = 5000
    sound_file: str = ""
    overlay_style: str = "card"

    def default_template(self) -> str:
        defaults = {
            AlertType.FOLLOWER:   "{name} just followed!",
            AlertType.SUBSCRIBER: "{name} subscribed! ({tier})",
            AlertType.GIFT_SUB:   "{name} gifted {count} subs!",
            AlertType.BITS:       "{name} cheered {amount} bits!",
            AlertType.RAID:       "{name} raided with {count} viewers!",
            AlertType.DONATION:   "{name} donated ${amount}!",
        }
        return defaults[self.alert_type]

    def resolved_template(self) -> str:
        return self.message_template if self.message_template else self.default_template()


@dataclass
class AlertEvent:
    alert_type: AlertType
    name: str = "Someone"
    tier: str = "Tier 1"
    count: int = 1
    amount: float = 0.0
    message: str = ""
    is_test: bool = False
