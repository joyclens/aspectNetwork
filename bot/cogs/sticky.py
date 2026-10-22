from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Guild
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Ctx = commands.Context[Any]
MAX_MESSAGE = 2000
NO_MENTIONS = discord.AllowedMentions.none()


class Sticky(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, channel_id: int) -> asyncio.Lock:
        lock = self._locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[channel_id] = lock
        return lock

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="sticky",
        aliases=("stickymessage", "stickymsg"),
        fallback="list",
        description="List channels that keep a sticky message at the bottom.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def sticky(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        rows = await database(self.bot).stickies(ctx.guild.id)
        if not rows:
            await ctx.warn("There are no sticky messages configured.")
            return
        lines = [
            f"<#{row.channel_id}> — `{row.message[:80]}{'…' if len(row.message) > 80 else ''}`"
            for row in rows
        ]
        await ctx.send(
            view=container_view(discord.ui.TextDisplay("## Sticky messages\n" + "\n".join(lines))),
            allowed_mentions=NO_MENTIONS,
        )

    @sticky.command(  # type: ignore[arg-type]
        name="add",
        description="Add or replace a sticky message in a channel.",
    )
    @app_commands.describe(
        channel="Channel that should keep the sticky message",
        message="Text posted after each new message",
        keep_old="Keep previous sticky messages instead of deleting them",
    )
    @commands.has_permissions(manage_guild=True)
    async def sticky_add(
        self,
        ctx: Ctx,
        channel: discord.TextChannel,
        *,
        message: str,
        keep_old: bool = False,
    ) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        text = message.replace("\\n", "\n").strip()
        if not text or len(text) > MAX_MESSAGE:
            await ctx.warn("That sticky message is not valid.")
            return
        if channel.guild.id != ctx.guild.id:
            await ctx.warn("That channel is not in this server.")
            return
        await database(self.bot).upsert_sticky(ctx.guild.id, channel.id, text, keep_old)
        await ctx.approve(f"Sticky message set in {channel.mention}.")

    @sticky.command(  # type: ignore[arg-type]
        name="remove",
        description="Remove the sticky message from a channel.",
    )
    @app_commands.describe(channel="Channel to clear the sticky message from")
    @commands.has_permissions(manage_guild=True)
    async def sticky_remove(self, ctx: Ctx, channel: discord.TextChannel) -> None:
        ctx = require_context(ctx)
        if not await database(self.bot).delete_sticky(channel.id):
            await ctx.warn("There is no sticky message in that channel.")
            return
        await ctx.approve(f"Sticky message removed from {channel.mention}.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if message.guild.id != Guild.id:
            return
        if not message.content and not message.attachments and not message.embeds:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if self.bot.db is None:
            return
        async with self._lock(message.channel.id):
            row = await self.bot.db.sticky(message.channel.id)
            if row is None or row.guild_id != message.guild.id:
                return
            await self._repost(message.channel, row.message, row.last_message_id, row.keep_old)

    async def _repost(
        self,
        channel: discord.TextChannel,
        text: str,
        last_message_id: int | None,
        keep_old: bool,
    ) -> None:
        if not keep_old and last_message_id is not None:
            try:
                previous = await channel.fetch_message(last_message_id)
                await previous.delete()
            except discord.HTTPException:
                pass
        try:
            posted = await channel.send(text, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            logger.warning("Could not post sticky message in %s", channel.id)
            return
        try:
            await database(self.bot).set_sticky_last_message(channel.id, posted.id)
        except Exception:
            logger.exception("Could not store sticky message id for %s", channel.id)


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Sticky(bot))
