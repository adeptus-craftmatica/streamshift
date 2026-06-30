from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from stream_controller.core.keyring_helper import (
    load as _kr_load, store as _kr_store, delete as _kr_delete,
)
from stream_controller.plugins.bot_manager.bot_models import BotConfig

logger = logging.getLogger(__name__)

# Sensitive fields stored in keychain, not JSON.  Key format:
#   "bot/{bot_id}/{field}"
_BOT_SENSITIVE = {"twitch_oauth_token", "discord_bot_token", "twitch_broadcaster_token"}


def _bot_ns(bot_id: str) -> str:
    return f"bot/{bot_id}"


class BotRepository:
    """
    Stores bot configurations as a JSON list on disk.
    Sensitive credentials (OAuth tokens, Discord bot token) are stored in the
    system keychain and never written to the JSON file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._bots: dict[str, BotConfig] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def list_bots(self) -> list[BotConfig]:
        return list(self._bots.values())

    def get_bot(self, bot_id: str) -> BotConfig | None:
        return self._bots.get(bot_id)

    def save_bot(self, bot: BotConfig) -> None:
        # Persist sensitive fields to keychain
        ns = _bot_ns(bot.bot_id)
        for field in _BOT_SENSITIVE:
            value = getattr(bot, field, "")
            _kr_store(ns, field, value or "")

        # Zero out sensitive fields before storing in memory / JSON
        safe = BotConfig(**{
            **vars(bot),
            **{f: "" for f in _BOT_SENSITIVE},
        })
        self._bots[bot.bot_id] = safe
        self._flush()

    def get_bot_with_secrets(self, bot_id: str) -> BotConfig | None:
        """Return bot config with secrets merged back in from keychain."""
        bot = self._bots.get(bot_id)
        if bot is None:
            return None
        return self._hydrate(bot)

    def list_bots_with_secrets(self) -> list[BotConfig]:
        return [self._hydrate(b) for b in self._bots.values()]

    def delete_bot(self, bot_id: str) -> None:
        if bot_id not in self._bots:
            return
        ns = _bot_ns(bot_id)
        for field in _BOT_SENSITIVE:
            _kr_delete(ns, field)
        del self._bots[bot_id]
        self._flush()

    # ── internal ──────────────────────────────────────────────────────────────

    def _hydrate(self, bot: BotConfig) -> BotConfig:
        """Merge keychain secrets back into a sanitised BotConfig."""
        ns = _bot_ns(bot.bot_id)
        return BotConfig(**{
            **vars(bot),
            **{f: _kr_load(ns, f) for f in _BOT_SENSITIVE},
        })

    def _load(self) -> None:
        if not self._path.exists():
            self._bots = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            bots = {}
            for entry in raw:
                if not isinstance(entry, dict) or "bot_id" not in entry:
                    continue
                # Strip any sensitive values that ended up in JSON (one-time migration)
                bot = BotConfig.from_dict(entry)
                ns = _bot_ns(bot.bot_id)
                for field in _BOT_SENSITIVE:
                    if getattr(bot, field, ""):
                        _kr_store(ns, field, getattr(bot, field))
                        setattr(bot, field, "")
                bots[bot.bot_id] = bot
            self._bots = bots
            # Re-flush to remove any secrets that were in the file
            self._flush()
        except Exception as exc:
            logger.warning("Could not load bots.json: %s", exc)
            self._bots = {}

    def _flush(self) -> None:
        safe_list = []
        for bot in self._bots.values():
            d = bot.to_dict()
            for f in _BOT_SENSITIVE:
                d[f] = ""
            safe_list.append(d)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(safe_list, indent=2), encoding="utf-8")
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as exc:
            logger.error("Could not save bots.json: %s", exc)
