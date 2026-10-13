from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

from bot.services.roblox import Sale, sale_from_raw

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Ticket:
    channel_id: int
    owner_id: int
    claimed_by: int | None
    number: int
    kind: str
    reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Giveaway:
    message_id: int
    guild_id: int
    channel_id: int
    winners: int
    members: list[int]
    finish: datetime
    host_id: int
    title: str
    required_roles: list[int] | None
    bonus_roles: list[int] | None
    ignore_roles: list[int] | None
    required_servers: list[int] | None


def _ids(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, str | bytes | bytearray):
        value = json.loads(value)
    if isinstance(value, list):
        return [int(item) for item in value]
    if isinstance(value, int):
        return [value]
    return None


def _member_ids(value: Any) -> list[int]:
    return _ids(value) or []


def _sale(row: Any) -> Sale | None:
    raw = row["raw"]
    if isinstance(raw, str | bytes | bytearray):
        raw = json.loads(raw)
    return sale_from_raw(raw) if isinstance(raw, dict) else None


def _ticket(row: Any) -> Ticket:
    return Ticket(
        channel_id=int(row["channel_id"]),
        owner_id=int(row["owner_id"]),
        claimed_by=int(row["claimed_by"]) if row["claimed_by"] is not None else None,
        number=int(row["number"] or 0),
        kind=str(row["kind"] or "general"),
        reason=str(row["reason"] or ""),
        created_at=row["created_at"],
    )


def _giveaway(row: Any) -> Giveaway:
    return Giveaway(
        message_id=int(row["message_id"]),
        guild_id=int(row["guild_id"]),
        channel_id=int(row["channel_id"]),
        winners=int(row["winners"]),
        members=_member_ids(row["members"]),
        finish=row["finish"],
        host_id=int(row["host_id"]),
        title=str(row["title"]),
        required_roles=_ids(row["required_roles"]),
        bonus_roles=_ids(row["bonus_roles"]),
        ignore_roles=_ids(row["ignore_roles"]),
        required_servers=_ids(row["required_servers"]),
    )


class Database:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def close(self) -> None:
        await self._pool.close()

    async def known_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        rows = await self._pool.fetch(
            "SELECT id FROM transactions WHERE id = ANY($1::bigint[])",
            ids,
        )
        return {int(row["id"]) for row in rows}

    async def store_sales(self, group_id: int, sales: list[Sale]) -> None:
        if not sales:
            return
        await self._pool.executemany(
            """
            INSERT INTO transactions (
                id, group_id, kind, amount, currency,
                agent_id, agent_name, agent_type,
                item_id, item_name, item_type,
                pending, created_at, raw
            ) VALUES (
                $1, $2, 'Sale', $3, $4,
                $5, $6, $7,
                $8, $9, $10,
                $11, $12, $13::jsonb
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    sale.id,
                    group_id,
                    sale.amount,
                    sale.currency,
                    sale.agent_id,
                    sale.agent_name,
                    sale.agent_type,
                    sale.item_id,
                    sale.item_name or None,
                    sale.item_type or None,
                    sale.pending,
                    sale.created,
                    json.dumps(sale.raw, separators=(",", ":")),
                )
                for sale in sales
            ],
        )

    async def agent_sales(self, group_id: int, agent_id: int) -> list[Sale]:
        rows = await self._pool.fetch(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale' AND agent_id = $2
            ORDER BY created_at DESC
            """,
            group_id,
            agent_id,
        )
        return [sale for row in rows if (sale := _sale(row))]

    async def recent_sale(self, group_id: int) -> Sale | None:
        row = await self._pool.fetchrow(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            group_id,
        )
        return _sale(row) if row else None

    async def highest_sale(self, group_id: int) -> Sale | None:
        row = await self._pool.fetchrow(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale'
            ORDER BY amount DESC, created_at DESC
            LIMIT 1
            """,
            group_id,
        )
        return _sale(row) if row else None

    async def sales_summary(
        self,
        group_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[int, int]:
        row = await self._pool.fetchrow(
            """
            SELECT COUNT(*)::bigint AS count, COALESCE(SUM(amount), 0)::bigint AS total
            FROM transactions
            WHERE group_id = $1
              AND kind = 'Sale'
              AND ($2::timestamptz IS NULL OR created_at >= $2)
              AND ($3::timestamptz IS NULL OR created_at < $3)
            """,
            group_id,
            start,
            end,
        )
        if row is None:
            return 0, 0
        return int(row["count"]), int(row["total"])

    async def setting(self, key: str) -> Any:
        raw = await self._pool.fetchval("SELECT value FROM settings WHERE key = $1", key)
        return json.loads(raw) if isinstance(raw, str) else raw

    async def store_setting(self, key: str, value: Any) -> None:
        await self._pool.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            key,
            json.dumps(value),
        )

    async def drop_setting(self, key: str) -> None:
        await self._pool.execute("DELETE FROM settings WHERE key = $1", key)

    async def ticket(self, channel_id: int) -> Ticket | None:
        row = await self._pool.fetchrow(
            """
            SELECT channel_id, owner_id, claimed_by, number, kind, reason, created_at
            FROM tickets
            WHERE channel_id = $1
            """,
            channel_id,
        )
        return _ticket(row) if row else None

    async def open_ticket_count(self, owner_id: int) -> int:
        value = await self._pool.fetchval(
            "SELECT COUNT(*)::bigint FROM tickets WHERE owner_id = $1",
            owner_id,
        )
        return int(value or 0)

    async def next_ticket_number(self) -> int:
        value = await self._pool.fetchval("SELECT nextval('ticket_number_seq')")
        return int(value)

    async def create_ticket(
        self,
        channel_id: int,
        owner_id: int,
        number: int,
        kind: str,
        reason: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO tickets (channel_id, owner_id, number, kind, reason)
            VALUES ($1, $2, $3, $4, $5)
            """,
            channel_id,
            owner_id,
            number,
            kind,
            reason,
        )

    async def claim_ticket(self, channel_id: int, user_id: int) -> None:
        await self._pool.execute(
            "UPDATE tickets SET claimed_by = $1 WHERE channel_id = $2",
            user_id,
            channel_id,
        )
        await self._pool.execute(
            "INSERT INTO ticket_claims (user_id, channel_id) VALUES ($1, $2)",
            user_id,
            channel_id,
        )

    async def unclaim_ticket(self, channel_id: int) -> None:
        await self._pool.execute(
            "UPDATE tickets SET claimed_by = NULL WHERE channel_id = $1",
            channel_id,
        )

    async def delete_ticket(self, channel_id: int) -> None:
        await self._pool.execute("DELETE FROM tickets WHERE channel_id = $1", channel_id)

    async def ticket_leaderboard(self, limit: int = 10) -> list[tuple[int, int]]:
        rows = await self._pool.fetch(
            """
            SELECT user_id, COUNT(*)::bigint AS claims
            FROM ticket_claims
            GROUP BY user_id
            ORDER BY claims DESC, user_id ASC
            LIMIT $1
            """,
            limit,
        )
        return [(int(row["user_id"]), int(row["claims"])) for row in rows]

    async def giveaway(self, guild_id: int, message_id: int) -> Giveaway | None:
        row = await self._pool.fetchrow(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, bonus_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE guild_id = $1 AND message_id = $2
            """,
            guild_id,
            message_id,
        )
        return _giveaway(row) if row else None

    async def giveaway_by_message(self, message_id: int) -> Giveaway | None:
        row = await self._pool.fetchrow(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, bonus_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE message_id = $1
            """,
            message_id,
        )
        return _giveaway(row) if row else None

    async def giveaways(self, guild_id: int) -> list[Giveaway]:
        rows = await self._pool.fetch(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, bonus_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE guild_id = $1
            ORDER BY finish ASC
            """,
            guild_id,
        )
        return [_giveaway(row) for row in rows]

    async def active_giveaway_count(self, guild_id: int) -> int:
        value = await self._pool.fetchval(
            "SELECT COUNT(*)::bigint FROM giveaways WHERE guild_id = $1",
            guild_id,
        )
        return int(value or 0)

    async def expired_giveaways(self, now: datetime) -> list[Giveaway]:
        rows = await self._pool.fetch(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, bonus_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE finish <= $1
            """,
            now,
        )
        return [_giveaway(row) for row in rows]

    async def create_giveaway(
        self,
        *,
        message_id: int,
        guild_id: int,
        channel_id: int,
        winners: int,
        finish: datetime,
        host_id: int,
        title: str,
        required_roles: list[int] | None,
        bonus_roles: list[int] | None,
        ignore_roles: list[int] | None,
        required_servers: list[int] | None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO giveaways (
                message_id, guild_id, channel_id, winners, members, finish, host_id, title,
                required_roles, bonus_roles, ignore_roles, required_servers
            ) VALUES (
                $1, $2, $3, $4, '[]'::jsonb, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb
            )
            """,
            message_id,
            guild_id,
            channel_id,
            winners,
            finish,
            host_id,
            title,
            json.dumps(required_roles) if required_roles else None,
            json.dumps(bonus_roles) if bonus_roles else None,
            json.dumps(ignore_roles) if ignore_roles else None,
            json.dumps(required_servers) if required_servers else None,
        )

    async def set_giveaway_members(self, message_id: int, members: list[int]) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET members = $1::jsonb WHERE message_id = $2",
            json.dumps(members),
            message_id,
        )

    async def set_giveaway_title(self, message_id: int, title: str) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET title = $1 WHERE message_id = $2",
            title,
            message_id,
        )

    async def set_giveaway_finish(self, message_id: int, finish: datetime) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET finish = $1 WHERE message_id = $2",
            finish,
            message_id,
        )

    async def set_giveaway_host(self, message_id: int, host_id: int) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET host_id = $1 WHERE message_id = $2",
            host_id,
            message_id,
        )

    async def set_giveaway_winners(self, message_id: int, winners: int) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET winners = $1 WHERE message_id = $2",
            winners,
            message_id,
        )

    async def set_giveaway_roles(
        self,
        message_id: int,
        column: str,
        role_ids: list[int] | None,
    ) -> None:
        if column not in {
            "required_roles",
            "bonus_roles",
            "ignore_roles",
            "required_servers",
        }:
            raise ValueError(f"invalid giveaway column: {column}")
        await self._pool.execute(
            f"UPDATE giveaways SET {column} = $1::jsonb WHERE message_id = $2",
            json.dumps(role_ids) if role_ids else None,
            message_id,
        )

    async def delete_giveaway(self, message_id: int) -> None:
        await self._pool.execute("DELETE FROM giveaways WHERE message_id = $1", message_id)

    async def ended_giveaway(self, channel_id: int, message_id: int) -> list[int] | None:
        row = await self._pool.fetchrow(
            """
            SELECT members FROM giveaways_ended
            WHERE channel_id = $1 AND message_id = $2
            """,
            channel_id,
            message_id,
        )
        return _member_ids(row["members"]) if row else None

    async def store_ended_giveaway(
        self,
        channel_id: int,
        message_id: int,
        members: list[int],
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO giveaways_ended (message_id, channel_id, members)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (message_id) DO UPDATE
            SET channel_id = EXCLUDED.channel_id, members = EXCLUDED.members
            """,
            message_id,
            channel_id,
            json.dumps(members),
        )
        await self.delete_giveaway(message_id)


async def connect(dsn: str) -> tuple[Database, str]:
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,
    )
    if pool is None:
        raise RuntimeError("Failed to connect to the database")
    for statement in _SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await pool.execute(sql)
    version = await pool.fetchval("SELECT version()")
    return Database(pool), str(version).split("(", maxsplit=1)[0].strip()
