from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from bot.core.bot import Aspect
from bot.shared.context import require_context
from bot.shared.layout import container_view


class Funds(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.hybrid_group(name="funds", fallback="balance")  # type: ignore[arg-type]
    async def funds(self, ctx: commands.Context[Any]) -> None:
        """Show the group's Robux and pending Robux."""
        ctx = require_context(ctx)
        if self.bot.roblox is None:
            await ctx.warn("Roblox is not ready.")
            return
        robux, pending = await self.bot.roblox.balance()
        emoji = self.bot.settings.emojis.robux
        text = f"# Funds\n**Robux**\n{emoji} {robux:,}\n**Pending**\n{emoji} {pending:,}"
        await ctx.send(view=container_view(discord.ui.TextDisplay(text)))


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Funds(bot))
