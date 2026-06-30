from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from stream_controller.plugins.macro_manager.macro_models import Macro, MacroStep

logger = logging.getLogger(__name__)


def _step_to_dict(step: MacroStep) -> dict:
    return {
        "step_id": step.step_id,
        "step_type": step.step_type,
        "params": step.params,
        "label": step.label,
        "then_steps": [_step_to_dict(s) for s in step.then_steps],
        "else_steps": [_step_to_dict(s) for s in step.else_steps],
        "body_steps": [_step_to_dict(s) for s in step.body_steps],
        "on_error": step.on_error,
    }


def _dict_to_step(s: dict) -> MacroStep:
    return MacroStep(
        step_id=s["step_id"],
        step_type=s["step_type"],
        params=s.get("params", {}),
        label=s.get("label", ""),
        then_steps=[_dict_to_step(c) for c in s.get("then_steps", [])],
        else_steps=[_dict_to_step(c) for c in s.get("else_steps", [])],
        body_steps=[_dict_to_step(c) for c in s.get("body_steps", [])],
        on_error=s.get("on_error", "skip"),
    )


class MacroRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._macros: dict[str, Macro] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for d in data:
                steps = [_dict_to_step(s) for s in d.get("steps", [])]
                macro = Macro(
                    macro_id=d["macro_id"],
                    name=d["name"],
                    icon=d.get("icon", "▶"),
                    description=d.get("description", ""),
                    steps=steps,
                    hotkey=d.get("hotkey", ""),
                    show_on_stage=bool(d.get("show_on_stage", True)),
                    created_at=d.get("created_at", ""),
                )
                self._macros[macro.macro_id] = macro
        except Exception as exc:
            logger.warning("Could not load macros: %s", exc)

    def _save_all(self) -> None:
        try:
            data = [
                {
                    "macro_id": m.macro_id,
                    "name": m.name,
                    "icon": m.icon,
                    "description": m.description,
                    "steps": [_step_to_dict(s) for s in m.steps],
                    "hotkey": m.hotkey,
                    "show_on_stage": m.show_on_stage,
                    "created_at": m.created_at,
                }
                for m in self._macros.values()
            ]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save macros: %s", exc)

    def list_macros(self) -> list[Macro]:
        return list(self._macros.values())

    def get_macro(self, macro_id: str) -> Macro | None:
        return self._macros.get(macro_id)

    def save_macro(self, macro: Macro) -> None:
        self._macros[macro.macro_id] = macro
        self._save_all()

    def delete_macro(self, macro_id: str) -> None:
        self._macros.pop(macro_id, None)
        self._save_all()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]
