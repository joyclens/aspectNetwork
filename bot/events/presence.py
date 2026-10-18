from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

import discord
from discord.ext import commands, tasks

from bot.core.bot import Aspect
from bot.core.ids import Guild

logger = logging.getLogger("aspect")

_STATUSES: Final[tuple[Callable[[int], str], ...]] = (
    lambda n: f"💫 Watching {n:,} Members",
    lambda _: "🌸 .gg/aspct",
    lambda n: f"✨ Networking with {n:,} Members",
    lambda _: "♦️ Powering Aspect Network",
)


class Presence(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._index = 0

    async def cog_load(self) -> None:
        self.rotate.start()

    async def cog_unload(self) -> None:
        self.rotate.cancel()

    @tasks.loop(seconds=30)
    async def rotate(self) -> None:
        guild = self.bot.get_guild(Guild.id)
        count = guild.member_count if guild is not None and guild.member_count is not None else 0
        text = _STATUSES[self._index](count)
        self._index = (self._index + 1) % len(_STATUSES)
        try:
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.CustomActivity(name=text),
            )
        except discord.HTTPException:
            logger.warning("Could not update presence")

    @rotate.before_loop
    async def before_rotate(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Presence(bot))
