from __future__ import annotations

from typing import Any, Callable

CommandHandler = Callable[..., Any]


class CommandRegistry:
    """Tracks named commands that plugins or the core app can execute."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}

    def register(self, command_name: str, callable_obj: CommandHandler) -> None:
        if command_name in self._commands:
            raise ValueError(f"Command '{command_name}' is already registered.")
        self._commands[command_name] = callable_obj

    def execute(self, command_name: str, **kwargs: Any) -> Any:
        if command_name not in self._commands:
            raise KeyError(f"Command '{command_name}' is not registered.")
        return self._commands[command_name](**kwargs)

    def unregister(self, command_name: str) -> None:
        if command_name not in self._commands:
            raise KeyError(f"Command '{command_name}' is not registered.")
        self._commands.pop(command_name, None)

    def list_commands(self) -> list[str]:
        return sorted(self._commands)
