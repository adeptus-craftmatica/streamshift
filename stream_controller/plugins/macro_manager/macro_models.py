from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MacroStep:
    step_id: str
    step_type: str
    params: dict
    label: str


@dataclass
class Macro:
    macro_id: str
    name: str
    icon: str
    description: str
    steps: list[MacroStep]
    hotkey: str
    show_on_stage: bool
    created_at: str
