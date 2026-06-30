from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_POOL_PATH = Path.home() / ".streamshift" / "macro_manager" / "chat_pool.json"


class ChatMessagePool:
    """Persistent library of reusable bot chat messages."""

    @staticmethod
    def load() -> list[str]:
        try:
            if _POOL_PATH.exists():
                data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
                return [m for m in data if isinstance(m, str) and m.strip()]
        except Exception as exc:
            logger.warning("ChatMessagePool.load: %s", exc)
        return []

    @staticmethod
    def save(messages: list[str]) -> None:
        try:
            _POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
            _POOL_PATH.write_text(
                json.dumps([m for m in messages if m.strip()], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("ChatMessagePool.save: %s", exc)

    @staticmethod
    def add(message: str) -> None:
        msgs = ChatMessagePool.load()
        if message.strip() and message.strip() not in msgs:
            msgs.append(message.strip())
            ChatMessagePool.save(msgs)

    @staticmethod
    def remove(message: str) -> None:
        msgs = ChatMessagePool.load()
        ChatMessagePool.save([m for m in msgs if m != message])
