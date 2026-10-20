from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.database import GuildTag
from bot.core.ids import Guild
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Ctx = commands.Context[Any]
MAX_ROLES = 10
MAX_MESSAGE = 2000
NO_MENTIONS = discord.AllowedMentions.none()
USER_MENTIONS = discord.AllowedMentions(users=True)


def primary_id(member: discord.Member) -> int | None:
    guild = member.primary_guild
    return guild.id if guild is not None else None


def format_alert(template: str, member: discord.Member) -> str:
    return (
        template.replace("{user.mention}", member.mention)
        .replace("{user.name}", member.display_name)
        .replace("{user.id}", str(member.id))
        .replace("{guild.name}", member.guild.name)
    )


class GuildTags(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="guildtag",
        aliases=("gt",),
        fallback="config",
        description="Show this server's guild tag reward settings.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def guildtag(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        row = await database(self.bot).guild_tag(ctx.guild.id)
        if row is None:
            await ctx.warn("Guild tag is not configured yet.")
            return
        roles = " ".join(f"<@&{role_id}>" for role_id in row.role_ids) or "none"
        channel = f"<#{row.channel_id}>" if row.channel_id is not None else "none"
        message = row.message or "none"
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay(
                    "## Guild tag\n"
                    f"**Enabled:** `{'yes' if row.enabled else 'no'}`\n"
                    f"**Channel:** {channel}\n"
                    f"**Roles:** {roles}\n"
                    f"**Message:**\n```{message[:500]}```"
                )
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @guildtag.command(  # type: ignore[arg-type]
        name="enable",
        description="Enable guild tag role rewards for this server.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_enable(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        db = database(self.bot)
        row = await db.guild_tag(ctx.guild.id)
        if row is not None and row.enabled:
            await ctx.warn("Guild tag is already enabled.")
            return
        await db.set_guild_tag_enabled(ctx.guild.id, True)
        await ctx.approve("Guild tag has been enabled.")

    @guildtag.command(  # type: ignore[arg-type]
        name="disable",
        description="Disable guild tag role rewards for this server.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_disable(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        db = database(self.bot)
        row = await db.guild_tag(ctx.guild.id)
        if row is None or not row.enabled:
            await ctx.warn("Guild tag is not enabled.")
            return
        await db.set_guild_tag_enabled(ctx.guild.id, False)
        await ctx.approve("Guild tag has been disabled.")

    @guildtag.command(  # type: ignore[arg-type]
        name="message",
        description="Set the alert text sent when someone equips the guild tag.",
    )
    @app_commands.describe(
        message="Alert text; supports {user.mention}, {user.name}, {user.id}, {guild.name}",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_message(self, ctx: Ctx, *, message: str) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None:
            return
        text = message.strip()
        if not text or len(text) > MAX_MESSAGE:
            await ctx.warn("That message is not valid.")
            return
        await database(self.bot).set_guild_tag_message(row.guild_id, text)
        await ctx.approve("Guild tag message updated.")

    @guildtag.group(  # type: ignore[arg-type]
        name="role",
        description="Manage roles granted when members equip the guild tag.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_role(self, ctx: Ctx) -> None:
        await require_context(ctx).warn("Use `add`, `remove`, or `list`.")

    @guildtag_role.command(  # type: ignore[arg-type]
        name="add",
        description="Add a role granted when members equip the guild tag.",
    )
    @app_commands.describe(role="Role to grant for the guild tag")
    @commands.has_permissions(manage_guild=True)
    async def guildtag_role_add(self, ctx: Ctx, role: discord.Role) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None:
            return
        if role.id in row.role_ids:
            await ctx.warn("That role is already a guild tag reward.")
            return
        if len(row.role_ids) >= MAX_ROLES:
            await ctx.warn(f"You can only set up to {MAX_ROLES} reward roles.")
            return
        await database(self.bot).set_guild_tag_roles(row.guild_id, [*row.role_ids, role.id])
        await ctx.approve(f"Added {role.mention} as a guild tag reward.")

    @guildtag_role.command(  # type: ignore[arg-type]
        name="remove",
        description="Remove a role from guild tag rewards.",
    )
    @app_commands.describe(role="Role to stop granting for the guild tag")
    @commands.has_permissions(manage_guild=True)
    async def guildtag_role_remove(self, ctx: Ctx, role: discord.Role) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None:
            return
        if role.id not in row.role_ids:
            await ctx.warn("That role is not a guild tag reward.")
            return
        await database(self.bot).set_guild_tag_roles(
            row.guild_id,
            [role_id for role_id in row.role_ids if role_id != role.id],
        )
        await ctx.approve(f"Removed {role.mention} from guild tag rewards.")

    @guildtag_role.command(  # type: ignore[arg-type]
        name="list",
        description="List roles granted when members equip the guild tag.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_role_list(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None:
            return
        if not row.role_ids:
            await ctx.warn("No guild tag reward roles are set.")
            return
        roles = "\n".join(f"<@&{role_id}>" for role_id in row.role_ids)
        await ctx.send(
            view=container_view(discord.ui.TextDisplay(f"## Guild tag roles\n{roles}")),
            allowed_mentions=NO_MENTIONS,
        )

    @guildtag.group(  # type: ignore[arg-type]
        name="channel",
        description="Manage the channel used for guild tag alerts.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_channel(self, ctx: Ctx) -> None:
        await require_context(ctx).warn("Use `set` or `remove`.")

    @guildtag_channel.command(  # type: ignore[arg-type]
        name="set",
        description="Set the channel that receives guild tag alerts.",
    )
    @app_commands.describe(channel="Text channel for guild tag alerts")
    @commands.has_permissions(manage_guild=True)
    async def guildtag_channel_set(self, ctx: Ctx, channel: discord.TextChannel) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None or ctx.guild is None:
            return
        if channel.guild.id != ctx.guild.id:
            await ctx.warn("That channel is not in this server.")
            return
        await database(self.bot).set_guild_tag_channel(row.guild_id, channel.id)
        await ctx.approve(f"Guild tag alerts will post in {channel.mention}.")

    @guildtag_channel.command(  # type: ignore[arg-type]
        name="remove",
        description="Clear the guild tag alert channel.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_channel_remove(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None:
            return
        if row.channel_id is None:
            await ctx.warn("No guild tag alert channel is set.")
            return
        await database(self.bot).set_guild_tag_channel(row.guild_id, None)
        await ctx.approve("Guild tag alert channel removed.")

    @guildtag.command(  # type: ignore[arg-type]
        name="list",
        description="List members currently showing this server's guild tag.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_list(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        members = [
            member.mention
            for member in ctx.guild.members
            if not member.bot and primary_id(member) == ctx.guild.id
        ]
        if not members:
            await ctx.warn("No members are currently showing this guild tag.")
            return
        body = "\n".join(members[:100])
        if len(members) > 100:
            body += f"\n…and {len(members) - 100} more"
        await ctx.send(
            view=container_view(discord.ui.TextDisplay(f"## Guild tag members\n{body}")),
            allowed_mentions=NO_MENTIONS,
        )

    @guildtag.command(  # type: ignore[arg-type]
        name="sync",
        description="Grant reward roles to everyone currently showing the guild tag.",
    )
    @commands.has_permissions(manage_guild=True)
    async def guildtag_sync(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        row = await self._require_enabled(ctx)
        if row is None or ctx.guild is None:
            return
        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer()
        roles = self._roles(ctx.guild, row.role_ids)
        if not roles:
            await ctx.warn("No valid guild tag reward roles are set.")
            return
        synced = 0
        failed = 0
        for member in ctx.guild.members:
            if member.bot or primary_id(member) != ctx.guild.id:
                continue
            missing = [role for role in roles if role not in member.roles]
            if not missing:
                continue
            try:
                await member.add_roles(*missing, reason="Guild tag sync")
                synced += 1
            except discord.HTTPException:
                failed += 1
        if failed:
            await ctx.warn(f"Synced {synced} members; {failed} failed.")
            return
        await ctx.approve(f"Synced guild tag roles for {synced} members.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild.id != Guild.id or after.bot:
            return
        before_id = primary_id(before)
        after_id = primary_id(after)
        if before_id == after_id:
            return
        if self.bot.db is None:
            return
        row = await self.bot.db.guild_tag(after.guild.id)
        if row is None or not row.enabled or not row.role_ids:
            return
        roles = self._roles(after.guild, row.role_ids)
        if not roles:
            return
        guild_id = after.guild.id
        if before_id == guild_id and after_id != guild_id:
            await self._remove_roles(after, roles)
            return
        if before_id != guild_id and after_id == guild_id:
            await self._add_roles(after, roles)
            await self._alert(after, row)

    async def _require_enabled(self, ctx: Ctx) -> GuildTag | None:
        reply = require_context(ctx)
        if reply.guild is None:
            return None
        row = await database(self.bot).guild_tag(reply.guild.id)
        if row is None or not row.enabled:
            await reply.warn("Guild tag is not enabled. Use `guildtag enable` first.")
            return None
        return row

    def _roles(self, guild: discord.Guild, role_ids: list[int]) -> list[discord.Role]:
        roles: list[discord.Role] = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                roles.append(role)
        return roles

    async def _add_roles(self, member: discord.Member, roles: list[discord.Role]) -> None:
        missing = [role for role in roles if role not in member.roles]
        if not missing:
            return
        try:
            await member.add_roles(*missing, reason="Guild tag equipped")
        except discord.HTTPException:
            logger.warning("Could not grant guild tag roles to %s", member.id)

    async def _remove_roles(self, member: discord.Member, roles: list[discord.Role]) -> None:
        present = [role for role in roles if role in member.roles]
        if not present:
            return
        try:
            await member.remove_roles(*present, reason="Guild tag removed")
        except discord.HTTPException:
            logger.warning("Could not remove guild tag roles from %s", member.id)

    async def _alert(self, member: discord.Member, row: GuildTag) -> None:
        if row.channel_id is None or not row.message.strip():
            return
        channel = member.guild.get_channel(row.channel_id)
        if not isinstance(channel, discord.TextChannel):
            try:
                fetched = await self.bot.fetch_channel(row.channel_id)
            except discord.HTTPException:
                logger.warning("Guild tag alert channel %s is unavailable", row.channel_id)
                return
            if not isinstance(fetched, discord.TextChannel):
                return
            channel = fetched
        text = format_alert(row.message, member)
        try:
            await channel.send(
                view=container_view(discord.ui.TextDisplay(text)),
                allowed_mentions=USER_MENTIONS,
            )
        except discord.HTTPException:
            logger.warning("Could not send guild tag alert for %s", member.id)


async def setup(bot: Aspect) -> None:
    await bot.add_cog(GuildTags(bot))
