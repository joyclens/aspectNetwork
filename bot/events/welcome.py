from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.core.bot import Aspect
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")


class Welcome(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or member.guild.id != self.bot.settings.discord_guild_id:
            return
        channel = self.bot.get_channel(1551307570822779020)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(1551307570822779020)
            except discord.HTTPException:
                logger.warning("Welcome channel is unavailable")
                return
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Welcome channel is unavailable")
            return
        count = member.guild.member_count or len(member.guild.members)
        try:
            await channel.send(
                view=container_view(
                    discord.ui.TextDisplay(
                        "<:affiliate:1551256291043971202> "
                        f"Welcome <@{member.id}> to **Aspect Network**! "
                        "We are pleased to have you join our journey "
                        "to become *Your Ideal Connection*.\n"
                        "-# And don't forget to check out our "
                        "**[marketplace](https://discordapp.com/channels/1559284770440216639/1529142741110358027)**"
                    ),
                    discord.ui.ActionRow(
                        discord.ui.Button(
                            label=str(count),
                            style=discord.ButtonStyle.secondary,
                            disabled=True,
                        ),
                        discord.ui.Button(
                            label="View our Dashboard",
                            style=discord.ButtonStyle.link,
                            url="https://discordapp.com/channels/1559284770440216639/1529141669340123257",
                        ),
                    ),
                ),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send a welcome message")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Welcome(bot))
