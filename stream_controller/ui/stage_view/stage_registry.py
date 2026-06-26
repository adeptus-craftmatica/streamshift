from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class StageWidgetDef:
    panel_id: str
    title:    str
    icon:     str
    factory:  Callable[[], Any]


class StageRegistry:
    """Global registry of widgets plugins can contribute to the Stage View."""

    def __init__(self) -> None:
        self._widgets: dict[str, StageWidgetDef] = {}

    def register(self, panel_id: str, title: str, icon: str, factory: Callable[[], Any]) -> None:
        self._widgets[panel_id] = StageWidgetDef(
            panel_id=panel_id,
            title=title,
            icon=icon,
            factory=factory,
        )

    def unregister(self, panel_id: str) -> None:
        self._widgets.pop(panel_id, None)

    def list_widgets(self) -> list[StageWidgetDef]:
        return list(self._widgets.values())

    def get(self, panel_id: str) -> StageWidgetDef | None:
        return self._widgets.get(panel_id)
