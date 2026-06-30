from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class ItemKind(str, Enum):
    REDEMPTION = "redemption"
    BITS       = "bits"


class ItemStatus(str, Enum):
    PENDING   = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class QueueItem:
    item_id:      str
    kind:         ItemKind
    viewer_name:  str
    reward_name:  str        # reward title for redemptions; "Bits Cheer" for bits
    user_input:   str        # viewer's text input (may be empty)
    amount:       int        # cost in points, or bits amount
    status:       ItemStatus = ItemStatus.PENDING
    timestamp:    str        = ""

    # Twitch IDs needed to call the fulfil API (redemptions only)
    twitch_redemption_id: str = ""
    twitch_reward_id:     str = ""
    broadcaster_id:       str = ""

    @staticmethod
    def new_redemption(
        viewer_name: str,
        reward_name: str,
        user_input: str,
        cost: int,
        redemption_id: str,
        reward_id: str,
        broadcaster_id: str,
        timestamp: str,
    ) -> QueueItem:
        return QueueItem(
            item_id=str(uuid.uuid4()),
            kind=ItemKind.REDEMPTION,
            viewer_name=viewer_name,
            reward_name=reward_name,
            user_input=user_input,
            amount=cost,
            timestamp=timestamp,
            twitch_redemption_id=redemption_id,
            twitch_reward_id=reward_id,
            broadcaster_id=broadcaster_id,
        )

    @staticmethod
    def new_bits(
        viewer_name: str,
        bits: int,
        message: str,
        timestamp: str,
    ) -> QueueItem:
        return QueueItem(
            item_id=str(uuid.uuid4()),
            kind=ItemKind.BITS,
            viewer_name=viewer_name,
            reward_name="Bits Cheer",
            user_input=message,
            amount=bits,
            timestamp=timestamp,
        )

    def to_dict(self) -> dict:
        return {
            "item_id":              self.item_id,
            "kind":                 self.kind.value,
            "viewer_name":          self.viewer_name,
            "reward_name":          self.reward_name,
            "user_input":           self.user_input,
            "amount":               self.amount,
            "status":               self.status.value,
            "timestamp":            self.timestamp,
            "twitch_redemption_id": self.twitch_redemption_id,
            "twitch_reward_id":     self.twitch_reward_id,
            "broadcaster_id":       self.broadcaster_id,
        }

    @staticmethod
    def from_dict(d: dict) -> QueueItem:
        return QueueItem(
            item_id=d.get("item_id", str(uuid.uuid4())),
            kind=ItemKind(d.get("kind", "redemption")),
            viewer_name=d.get("viewer_name", ""),
            reward_name=d.get("reward_name", ""),
            user_input=d.get("user_input", ""),
            amount=int(d.get("amount", 0)),
            status=ItemStatus(d.get("status", "pending")),
            timestamp=d.get("timestamp", ""),
            twitch_redemption_id=d.get("twitch_redemption_id", ""),
            twitch_reward_id=d.get("twitch_reward_id", ""),
            broadcaster_id=d.get("broadcaster_id", ""),
        )
