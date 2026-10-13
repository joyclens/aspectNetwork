from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

from bot.shared.errors import DatabaseUnavailable

if TYPE_CHECKING:
    from bot.core.bot import Aspect
    from bot.core.database import Database


def database(bot: Aspect) -> Database:
    if bot.db is None:
        raise DatabaseUnavailable()
    return bot.db


async def database_ready(ctx: commands.Context[Aspect]) -> bool:
    database(ctx.bot)
    return True
