from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.chat_manager.chat_state import ChatStateManager


def make_action_handlers(chat_state: "ChatStateManager") -> dict[str, callable]:
    return {
        "chat.connect": chat_state.connect,
        "chat.disconnect": chat_state.disconnect,
        "chat.clear_chat": chat_state.clear_chat,
        "chat.slow_mode_on": lambda: chat_state.set_slow_mode(30),
        "chat.slow_mode_off": lambda: chat_state.set_slow_mode(0),
        "chat.sub_only_on": lambda: chat_state.set_sub_only(True),
        "chat.sub_only_off": lambda: chat_state.set_sub_only(False),
        "chat.emote_only_on": lambda: chat_state.set_emote_only(True),
        "chat.emote_only_off": lambda: chat_state.set_emote_only(False),
    }


ACTION_DEFINITIONS = [
    {
        "action_id": "chat.chat_tile",
        "title": "Chat Manager Tile",
        "description": "Compact live-chat tile showing the latest messages and a quick-send box.",
        "icon": "💬",
        "page": "Chat",
        "group": "Chat Manager",
    },
    {
        "action_id": "chat.open_panel",
        "title": "Open Chat Manager",
        "description": "Open the Chat Manager plugin workspace.",
        "icon": "CH",
        "page": "Chat",
        "group": "Chat Manager",
        "default_shortcut": "Ctrl+Alt+C",
    },
    {
        "action_id": "chat.connect",
        "title": "Connect to Chat",
        "description": "Connect to the configured Twitch channel.",
        "icon": "CN",
        "page": "Chat",
        "group": "Connection",
    },
    {
        "action_id": "chat.disconnect",
        "title": "Disconnect Chat",
        "description": "Disconnect from the Twitch chat IRC.",
        "icon": "DC",
        "page": "Chat",
        "group": "Connection",
    },
    {
        "action_id": "chat.clear_chat",
        "title": "Clear Chat",
        "description": "Send /clear to remove all visible chat messages.",
        "icon": "CL",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.slow_mode_on",
        "title": "Slow Mode On (30s)",
        "description": "Enable slow mode at 30 seconds.",
        "icon": "SM",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.slow_mode_off",
        "title": "Slow Mode Off",
        "description": "Disable slow mode.",
        "icon": "SF",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.sub_only_on",
        "title": "Subscriber Only On",
        "description": "Restrict chat to subscribers only.",
        "icon": "S+",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.sub_only_off",
        "title": "Subscriber Only Off",
        "description": "Allow all viewers to chat.",
        "icon": "S-",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.emote_only_on",
        "title": "Emote Only On",
        "description": "Restrict chat to emotes only.",
        "icon": "E+",
        "page": "Chat",
        "group": "Moderation",
    },
    {
        "action_id": "chat.emote_only_off",
        "title": "Emote Only Off",
        "description": "Allow all message types in chat.",
        "icon": "E-",
        "page": "Chat",
        "group": "Moderation",
    },
]
