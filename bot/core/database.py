from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg

from bot.services.roblox import Sale, sale_from_raw

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def _sale(row: Any) -> Sale | None:
    raw = row["raw"]
    if isinstance(raw, str | bytes | bytearray):
        raw = json.loads(raw)
    return sale_from_raw(raw) if isinstance(raw, dict) else None


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
