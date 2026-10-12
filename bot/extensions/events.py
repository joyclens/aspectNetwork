from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord.ext import commands

from bot.core.bot import Aspect
from bot.services.dock import DockError, SessionCreated
from bot.services.roblox import RobloxError
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")


def _emoji_id(token: str) -> int | None:
    if not (token.startswith("<") and token.endswith(">") and token.count(":") == 2):
        return None
    raw = token[1:-1].rsplit(":", 1)[-1]
    if not raw.isdigit() or int(raw) < 1:
        return None
    return int(raw)


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
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.TextDisplay(
                    "# Verification\n\n"
                    "Verification in **Aspect Network** is *essential* to gain **full access** "
                    "to the server and its features.\n\n"
                    "**Getting Started:**\n"
                    "- Simply click the **Verify** button below.\n"
                    "- Carefully *follow the steps* provided."
                ),
                discord.ui.ActionRow(VerifyButton()),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6ace0720&is=6accb5a0&hm=4c4fffa70183ac88e939beabc0dccd963d97cb1f11463d2e77c7a759a2b49567&"
                    )
                ),
            )
        )


class _Continue(discord.ui.Button[Any]):
    def __init__(self, roblox_id: int, username: str, emoji: str) -> None:
        super().__init__(
            label="Continue",
            style=discord.ButtonStyle.secondary,
            custom_id=f"verifyContinue:{roblox_id}",
        )
        self.roblox_id = roblox_id
        self.username = username
        self.headshot = emoji

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        client = interaction.client
        cog = client.get_cog("Events") if isinstance(client, Aspect) else None
        if isinstance(cog, Events):
            await cog.confirm(interaction, self.roblox_id, self.username, self.headshot)


class Events(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._posted = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._emoji_tasks: dict[int, asyncio.Task[None]] = {}

    async def cog_load(self) -> None:
        self.bot.add_view(VerificationPanel())

    async def cog_unload(self) -> None:
        for task in self._tasks:
            task.cancel()
        pending = list(self._emoji_tasks)
        for task in self._emoji_tasks.values():
            task.cancel()
        for emoji_id in pending:
            await self._delete_emoji(emoji_id)

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
        if dock is None or self.bot.roblox is None or interaction.guild_id is None:
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Verification is not ready.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            linked = await dock.linked_roblox(interaction.user.id, interaction.guild_id)
        except DockError as exc:
            logger.warning("Dock lookup failed status=%s", exc.status)
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("Verification could not be started.")),
                ephemeral=True,
            )
            return
        if linked is not None:
            await self._already(interaction, int(linked))
            return
        try:
            session = await dock.create_session(str(interaction.user.id), interaction.guild_id)
        except DockError as exc:
            logger.warning("Dock session failed status=%s", exc.status)
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("Verification could not be started.")),
                ephemeral=True,
            )
            return
        message = await interaction.followup.send(
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
            wait=True,
        )
        member = interaction.user
        if isinstance(member, discord.Member) and isinstance(message, discord.WebhookMessage):
            task = asyncio.create_task(self._watch(member, session, message))
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

    async def _already(self, interaction: discord.Interaction[Any], roblox_id: int) -> None:
        try:
            username, emoji = await self._portrait(roblox_id)
        except RobloxError as exc:
            logger.warning("Roblox profile failed status=%s", exc.status)
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("Verification could not be started.")),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=self._known_view(username, roblox_id, emoji),
            ephemeral=True,
        )

    async def confirm(
        self,
        interaction: discord.Interaction[Any],
        roblox_id: int,
        username: str,
        emoji: str,
    ) -> None:
        if interaction.guild_id != self.bot.settings.discord_guild_id:
            return
        emoji_id = _emoji_id(emoji)
        if emoji_id is not None:
            self._keep_emoji(emoji_id)
        view = self._success_view(username, roblox_id, emoji)
        try:
            await interaction.response.edit_message(view=view)
        except discord.HTTPException:
            logger.warning("Could not show verification success")
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(view=view, ephemeral=True)
                except discord.HTTPException:
                    logger.warning("Could not show verification success")
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        guild = interaction.guild
        if member is None and guild is not None:
            member = guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    logger.warning("Could not find the member to verify")
                    return
        if member is not None:
            await self._grant(member)

    async def _watch(
        self,
        member: discord.Member,
        session: SessionCreated,
        message: discord.WebhookMessage,
    ) -> None:
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
            if result is not None and result.roblox_id and result.roblox_id.isdigit():
                if result.discord_id not in {None, str(member.id)}:
                    logger.warning("Dock session finished for a different Discord user")
                    return
                await self._show_success(message, int(result.roblox_id))
                await self._grant(member)
                return
            if state.status in {"expired", "cancelled"}:
                return
        logger.info("Dock session ended before completion")

    async def _show_success(self, message: discord.WebhookMessage, roblox_id: int) -> None:
        try:
            username, emoji = await self._portrait(roblox_id)
        except RobloxError as exc:
            logger.warning("Roblox profile failed status=%s", exc.status)
            return
        try:
            await message.edit(view=self._success_view(username, roblox_id, emoji))
        except discord.HTTPException:
            logger.warning("Could not show verification success")

    async def _portrait(self, roblox_id: int) -> tuple[str, str]:
        roblox = self.bot.roblox
        if roblox is None:
            raise RobloxError(0)
        username, image = await roblox.account(roblox_id)
        name = f"headshot_{roblox_id}"
        if len(name) > 32:
            return username, ""
        try:
            found = discord.utils.get(await self.bot.fetch_application_emojis(), name=name)
            emoji = found or await self.bot.create_application_emoji(name=name, image=image)
        except discord.HTTPException:
            logger.warning("Could not create headshot emoji")
            return username, ""
        self._keep_emoji(emoji.id)
        return username, str(emoji)

    def _keep_emoji(self, emoji_id: int) -> None:
        previous = self._emoji_tasks.pop(emoji_id, None)
        if previous is not None:
            previous.cancel()
        task = asyncio.create_task(self._expire_emoji(emoji_id))
        self._emoji_tasks[emoji_id] = task

    async def _expire_emoji(self, emoji_id: int) -> None:
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            return
        self._emoji_tasks.pop(emoji_id, None)
        await self._delete_emoji(emoji_id)

    async def _delete_emoji(self, emoji_id: int) -> None:
        try:
            emoji = await self.bot.fetch_application_emoji(emoji_id)
            await emoji.delete()
        except discord.HTTPException as exc:
            if exc.status != 404:
                logger.warning("Could not delete temporary emoji")

    def _known_view(self, username: str, roblox_id: int, emoji: str) -> discord.ui.LayoutView:
        profile = f"https://www.roblox.com/users/{roblox_id}/profile"
        shot = f" {emoji}" if emoji else ""
        view = discord.ui.LayoutView(timeout=300)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "## You're already verified!\n"
                    f"We have you verified as [**{username}**]({profile}){shot}\n\n"
                    "-# To switch to a different account, click **Change Account**.\n"
                    "-# To continue using your current account, click **Continue**.\n\n"
                ),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
                discord.ui.ActionRow(
                    _Continue(roblox_id, username, emoji),
                    discord.ui.Button(
                        label="Change Account",
                        style=discord.ButtonStyle.link,
                        url="https://api.docksys.xyz/v1/api/verify/discord",
                    ),
                ),
            )
        )
        return view

    def _success_view(self, username: str, roblox_id: int, emoji: str) -> discord.ui.LayoutView:
        profile = f"https://www.roblox.com/users/{roblox_id}/profile"
        shot = f" {emoji}" if emoji else ""
        view = discord.ui.LayoutView()
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"{self.bot.settings.emojis.approve} **Verification Successful!**\n"
                    "-# You have been successfully verified under "
                    f"[**{username}**]({profile}){shot}"
                ),
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6ace0720&is=6accb5a0&hm="
                        "4c4fffa70183ac88e939beabc0dccd963d97cb1f11463d2e77c7a759a2b49567&"
                    ),
                ),
            )
        )
        return view

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
