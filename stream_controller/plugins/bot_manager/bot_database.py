from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from pathlib import Path

from stream_controller.plugins.bot_manager.bot_models import (
    BotCommand,
    DEFAULT_COMMANDS,
    EventResponse,
    TimedMessage,
)

logger = logging.getLogger(__name__)


class BotDatabase:
    """Per-bot SQLite database storing commands, timed messages, and event responses."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        if is_new:
            self._seed_defaults()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── DDL ───────────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS commands (
                command_id      TEXT PRIMARY KEY,
                bot_id          TEXT NOT NULL DEFAULT '',
                trigger         TEXT NOT NULL,
                response        TEXT NOT NULL DEFAULT '',
                cooldown_seconds INTEGER NOT NULL DEFAULT 5,
                enabled         INTEGER NOT NULL DEFAULT 1,
                is_builtin      INTEGER NOT NULL DEFAULT 0,
                last_used_ts    REAL NOT NULL DEFAULT 0,
                use_count       INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS timed_messages (
                msg_id              TEXT PRIMARY KEY,
                bot_id              TEXT NOT NULL DEFAULT '',
                message             TEXT NOT NULL DEFAULT '',
                interval_minutes    INTEGER NOT NULL DEFAULT 30,
                enabled             INTEGER NOT NULL DEFAULT 1,
                only_when_active    INTEGER NOT NULL DEFAULT 1,
                last_sent_ts        REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS event_responses (
                resp_id             TEXT PRIMARY KEY,
                bot_id              TEXT NOT NULL DEFAULT '',
                event_type          TEXT NOT NULL,
                response_template   TEXT NOT NULL DEFAULT '',
                enabled             INTEGER NOT NULL DEFAULT 1,
                min_bits            INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS command_stats (
                trigger         TEXT PRIMARY KEY,
                use_count       INTEGER NOT NULL DEFAULT 0,
                last_used_ts    REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_stats (
                user_id         TEXT NOT NULL DEFAULT '',
                username        TEXT NOT NULL,
                bits_total      INTEGER NOT NULL DEFAULT 0,
                subs_total      INTEGER NOT NULL DEFAULT 0,
                gifted_subs_total INTEGER NOT NULL DEFAULT 0,
                channel_points_total INTEGER NOT NULL DEFAULT 0,
                messages_total  INTEGER NOT NULL DEFAULT 0,
                first_seen_ts   REAL NOT NULL DEFAULT 0,
                last_seen_ts    REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (username)
            );

            CREATE TABLE IF NOT EXISTS events_log (
                event_id    TEXT PRIMARY KEY,
                event_type  TEXT NOT NULL,
                username    TEXT NOT NULL DEFAULT '',
                user_id     TEXT NOT NULL DEFAULT '',
                amount      INTEGER NOT NULL DEFAULT 0,
                extra       TEXT NOT NULL DEFAULT '',
                ts          REAL NOT NULL DEFAULT 0,
                stream_date TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS discord_routes (
                route_id            TEXT PRIMARY KEY,
                event_type          TEXT NOT NULL,
                channel_id          TEXT NOT NULL DEFAULT '',
                message_template    TEXT NOT NULL DEFAULT '',
                enabled             INTEGER NOT NULL DEFAULT 1
            );
        """)
        self._conn.commit()

    def _seed_defaults(self) -> None:
        for cmd in DEFAULT_COMMANDS:
            seeded = BotCommand(
                command_id=uuid.uuid4().hex,
                bot_id="",
                trigger=cmd.trigger,
                response=cmd.response,
                cooldown_seconds=cmd.cooldown_seconds,
                enabled=cmd.enabled,
                is_builtin=cmd.is_builtin,
            )
            self.save_command(seeded)

    # ── Commands ──────────────────────────────────────────────────────────────

    def list_commands(self) -> list[BotCommand]:
        cur = self._conn.execute(
            "SELECT command_id, bot_id, trigger, response, cooldown_seconds, enabled, is_builtin "
            "FROM commands ORDER BY trigger"
        )
        return [
            BotCommand(
                command_id=row["command_id"],
                bot_id=row["bot_id"],
                trigger=row["trigger"],
                response=row["response"],
                cooldown_seconds=row["cooldown_seconds"],
                enabled=bool(row["enabled"]),
                is_builtin=bool(row["is_builtin"]),
            )
            for row in cur.fetchall()
        ]

    def save_command(self, cmd: BotCommand) -> None:
        self._conn.execute(
            """
            INSERT INTO commands (command_id, bot_id, trigger, response, cooldown_seconds, enabled, is_builtin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(command_id) DO UPDATE SET
                bot_id           = excluded.bot_id,
                trigger          = excluded.trigger,
                response         = excluded.response,
                cooldown_seconds = excluded.cooldown_seconds,
                enabled          = excluded.enabled,
                is_builtin       = excluded.is_builtin
            """,
            (
                cmd.command_id,
                cmd.bot_id,
                cmd.trigger,
                cmd.response,
                cmd.cooldown_seconds,
                int(cmd.enabled),
                int(cmd.is_builtin),
            ),
        )
        self._conn.commit()

    def delete_command(self, command_id: str) -> None:
        self._conn.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        self._conn.commit()

    def record_command_use(self, trigger: str) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO command_stats (trigger, use_count, last_used_ts)
            VALUES (?, 1, ?)
            ON CONFLICT(trigger) DO UPDATE SET
                use_count    = use_count + 1,
                last_used_ts = excluded.last_used_ts
            """,
            (trigger, now),
        )
        self._conn.execute(
            "UPDATE commands SET use_count = use_count + 1, last_used_ts = ? WHERE trigger = ?",
            (now, trigger),
        )
        self._conn.commit()

    def get_command_last_used(self, trigger: str) -> float:
        row = self._conn.execute(
            "SELECT last_used_ts FROM command_stats WHERE trigger = ?", (trigger,)
        ).fetchone()
        return row["last_used_ts"] if row else 0.0

    # ── Timed messages ────────────────────────────────────────────────────────

    def list_timed_messages(self) -> list[TimedMessage]:
        cur = self._conn.execute(
            "SELECT msg_id, bot_id, message, interval_minutes, enabled, only_when_active, last_sent_ts "
            "FROM timed_messages"
        )
        return [
            TimedMessage(
                msg_id=row["msg_id"],
                bot_id=row["bot_id"],
                message=row["message"],
                interval_minutes=row["interval_minutes"],
                enabled=bool(row["enabled"]),
                only_when_active=bool(row["only_when_active"]),
                last_sent_ts=row["last_sent_ts"],
            )
            for row in cur.fetchall()
        ]

    def save_timed_message(self, msg: TimedMessage) -> None:
        self._conn.execute(
            """
            INSERT INTO timed_messages (msg_id, bot_id, message, interval_minutes, enabled, only_when_active, last_sent_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(msg_id) DO UPDATE SET
                bot_id           = excluded.bot_id,
                message          = excluded.message,
                interval_minutes = excluded.interval_minutes,
                enabled          = excluded.enabled,
                only_when_active = excluded.only_when_active,
                last_sent_ts     = excluded.last_sent_ts
            """,
            (
                msg.msg_id,
                msg.bot_id,
                msg.message,
                msg.interval_minutes,
                int(msg.enabled),
                int(msg.only_when_active),
                msg.last_sent_ts,
            ),
        )
        self._conn.commit()

    def delete_timed_message(self, msg_id: str) -> None:
        self._conn.execute("DELETE FROM timed_messages WHERE msg_id = ?", (msg_id,))
        self._conn.commit()

    def update_timed_last_sent(self, msg_id: str, ts: float) -> None:
        self._conn.execute(
            "UPDATE timed_messages SET last_sent_ts = ? WHERE msg_id = ?", (ts, msg_id)
        )
        self._conn.commit()

    # ── Event responses ───────────────────────────────────────────────────────

    def list_event_responses(self) -> list[EventResponse]:
        cur = self._conn.execute(
            "SELECT resp_id, bot_id, event_type, response_template, enabled, min_bits "
            "FROM event_responses"
        )
        return [
            EventResponse(
                resp_id=row["resp_id"],
                bot_id=row["bot_id"],
                event_type=row["event_type"],
                response_template=row["response_template"],
                enabled=bool(row["enabled"]),
                min_bits=row["min_bits"],
            )
            for row in cur.fetchall()
        ]

    def save_event_response(self, resp: EventResponse) -> None:
        self._conn.execute(
            """
            INSERT INTO event_responses (resp_id, bot_id, event_type, response_template, enabled, min_bits)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(resp_id) DO UPDATE SET
                bot_id            = excluded.bot_id,
                event_type        = excluded.event_type,
                response_template = excluded.response_template,
                enabled           = excluded.enabled,
                min_bits          = excluded.min_bits
            """,
            (
                resp.resp_id,
                resp.bot_id,
                resp.event_type,
                resp.response_template,
                int(resp.enabled),
                resp.min_bits,
            ),
        )
        self._conn.commit()

    def delete_event_response(self, resp_id: str) -> None:
        self._conn.execute("DELETE FROM event_responses WHERE resp_id = ?", (resp_id,))
        self._conn.commit()

    def enable_all_commands(self) -> None:
        self._conn.execute("UPDATE commands SET enabled = 1")
        self._conn.commit()

    _DEFAULT_EVENT_TYPES = [
        ("sub",            "🎉 {user} just subscribed!"),
        ("resub",          "🔄 {user} resubscribed for {months} months!"),
        ("giftsub",        "🎁 {user} gifted a sub!"),
        ("raid",           "⚔️ {user} raided with {viewers} viewers!"),
        ("bits",           "💎 {user} cheered {amount} bits!"),
        ("follow",         "❤️ {user} just followed!"),
        ("channel_points", "🏆 {user} redeemed {reward}!"),
    ]

    def enable_all_event_responses(self, bot_id: str = "") -> None:
        """Enable all event responses, seeding defaults for any that don't exist yet."""
        existing = {r.event_type for r in self.list_event_responses()}
        for event_type, default_template in self._DEFAULT_EVENT_TYPES:
            if event_type not in existing:
                resp = EventResponse(
                    resp_id=str(uuid.uuid4()),
                    bot_id=bot_id,
                    event_type=event_type,
                    response_template=default_template,
                    enabled=True,
                    min_bits=0,
                )
                self.save_event_response(resp)
        self._conn.execute("UPDATE event_responses SET enabled = 1")
        self._conn.commit()

    # ── User stats ────────────────────────────────────────────────────

    def upsert_user_stat(
        self,
        username: str,
        user_id: str = "",
        bits_delta: int = 0,
        subs_delta: int = 0,
        gifted_subs_delta: int = 0,
        channel_points_delta: int = 0,
        message_delta: int = 0,
    ) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO user_stats (username, user_id, bits_total, subs_total,
                gifted_subs_total, channel_points_total, messages_total,
                first_seen_ts, last_seen_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                user_id              = CASE WHEN excluded.user_id != '' THEN excluded.user_id ELSE user_id END,
                bits_total           = bits_total + excluded.bits_total,
                subs_total           = subs_total + excluded.subs_total,
                gifted_subs_total    = gifted_subs_total + excluded.gifted_subs_total,
                channel_points_total = channel_points_total + excluded.channel_points_total,
                messages_total       = messages_total + excluded.messages_total,
                last_seen_ts         = excluded.last_seen_ts
            """,
            (username, user_id, bits_delta, subs_delta, gifted_subs_delta,
             channel_points_delta, message_delta, now, now),
        )
        self._conn.commit()

    def list_user_stats(self) -> list:
        from stream_controller.plugins.bot_manager.bot_models import UserStat
        cur = self._conn.execute(
            "SELECT username, user_id, bits_total, subs_total, gifted_subs_total, "
            "channel_points_total, messages_total, first_seen_ts, last_seen_ts "
            "FROM user_stats ORDER BY last_seen_ts DESC"
        )
        return [
            UserStat(
                user_id=row["user_id"],
                username=row["username"],
                bits_total=row["bits_total"],
                subs_total=row["subs_total"],
                gifted_subs_total=row["gifted_subs_total"],
                channel_points_total=row["channel_points_total"],
                messages_total=row["messages_total"],
                first_seen_ts=row["first_seen_ts"],
                last_seen_ts=row["last_seen_ts"],
            )
            for row in cur.fetchall()
        ]

    # ── Events log ────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        username: str,
        user_id: str = "",
        amount: int = 0,
        extra: str = "",
    ) -> None:
        import uuid as _uuid
        from datetime import datetime
        now = time.time()
        stream_date = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        self._conn.execute(
            """
            INSERT INTO events_log (event_id, event_type, username, user_id, amount, extra, ts, stream_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_uuid.uuid4().hex, event_type, username, user_id, amount, extra, now, stream_date),
        )
        self._conn.commit()

    def list_events(self, event_type: str = "", limit: int = 200) -> list:
        from stream_controller.plugins.bot_manager.bot_models import EventLog
        if event_type:
            cur = self._conn.execute(
                "SELECT event_id, event_type, username, user_id, amount, extra, ts, stream_date "
                "FROM events_log WHERE event_type = ? ORDER BY ts DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT event_id, event_type, username, user_id, amount, extra, ts, stream_date "
                "FROM events_log ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
        return [
            EventLog(
                event_id=row["event_id"],
                event_type=row["event_type"],
                username=row["username"],
                user_id=row["user_id"],
                amount=row["amount"],
                extra=row["extra"],
                ts=row["ts"],
                stream_date=row["stream_date"],
            )
            for row in cur.fetchall()
        ]

    # ── Discord routes ─────────────────────────────────────────────────

    def list_discord_routes(self) -> list:
        from stream_controller.plugins.bot_manager.bot_models import DiscordRoute
        cur = self._conn.execute(
            "SELECT route_id, event_type, channel_id, message_template, enabled "
            "FROM discord_routes ORDER BY event_type"
        )
        return [
            DiscordRoute(
                route_id=row["route_id"],
                event_type=row["event_type"],
                channel_id=row["channel_id"],
                message_template=row["message_template"],
                enabled=bool(row["enabled"]),
            )
            for row in cur.fetchall()
        ]

    def save_discord_route(self, route) -> None:
        self._conn.execute(
            """
            INSERT INTO discord_routes (route_id, event_type, channel_id, message_template, enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(route_id) DO UPDATE SET
                event_type       = excluded.event_type,
                channel_id       = excluded.channel_id,
                message_template = excluded.message_template,
                enabled          = excluded.enabled
            """,
            (route.route_id, route.event_type, route.channel_id, route.message_template, int(route.enabled)),
        )
        self._conn.commit()

    def delete_discord_route(self, route_id: str) -> None:
        self._conn.execute("DELETE FROM discord_routes WHERE route_id = ?", (route_id,))
        self._conn.commit()
