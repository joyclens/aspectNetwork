from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Channels, Guild
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Ctx = commands.Context[Any]
NO_MENTIONS = discord.AllowedMentions.none()
STACK_KEY = "invites:stack"
LEADERBOARD_SIZE = 25
LIST_LIMIT = 50


@dataclass(slots=True)
class CachedInvite:
    uses: int
    inviter_id: int | None
    max_uses: int


def _name(user: discord.abc.User | None, fallback: int) -> str:
    return discord.utils.escape_markdown(user.name) if user is not None else f"`{fallback}`"


class Invites(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._cache: dict[str, CachedInvite] = {}
        self._vanity_uses: int | None = None

    async def cog_load(self) -> None:
        if self.bot.is_ready():
            await self.refresh_cache()

    def guild(self) -> discord.Guild | None:
        return self.bot.get_guild(Guild.id)

    async def fetch_invites(self, guild: discord.Guild) -> dict[str, CachedInvite] | None:
        try:
            invites = await guild.invites()
        except discord.HTTPException:
            logger.warning("Could not fetch invites for %s", guild.id)
            return None
        return {
            invite.code: CachedInvite(
                uses=invite.uses or 0,
                inviter_id=invite.inviter.id if invite.inviter else None,
                max_uses=invite.max_uses or 0,
            )
            for invite in invites
        }

    async def fetch_vanity_uses(self, guild: discord.Guild) -> int | None:
        if guild.vanity_url_code is None:
            return None
        try:
            vanity = await guild.vanity_invite()
        except discord.HTTPException:
            return None
        return vanity.uses if vanity is not None else None

    async def refresh_cache(self) -> None:
        guild = self.guild()
        if guild is None:
            return
        invites = await self.fetch_invites(guild)
        if invites is not None:
            self._cache = invites
        self._vanity_uses = await self.fetch_vanity_uses(guild)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.refresh_cache()

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is None or invite.guild.id != Guild.id:
            return
        self._cache[invite.code] = CachedInvite(
            uses=invite.uses or 0,
            inviter_id=invite.inviter.id if invite.inviter else None,
            max_uses=invite.max_uses or 0,
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is None or invite.guild.id != Guild.id:
            return
        cached = self._cache.get(invite.code)
        if cached is None or not cached.max_uses or cached.uses + 1 < cached.max_uses:
            self._cache.pop(invite.code, None)

    async def resolve_join(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> tuple[int | None, str | None, str]:
        before = self._cache
        after = await self.fetch_invites(guild)
        vanity_before = self._vanity_uses
        vanity_after = await self.fetch_vanity_uses(guild)
        if after is not None:
            self._cache = after
        self._vanity_uses = vanity_after
        if member.bot:
            return None, None, "via OAuth"
        if after is not None:
            for code, invite in after.items():
                old = before.get(code)
                if old is not None and invite.uses > old.uses:
                    return invite.inviter_id, code, await self.invite_text(guild, invite)
            for code, old in before.items():
                if code not in after and old.max_uses and old.uses + 1 >= old.max_uses:
                    return old.inviter_id, code, await self.invite_text(guild, old)
        if vanity_after is not None and vanity_before is not None and vanity_after > vanity_before:
            return None, guild.vanity_url_code, "via the vanity URL"
        return None, None, "via an unknown invite"

    async def invite_text(self, guild: discord.Guild, invite: CachedInvite) -> str:
        if invite.inviter_id is None:
            return "via an invite"
        user: discord.abc.User | None = guild.get_member(invite.inviter_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(invite.inviter_id)
            except discord.HTTPException:
                user = None
        return f"via {_name(user, invite.inviter_id)}'s invite"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != Guild.id or self.bot.db is None:
            return
        inviter_id, code, how = await self.resolve_join(member.guild, member)
        logger.info("Member %s joined %s (code=%s)", member.id, how, code)
        count = await self.bot.db.record_invite_join(member.id, inviter_id, code, how)
        channel = member.guild.get_channel(Channels.invite_logs)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"**{_name(member, member.id)}** joined **{how}**",
                    allowed_mentions=NO_MENTIONS,
                )
            except discord.HTTPException:
                logger.warning("Could not send invite log for %s", member.id)
        if inviter_id is not None and count is not None:
            await self.apply_rewards(member.guild, inviter_id, count)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != Guild.id or self.bot.db is None:
            return
        left = await self.bot.db.record_invite_leave(member.id)
        if left is not None:
            await self.apply_rewards(member.guild, *left)

    async def stacking(self) -> bool:
        value = await database(self.bot).setting(STACK_KEY)
        return value is not False

    async def apply_rewards(self, guild: discord.Guild, user_id: int, count: int) -> None:
        member = guild.get_member(user_id)
        if member is None:
            return
        rewards = await database(self.bot).invite_rewards()
        if not rewards:
            return
        earned = [reward.role_id for reward in rewards if count >= reward.threshold]
        keep = set(earned) if await self.stacking() else set(earned[-1:])
        add = [
            role
            for role_id in keep
            if (role := guild.get_role(role_id)) is not None and member.get_role(role_id) is None
        ]
        remove = [
            role
            for reward in rewards
            if reward.role_id not in keep and (role := member.get_role(reward.role_id)) is not None
        ]
        try:
            if add:
                await member.add_roles(*add, reason="Invite reward")
            if remove:
                await member.remove_roles(*remove, reason="Invite reward updated")
        except discord.HTTPException:
            logger.warning("Could not update invite rewards for %s", user_id)

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="invites",
        aliases=("invitetracker", "invt", "it"),
        fallback="view",
        description="Show how many members someone has invited.",
    )
    @app_commands.describe(member="Member to check")
    @commands.guild_only()
    async def invites(self, ctx: Ctx, member: discord.Member | None = None) -> None:
        ctx = require_context(ctx)
        target = member or ctx.author
        count = await database(self.bot).invite_count(target.id)
        subject = "You have" if target.id == ctx.author.id else f"{target.mention} has"
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay(
                    f"{subject} **{count.regular} invites** ({count.left} left)."
                )
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @invites.command(  # type: ignore[arg-type]
        name="leaderboard",
        aliases=("lb",),
        description="Show the invite leaderboard.",
    )
    async def invites_leaderboard(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        rows = await database(self.bot).invite_leaderboard(LEADERBOARD_SIZE)
        if not rows:
            await ctx.warn("Nobody has invited anyone yet.")
            return
        lines = [
            f"`{index}.` <@{row.user_id}> - **{row.regular}** invites ({row.left} left)"
            for index, row in enumerate(rows, start=1)
        ]
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay("## Invite Leaderboard\n" + "\n".join(lines))
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @invites.command(  # type: ignore[arg-type]
        name="inviter",
        aliases=("invited-by",),
        description="Show who invited a member.",
    )
    @app_commands.describe(member="Member to check")
    async def invites_inviter(self, ctx: Ctx, member: discord.Member) -> None:
        ctx = require_context(ctx)
        join = await database(self.bot).invite_join(member.id)
        if join is None:
            await ctx.warn(f"{member.mention} has no recorded join.")
            return
        joined = discord.utils.format_dt(join.joined_at, "R")
        text = (
            f"{member.mention} was invited by <@{join.inviter_id}> {joined}."
            if join.inviter_id is not None
            else f"{member.mention} joined **{join.how}** {joined}."
        )
        await ctx.send(
            view=container_view(discord.ui.TextDisplay(text)),
            allowed_mentions=NO_MENTIONS,
        )

    @invites.command(  # type: ignore[arg-type]
        name="invited",
        description="List the members someone has invited.",
    )
    @app_commands.describe(member="Member to check")
    async def invites_invited(self, ctx: Ctx, member: discord.Member | None = None) -> None:
        ctx = require_context(ctx)
        target = member or ctx.author
        rows = await database(self.bot).invited_by(target.id)
        if not rows:
            await ctx.warn(f"{target.mention} hasn't invited anyone.")
            return
        lines = [
            f"<@{row.user_id}> {discord.utils.format_dt(row.joined_at, 'R')}"
            for row in rows[:LIST_LIMIT]
        ]
        if len(rows) > LIST_LIMIT:
            lines.append(f"-# and {len(rows) - LIST_LIMIT} more")
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay(
                    f"## Invited by {discord.utils.escape_markdown(target.name)} "
                    f"({len(rows)})\n" + "\n".join(lines)
                )
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @invites.command(  # type: ignore[arg-type]
        name="code",
        description="Show a member's invite codes.",
    )
    @app_commands.describe(member="Member to check")
    async def invites_code(self, ctx: Ctx, member: discord.Member | None = None) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        target = member or ctx.author
        try:
            invites = await ctx.guild.invites()
        except discord.HTTPException:
            await ctx.warn("I could not fetch the server's invites.")
            return
        owned = [invite for invite in invites if invite.inviter and invite.inviter.id == target.id]
        if not owned:
            await ctx.warn(f"{target.mention} has not created any invites.")
            return
        lines = [f"**{invite.code}** - {invite.uses or 0} uses" for invite in owned[:LIST_LIMIT]]
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay(
                    f"## {discord.utils.escape_markdown(target.name)}'s Invite Codes\n"
                    + "\n".join(lines)
                )
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @invites.group(  # type: ignore[arg-type]
        name="rewards",
        fallback="list",
        description="List the invite role rewards.",
    )
    async def invites_rewards(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        rewards = await database(self.bot).invite_rewards()
        if not rewards:
            await ctx.warn("No role rewards have been set.")
            return
        stack = "on" if await self.stacking() else "off"
        lines = [f"**{reward.threshold}** invites - <@&{reward.role_id}>" for reward in rewards]
        await ctx.send(
            view=container_view(
                discord.ui.TextDisplay(
                    f"## Role Rewards ({len(rewards)})\n"
                    + "\n".join(lines)
                    + f"\n-# Stacking: {stack}"
                )
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @invites_rewards.command(  # type: ignore[arg-type]
        name="add",
        description="Add a role reward for an invite count.",
    )
    @app_commands.describe(threshold="Invites needed", role="Role to give")
    @commands.has_permissions(manage_guild=True)
    async def invites_rewards_add(self, ctx: Ctx, threshold: int, role: discord.Role) -> None:
        ctx = require_context(ctx)
        if threshold < 1:
            await ctx.warn("The threshold must be at least 1.")
            return
        if role.is_default() or role.managed:
            await ctx.warn("That role cannot be given as a reward.")
            return
        if not await database(self.bot).add_invite_reward(threshold, role.id):
            await ctx.warn(f"A reward for **{threshold} invites** already exists.")
            return
        await ctx.approve(f"{role.mention} will be given at **{threshold} invites**.")

    @invites_rewards.command(  # type: ignore[arg-type]
        name="remove",
        description="Remove the role reward for an invite count.",
    )
    @app_commands.describe(threshold="Invite count of the reward to remove")
    @commands.has_permissions(manage_guild=True)
    async def invites_rewards_remove(self, ctx: Ctx, threshold: int) -> None:
        ctx = require_context(ctx)
        if not await database(self.bot).remove_invite_reward(threshold):
            await ctx.warn("That role reward does not exist.")
            return
        await ctx.approve(f"Removed the reward for **{threshold} invites**.")

    @invites_rewards.command(  # type: ignore[arg-type]
        name="stack",
        description="Keep every earned reward role, or only the highest one.",
    )
    @app_commands.describe(option="on keeps every earned role, off keeps only the highest")
    @commands.has_permissions(manage_guild=True)
    async def invites_rewards_stack(self, ctx: Ctx, option: str) -> None:
        ctx = require_context(ctx)
        choice = option.lower()
        if choice not in {"on", "off"}:
            await ctx.warn("Valid options are `on` and `off`.")
            return
        await database(self.bot).store_setting(STACK_KEY, choice == "on")
        await ctx.approve(
            "Members now keep every reward role they earn."
            if choice == "on"
            else "Members now keep only their highest reward role."
        )

    @invites_rewards.command(  # type: ignore[arg-type]
        name="sync",
        description="Sync reward roles with current invite counts.",
    )
    @commands.has_permissions(manage_guild=True)
    async def invites_rewards_sync(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return
        if not await database(self.bot).invite_rewards():
            await ctx.warn("No role rewards have been set.")
            return
        async with ctx.typing():
            for row in await database(self.bot).invite_counts():
                await self.apply_rewards(ctx.guild, row.user_id, row.regular)
        await ctx.approve("Role rewards have been synced with current invites.")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Invites(bot))
