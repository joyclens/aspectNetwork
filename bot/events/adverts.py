from __future__ import annotations

import logging
import re
from typing import Final

import discord
from discord import ui
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Channels, Guild
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

FOOTER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png?ex=6ad54760&is=6ad3f5e0&hm=a620cfc6a45f8943e51320363b156c32491524ee8f70116a5cc52fa43faa96c3&"

INVITE_RE = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([a-z0-9-]+)"
)

AdvertBucket = tuple[int, int | None, int]

ADVERT_BUCKETS: Final[tuple[AdvertBucket, ...]] = (
    (1, 199, Channels.advertise_1_199),
    (200, 299, Channels.advertise_200_299),
    (300, 499, Channels.advertise_300_499),
    (500, 999, Channels.advertise_500_999),
    (1000, 1999, Channels.advertise_1000_1999),
    (2000, None, Channels.advertise_2000_plus),
)

ADVERT_CHANNELS: Final[frozenset[int]] = frozenset(
    channel_id for _, _, channel_id in ADVERT_BUCKETS
)


def invite_code(content: str) -> str | None:
    match = INVITE_RE.search(content)
    return match.group(1) if match is not None else None


def channel_for_members(count: int) -> int | None:
    for low, high, channel_id in ADVERT_BUCKETS:
        if count < low:
            return None
        if high is None or count <= high:
            return channel_id
    return None


def notice(text: str) -> discord.ui.LayoutView:
    return container_view(
        ui.TextDisplay(text),
        ui.Separator(visible=True),
        ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
    )


class Adverts(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != Guild.id:
            return
        if message.author.bot or message.webhook_id is not None:
            return
        if message.channel.id not in ADVERT_CHANNELS:
            return

        channel = message.channel
        if not isinstance(channel, discord.TextChannel):
            return

        code = invite_code(message.content)
        if code is None:
            await self._reject(
                message,
                notice(
                    f"Your message in {channel.mention} was deleted as your "
                    "**server invite is invalid**, please make sure you're posting a valid server."
                ),
            )
            return

        try:
            invite = await self.bot.fetch_invite(code, with_counts=True)
        except discord.HTTPException:
            await self._reject(
                message,
                notice(
                    f"Your message in {channel.mention} was deleted as your "
                    "**server invite is invalid**, please make sure you're posting a valid server."
                ),
            )
            return

        count = invite.approximate_member_count
        guild = invite.guild
        name = guild.name if isinstance(guild, discord.Guild | discord.PartialInviteGuild) else None
        if count is None or count < 1 or name is None:
            await self._reject(
                message,
                notice(
                    f"Your message in {channel.mention} was deleted as your "
                    "**server invite is invalid**, please make sure you're posting a valid server."
                ),
            )
            return

        allowed_id = channel_for_members(count)
        if allowed_id is None:
            await self._reject(
                message,
                notice(
                    f"Your message in {channel.mention} was deleted as your "
                    "**server invite is invalid**, please make sure you're posting a valid server."
                ),
            )
            return

        if channel.id == allowed_id:
            return

        await self._reject(
            message,
            notice(
                f"Your message in {channel.mention} was deleted as your "
                "**server membercount doesn't meet the criteria for that channel**, "
                f"your server [`{name}`] can be posted in <#{allowed_id}>"
            ),
        )

    async def _reject(self, message: discord.Message, view: discord.ui.LayoutView) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            logger.warning("Could not delete advert message %s", message.id)
            return
        try:
            await message.author.send(view=view)
        except discord.HTTPException:
            logger.info("Could not DM advert author %s", message.author.id)


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Adverts(bot))
