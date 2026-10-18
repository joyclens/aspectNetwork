from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Channels, Emojis, Guild, Roles
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")


class Welcome(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or member.guild.id != Guild.id:
            return
        unverified = member.guild.get_role(Roles.unverified)
        if unverified is not None and unverified not in member.roles:
            try:
                await member.add_roles(unverified, reason="Joined")
            except discord.HTTPException:
                logger.warning("Could not grant Unverified to %s", member.id)
        channel = self.bot.get_channel(Channels.welcome)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(Channels.welcome)
            except discord.HTTPException:
                logger.warning("Welcome channel is unavailable")
                return
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Welcome channel is unavailable")
            return
        count = member.guild.member_count or len(member.guild.members)
        marketplace = f"https://discordapp.com/channels/{Guild.id}/{Channels.marketplace}"
        dashboard = f"https://discordapp.com/channels/{Guild.id}/{Channels.dashboard}"
        try:
            await channel.send(
                view=container_view(
                    discord.ui.TextDisplay(
                        f"{Emojis.affiliate} "
                        f"Welcome <@{member.id}> to **Aspect Network**! "
                        "We are pleased to have you join our journey "
                        "to become *Your Ideal Connection*.\n"
                        "-# And don't forget to check out our "
                        f"**[marketplace]({marketplace})**"
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
                            url=dashboard,
                        ),
                    ),
                ),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send a welcome message")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Welcome(bot))
