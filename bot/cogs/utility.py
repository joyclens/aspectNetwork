from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot import Aspect
from bot.shared.context import require_context


class Utility(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.hybrid_command(
        name="say",
        description="Send a message as the bot",
        )  # type: ignore[arg-type]
    @app_commands.describe(message="Text to send in this channel")
    async def say(self, ctx: commands.Context[Any], *, message: str) -> None:
        """Send a message as the bot."""
        ctx = require_context(ctx)
        text = message.strip()
        if not text or len(text) > 2000:
            await ctx.warn("That message is not valid.")
            return
        if ctx.interaction is not None:
            await ctx.interaction.response.send_message("Sent.", ephemeral=True)
        elif ctx.message is not None:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
        if not isinstance(ctx.channel, discord.abc.Messageable):
            return
        await ctx.channel.send(text)


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Utility(bot))
