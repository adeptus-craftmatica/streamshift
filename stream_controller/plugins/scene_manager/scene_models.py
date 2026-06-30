from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"


@dataclass
class Scene:
    name: str
    uuid: str = ""
    is_current: bool = False
    is_group: bool = False

    def to_dict(self) -> dict:
        return {
            "name":       self.name,
            "uuid":       self.uuid,
            "is_current": self.is_current,
        }


@dataclass
class SceneManagerState:
    status:        ConnectionStatus = ConnectionStatus.DISCONNECTED
    current_scene: str = ""
    scenes:        list[Scene] = field(default_factory=list)
    error:         str = ""
    stream_active: bool = False
    record_active: bool = False

    def to_dict(self) -> dict:
        return {
            "connected":     self.status == ConnectionStatus.CONNECTED,
            "status":        self.status.value,
            "current_scene": self.current_scene,
            "scenes":        [s.to_dict() for s in self.scenes],
            "stream_active": self.stream_active,
            "record_active": self.record_active,
        }
