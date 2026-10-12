from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord.ext import commands

from bot.core.bot import Aspect
from bot.services.dock import DockError, SessionCreated
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")


class VerifyButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Begin Verification",
            style=discord.ButtonStyle.secondary,
            custom_id="verifyButton",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        client = interaction.client
        cog = client.get_cog("Events") if isinstance(client, Aspect) else None
        if isinstance(cog, Events):
            await cog.begin(interaction)


class VerificationPanel(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553891882378076281/verification.png"
                        "?ex=6ace03d6&is=6accb256&hm=37c7c948efa60bd8ccc9401a509bf036d3d97c76f2b18f0b5f4692d662baa37c&"
                    )
                ),
                discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
                discord.ui.TextDisplay(
                    "# Verification\n\n"
                    "Verification in **Aspect Network** is *essential* to gain **full access** "
                    "to the server and its features.\n\n"
                    "**Getting Started:**\n"
                    "- Simply click the **Verify** button below.\n"
                    "- Carefully *follow the steps* provided."
                ),
                discord.ui.ActionRow(VerifyButton()),
                discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6ace0720&is=6accb5a0&hm=4c4fffa70183ac88e939beabc0dccd963d97cb1f11463d2e77c7a759a2b49567&"
                    )
                ),
            )
        )


class Events(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._posted = False
        self._tasks: set[asyncio.Task[None]] = set()

    async def cog_load(self) -> None:
        self.bot.add_view(VerificationPanel())

    async def cog_unload(self) -> None:
        for task in self._tasks:
            task.cancel()

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
                        "**[marketplace](https://discordapp.com/channels/1529135675318866020/1529142741110358027)**"
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
                            url="https://discordapp.com/channels/1529135675318866020/1529141669340123257",
                        ),
                    ),
                ),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send a welcome message")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if guild.id == self.bot.settings.discord_guild_id:
            await self._panel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._posted or self.bot.user is None:
            return
        self._posted = True
        await self._panel()

    async def begin(self, interaction: discord.Interaction[Any]) -> None:
        if interaction.guild_id != self.bot.settings.discord_guild_id or interaction.user.bot:
            return
        dock = self.bot.dock
        if dock is None or interaction.guild_id is None:
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Verification is not ready.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            session = await dock.create_session(str(interaction.user.id), interaction.guild_id)
        except DockError as exc:
            logger.warning("Dock session failed status=%s", exc.status)
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("Verification could not be started.")),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(
                discord.ui.TextDisplay(
                    "# Verification\nFollow the steps to link your Roblox account."
                ),
                discord.ui.ActionRow(
                    discord.ui.Button(
                        label="Continue",
                        style=discord.ButtonStyle.link,
                        url=session.verify_url,
                    ),
                ),
            ),
            ephemeral=True,
        )
        member = interaction.user
        if isinstance(member, discord.Member):
            task = asyncio.create_task(self._watch(member, session))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _panel(self) -> None:
        channel = self.bot.get_channel(1530638348421566678)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(1530638348421566678)
            except discord.HTTPException:
                logger.warning("Verification channel is unavailable")
                return
        if not isinstance(channel, discord.TextChannel) or self.bot.user is None:
            logger.warning("Verification channel is unavailable")
            return
        try:
            async for message in channel.history(limit=30):
                if message.author.id == self.bot.user.id and message.flags.components_v2:
                    return
        except discord.HTTPException:
            logger.warning("Could not read the verification channel")
            return
        try:
            await channel.send(view=VerificationPanel())
        except discord.HTTPException:
            logger.warning("Could not send the verification panel")

    async def _watch(self, member: discord.Member, session: SessionCreated) -> None:
        dock = self.bot.dock
        if dock is None:
            return
        deadline = session.expires_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        deadline = min(deadline, datetime.now(UTC) + timedelta(minutes=30))
        while datetime.now(UTC) < deadline:
            try:
                state = await dock.session_state(session.sid)
            except DockError as exc:
                if exc.status == 429:
                    await asyncio.sleep(exc.retry_after if exc.retry_after is not None else 5)
                    continue
                logger.warning("Dock status failed status=%s", exc.status)
                return
            result = state.result
            if result is not None and result.roblox_id:
                if result.discord_id not in {None, str(member.id)}:
                    logger.warning("Dock session finished for a different Discord user")
                    return
                await self._grant(member)
                return
            if state.status in {"expired", "cancelled"}:
                return
        logger.info("Dock session ended before completion")

    async def _grant(self, member: discord.Member) -> None:
        role_id = self.bot.settings.verified_role_id
        if role_id is None:
            logger.info("Verification finished with no role configured")
            return
        role = member.guild.get_role(role_id)
        if role is None:
            logger.warning("Verified role is missing")
            return
        if role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Dock verification")
        except discord.HTTPException:
            logger.warning("Could not assign the verified role")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Events(bot))
