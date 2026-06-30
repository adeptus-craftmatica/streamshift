from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MacroStep:
    step_id: str
    step_type: str
    params: dict
    label: str
    then_steps: list["MacroStep"] = field(default_factory=list)
    else_steps: list["MacroStep"] = field(default_factory=list)
    body_steps: list["MacroStep"] = field(default_factory=list)
    on_error: str = "skip"  # "skip" | "abort" | "retry"


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


@dataclass
class MacroExecutionRecord:
    run_id: str
    macro_id: str
    macro_name: str
    started_at: float
    finished_at: float | None
    steps_completed: int
    total_steps: int
    error: str | None
    success: bool
