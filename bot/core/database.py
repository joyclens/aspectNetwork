from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncpg

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


class Database:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def close(self) -> None:
        await self._pool.close()


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
