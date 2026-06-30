from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.timer_manager.timer_engine import TimerEngine


def make_action_handlers(engine: "TimerEngine") -> dict[str, callable]:
    return {
        "timer.start":   engine.start_active,
        "timer.pause":   engine.pause_active,
        "timer.stop":    engine.stop_active,
        "timer.reset":   engine.reset_active,
        "timer.toggle":  engine.toggle_active,
    }


ACTION_DEFINITIONS = [
    {
        "action_id": "timer.timer_tile",
        "title": "Timer Tile",
        "description": "Compact timer card showing all timers with play/pause/reset controls.",
        "icon": "⏱",
        "page": "Timer",
        "group": "Timer Manager",
    },
    {
        "action_id": "timer.open_panel",
        "title": "Open Timer Manager",
        "description": "Open the Timer Manager plugin workspace.",
        "icon": "TM",
        "page": "Timer",
        "group": "Timer Manager",
        "default_shortcut": "Ctrl+Alt+T",
    },
    {
        "action_id": "timer.toggle",
        "title": "Play / Pause",
        "description": "Toggle the active timer.",
        "icon": "▶",
        "page": "Timer",
        "group": "Transport",
        "default_shortcut": "Ctrl+Alt+Space",
    },
    {
        "action_id": "timer.start",
        "title": "Start",
        "description": "Start the active timer.",
        "icon": "ST",
        "page": "Timer",
        "group": "Transport",
    },
    {
        "action_id": "timer.pause",
        "title": "Pause",
        "description": "Pause the active timer.",
        "icon": "PA",
        "page": "Timer",
        "group": "Transport",
    },
    {
        "action_id": "timer.stop",
        "title": "Stop",
        "description": "Stop and reset the active timer to zero.",
        "icon": "SP",
        "page": "Timer",
        "group": "Transport",
    },
    {
        "action_id": "timer.reset",
        "title": "Reset",
        "description": "Reset the active timer without stopping it.",
        "icon": "RS",
        "page": "Timer",
        "group": "Transport",
    },
]
