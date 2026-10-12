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
from bot.shared.errors import remember_error, report_interaction
from bot.shared.layout import AspectLayout, container_view

logger = logging.getLogger("aspect")


def _emoji_id(token: str) -> int | None:
    if not (token.startswith("<") and token.endswith(">") and token.count(":") == 2):
        return None
    raw = token[1:-1].rsplit(":", 1)[-1]
    if not raw.isdigit() or int(raw) < 1:
        return None
    return int(raw)


def _has_id(components: list[Any], custom_id: str) -> bool:
    for component in components:
        if getattr(component, "custom_id", None) == custom_id:
            return True
        children = getattr(component, "children", None)
        if isinstance(children, list) and _has_id(children, custom_id):
            return True
    return False


class VerifyButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Begin Verification",
            style=discord.ButtonStyle.secondary,
            custom_id="verifyButton",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        client = interaction.client
        cog = client.get_cog("Verification") if isinstance(client, Aspect) else None
        if isinstance(cog, Verification):
            await cog.begin(interaction)


class VerificationPanel(AspectLayout):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553891882378076281/verification.png"
                        "?ex=6ace03d6&is=6accb256&hm="
                        "37c7c948efa60bd8ccc9401a509bf036d3d97c76f2b18f0b5f4692d662baa37c&"
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
        cog = client.get_cog("Verification") if isinstance(client, Aspect) else None
        if isinstance(cog, Verification):
            await cog.confirm(interaction, self.roblox_id, self.username, self.headshot)


class Verification(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._panel_id: int | None = None
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
    async def on_ready(self) -> None:
        if self.bot.user is None:
            return
        await self._panel()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if guild.id == self.bot.settings.discord_guild_id:
            await self._panel()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.channel_id != 1559306245901389907 or payload.message_id != self._panel_id:
            return
        self._panel_id = None
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
        linked = await dock.linked_roblox(interaction.user.id, interaction.guild_id)
        if linked is not None:
            await self._already(interaction, int(linked))
            return
        session = await dock.create_session(str(interaction.user.id), interaction.guild_id)
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
            self._track(asyncio.create_task(self._watch(member, session, message)))

    async def _panel(self) -> None:
        async with self.bot.lock_for("verification-panel"):
            channel = self.bot.get_channel(1559306245901389907)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(1559306245901389907)
                except discord.HTTPException:
                    logger.warning("Verification channel is unavailable")
                    return
            if not isinstance(channel, discord.TextChannel) or self.bot.user is None:
                logger.warning("Verification channel is unavailable")
                return
            if await self._panel_exists(channel):
                return
            try:
                message = await channel.send(view=VerificationPanel())
            except discord.HTTPException:
                logger.warning("Could not send the verification panel")
                return
            self._panel_id = message.id

    async def _panel_exists(self, channel: discord.TextChannel) -> bool:
        if self._panel_id is not None:
            try:
                await channel.fetch_message(self._panel_id)
            except discord.NotFound:
                self._panel_id = None
            except discord.HTTPException:
                logger.warning("Could not read the verification channel")
                return True
            else:
                return True
        user = self.bot.user
        if user is None:
            return True
        found: list[discord.Message] = []
        seen: set[int] = set()
        try:
            found.extend(await channel.pins())
            seen.update(message.id for message in found)
            async for message in channel.history(limit=100):
                if message.id not in seen:
                    seen.add(message.id)
                    found.append(message)
        except discord.HTTPException:
            logger.warning("Could not read the verification channel")
            return True
        for message in found:
            if message.author.id == user.id and _has_id(list(message.components), "verifyButton"):
                self._panel_id = message.id
                return True
        return False

    def _track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            remember_error(self.bot.traceback, error, where="Verification")

    async def _already(self, interaction: discord.Interaction[Any], roblox_id: int) -> None:
        username, emoji = await self._portrait(roblox_id)
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
        except discord.HTTPException as exc:
            await report_interaction(interaction, exc, where="Button verifyContinue")
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        guild = interaction.guild
        if member is None and guild is not None:
            member = guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.HTTPException as exc:
                    remember_error(self.bot.traceback, exc, where="Button verifyContinue")
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
                remember_error(self.bot.traceback, exc, where="Verification")
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
            remember_error(self.bot.traceback, exc, where="Verification")
            return
        try:
            await message.edit(view=self._success_view(username, roblox_id, emoji))
        except discord.HTTPException as exc:
            remember_error(self.bot.traceback, exc, where="Verification")

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
        except discord.HTTPException as exc:
            remember_error(self.bot.traceback, exc, where="Button verifyButton")
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
                remember_error(self.bot.traceback, exc, where="Verification")

    def _known_view(self, username: str, roblox_id: int, emoji: str) -> discord.ui.LayoutView:
        profile = f"https://www.roblox.com/users/{roblox_id}/profile"
        shot = f" {emoji}" if emoji else ""
        view = AspectLayout(timeout=300)
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
        view = AspectLayout()
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
        except discord.HTTPException as exc:
            remember_error(self.bot.traceback, exc, where="Verification role")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Verification(bot))
