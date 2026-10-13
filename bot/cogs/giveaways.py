from __future__ import annotations

import logging
import random
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from bot.core.bot import Aspect
from bot.core.database import Giveaway
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.converters import Duration
from bot.shared.errors import DatabaseUnavailable, report_interaction
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

EMBED_COLOR = 0xFF3171
MAX_ACTIVE = 5
MAX_ROLE_REQS = 5
MAX_SERVER_REQS = 3
_FLAG = re.compile(r"(--(?:role|bonus|ignore|server))\s+(.+?)(?=\s--|\s*$)", re.I)
_ROLE_COLUMNS = {
    "role": "required_roles",
    "bonus": "bonus_roles",
    "ignore": "ignore_roles",
}
_FIELD_NAMES = {
    "role": "Role",
    "bonus": "Bonus",
    "ignore": "Ignore",
    "server": "Server",
}


def unique_members(members: list[int]) -> list[int]:
    return list(dict.fromkeys(members))


def role_mentions(role_ids: list[int]) -> str:
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def server_labels(bot: Aspect, server_ids: list[int]) -> str:
    labels: list[str] = []
    for server_id in server_ids:
        guild = bot.get_guild(server_id)
        labels.append(guild.name if guild else f"`{server_id}`")
    return ", ".join(labels)


def giveaway_description(finish: datetime, host: str, winners: int | str) -> str:
    stamp = int(finish.timestamp())
    return f"**Ends:** <t:{stamp}> (<t:{stamp}:R>)\n**Hosted by:** {host}\n**Winners:** {winners}"


def build_embed(
    bot: Aspect,
    *,
    title: str,
    finish: datetime,
    host: str,
    winners: int | str,
    entries: int,
    required_roles: list[int] | None = None,
    bonus_roles: list[int] | None = None,
    ignore_roles: list[int] | None = None,
    required_servers: list[int] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        color=EMBED_COLOR,
        title=title,
        description=giveaway_description(finish, host, winners),
    )
    embed.add_field(name="Entries", value=str(entries))
    if bonus_roles:
        embed.add_field(name="Bonus", value=role_mentions(bonus_roles))
    if required_roles:
        embed.add_field(name="Role", value=role_mentions(required_roles))
    if required_servers:
        embed.add_field(name="Server", value=server_labels(bot, required_servers))
    if ignore_roles:
        embed.add_field(name="Ignore", value=role_mentions(ignore_roles))
    return embed


def set_or_add_field(embed: discord.Embed, name: str, value: str) -> None:
    for index, field in enumerate(embed.fields):
        if field.name and field.name.lower() == name.lower():
            embed.set_field_at(index, name=name, value=value, inline=True)
            return
    embed.add_field(name=name, value=value, inline=True)


def remove_field(embed: discord.Embed, name: str) -> None:
    for index, field in enumerate(embed.fields):
        if field.name and field.name.lower() == name.lower():
            embed.remove_field(index)
            return


def parse_flags(prize: str) -> tuple[str, dict[str, str]]:
    flags: dict[str, str] = {}
    cleaned = prize
    for match in _FLAG.finditer(prize):
        flags[match.group(1).lower()] = match.group(2).strip()
        cleaned = cleaned.replace(match.group(0), "")
    return " ".join(cleaned.split()), flags


async def parse_roles(ctx: commands.Context[Any], raw: str) -> list[discord.Role]:
    converter = commands.RoleConverter()
    roles: list[discord.Role] = []
    for token in raw.split():
        roles.append(await converter.convert(ctx, token))
    return roles


def parse_server_ids(raw: str) -> list[int] | None:
    values: list[int] = []
    for token in raw.split():
        if not token.isdigit():
            return None
        values.append(int(token))
    return values


async def end_giveaway(bot: Aspect, row: Giveaway) -> None:
    db = database(bot)
    guild = bot.get_guild(row.guild_id)
    if guild is None:
        await db.store_ended_giveaway(row.channel_id, row.message_id, row.members)
        return
    channel = guild.get_channel(row.channel_id)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await guild.fetch_channel(row.channel_id)
        except discord.HTTPException:
            await db.store_ended_giveaway(row.channel_id, row.message_id, row.members)
            return
        if not isinstance(fetched, discord.TextChannel):
            await db.store_ended_giveaway(row.channel_id, row.message_id, row.members)
            return
        channel = fetched
    try:
        message = await channel.fetch_message(row.message_id)
    except discord.HTTPException:
        await db.store_ended_giveaway(row.channel_id, row.message_id, row.members)
        return
    members = row.members
    stamp = int(datetime.now(UTC).timestamp())
    pool = unique_members(members)
    if len(pool) < row.winners:
        wins: list[int] = []
        winners_text = f"{row.winners}\n\n> Not enough entries to determine the winners!"
    else:
        wins = random.sample(members, row.winners)
        winners_text = ", ".join(f"<@{user_id}>" for user_id in wins)
    title = message.embeds[0].title if message.embeds else row.title
    embed = discord.Embed(color=EMBED_COLOR, title=title or row.title)
    embed.description = (
        f"**Ended:** <t:{stamp}> (<t:{stamp}:R>)\n"
        f"**Hosted by:** <@!{row.host_id}>\n"
        f"**Winners:** {winners_text}"
    )
    embed.add_field(name="Entries", value=str(len(pool)))
    if row.bonus_roles:
        embed.add_field(name="Bonus", value=role_mentions(row.bonus_roles))
    if row.required_roles:
        embed.add_field(name="Role", value=role_mentions(row.required_roles))
    if row.required_servers:
        embed.add_field(name="Server", value=server_labels(bot, row.required_servers))
    if row.ignore_roles:
        embed.add_field(name="Ignore", value=role_mentions(row.ignore_roles))
    try:
        await message.edit(embed=embed, view=GiveawayEndedView())
    except discord.HTTPException:
        logger.warning("Could not edit ended giveaway %s", row.message_id)
    if wins:
        try:
            await message.reply(
                f"**{row.title}** winners:\n"
                + "\n".join(f"<@{user_id}> (`{user_id}`)" for user_id in wins)
            )
        except discord.HTTPException:
            pass
    await db.store_ended_giveaway(row.channel_id, row.message_id, members)


class GiveawayView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(emoji="🎉", style=discord.ButtonStyle.blurple, custom_id="giveaway:join")
    async def join(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        client = interaction.client
        if not isinstance(client, Aspect) or interaction.guild is None:
            return
        if interaction.message is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            db = database(client)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        await interaction.response.defer(ephemeral=True)
        row = await db.giveaway(interaction.guild.id, interaction.message.id)
        if row is None:
            await interaction.followup.send(
                view=container_view(
                    ui.TextDisplay("This giveaway does not exist or has been removed.")
                ),
                ephemeral=True,
            )
            return
        member = interaction.user
        if row.ignore_roles:
            blocked = next(
                (role_id for role_id in row.ignore_roles if member.get_role(role_id)),
                None,
            )
            if blocked is not None:
                role = interaction.guild.get_role(blocked)
                label = role.mention if role else f"<@&{blocked}>"
                await interaction.followup.send(
                    view=container_view(
                        ui.TextDisplay(f"You can't join this giveaway with {label}.")
                    ),
                    ephemeral=True,
                )
                return
        has_role = row.required_roles and any(
            member.get_role(role_id) for role_id in row.required_roles
        )
        if row.required_roles and not has_role:
            await interaction.followup.send(
                view=container_view(
                    ui.TextDisplay(
                        "You need one of these roles to join: " + role_mentions(row.required_roles)
                    )
                ),
                ephemeral=True,
            )
            return
        if row.required_servers:
            missing: list[str] = []
            for server_id in row.required_servers:
                guild = client.get_guild(server_id)
                if guild is None or guild.get_member(member.id) is None:
                    missing.append(guild.name if guild else f"`{server_id}`")
            if missing:
                await interaction.followup.send(
                    view=container_view(
                        ui.TextDisplay("Join these servers to enter: " + ", ".join(missing))
                    ),
                    ephemeral=True,
                )
                return
        members = list(row.members)
        bonus = bool(
            row.bonus_roles and any(member.get_role(role_id) for role_id in row.bonus_roles)
        )
        if member.id in members:
            leave: ui.Button[Any] = ui.Button(
                label="Leave the Giveaway",
                style=discord.ButtonStyle.danger,
            )

            async def leave_callback(inter: discord.Interaction[Any]) -> None:
                await inter.response.defer(ephemeral=True)
                if interaction.guild is None or interaction.message is None:
                    return
                current = await db.giveaway(interaction.guild.id, interaction.message.id)
                if current is None:
                    return
                updated = [user_id for user_id in current.members if user_id != member.id]
                await db.set_giveaway_members(interaction.message.id, updated)
                await _sync_entries(interaction.message, len(unique_members(updated)))
                await inter.followup.send(
                    view=container_view(ui.TextDisplay("You left the giveaway.")),
                    ephemeral=True,
                )

            leave.callback = leave_callback  # type: ignore[assignment]
            view = ui.View()
            view.add_item(leave)
            await interaction.followup.send(
                "You are already in this giveaway.",
                view=view,
                ephemeral=True,
            )
            return
        members.append(member.id)
        if bonus:
            members.append(member.id)
        await db.set_giveaway_members(interaction.message.id, members)
        await _sync_entries(interaction.message, len(unique_members(members)))
        text = (
            "You joined the giveaway with **double chances**!"
            if bonus
            else "You joined the giveaway."
        )
        await interaction.followup.send(
            view=container_view(ui.TextDisplay(text)),
            ephemeral=True,
        )

    @ui.button(
        label="Participants",
        style=discord.ButtonStyle.secondary,
        custom_id="giveaway:participants",
    )
    async def participants(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        await _show_participants(interaction, ended=False)


class GiveawayEndedView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Participants",
        style=discord.ButtonStyle.secondary,
        custom_id="giveaway:participants_ended",
    )
    async def participants(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        await _show_participants(interaction, ended=True)


async def _sync_entries(message: discord.Message, count: int) -> None:
    if not message.embeds:
        return
    embed = message.embeds[0]
    if embed.fields:
        embed.set_field_at(0, name="Entries", value=str(count))
    try:
        await message.edit(embed=embed)
    except discord.HTTPException:
        return


async def _show_participants(interaction: discord.Interaction[Any], *, ended: bool) -> None:
    client = interaction.client
    if not isinstance(client, Aspect) or interaction.message is None:
        return
    try:
        db = database(client)
    except DatabaseUnavailable as exc:
        await report_interaction(interaction, exc, where="Database")
        return
    await interaction.response.defer(ephemeral=True)
    if ended:
        members = await db.ended_giveaway(interaction.message.channel.id, interaction.message.id)
    else:
        if interaction.guild is None:
            return
        row = await db.giveaway(interaction.guild.id, interaction.message.id)
        members = row.members if row else None
    if members is None:
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("This giveaway does not exist.")),
            ephemeral=True,
        )
        return
    counts: dict[int, int] = {}
    for user_id in members:
        counts[user_id] = counts.get(user_id, 0) + 1
    if not counts:
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("This giveaway has no participants yet.")),
            ephemeral=True,
        )
        return
    lines = [
        f"<@{user_id}>" + (" (Bonus)" if count > 1 else "") for user_id, count in counts.items()
    ]
    body = "\n".join(lines[:40])
    if len(lines) > 40:
        body += f"\n…and {len(lines) - 40} more"
    await interaction.followup.send(
        view=container_view(ui.TextDisplay(f"## Participants\n{body}")),
        ephemeral=True,
    )


class Giveaways(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(GiveawayView())
        self.bot.add_view(GiveawayEndedView())
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()

    @tasks.loop(minutes=1)
    async def watch(self) -> None:
        if self.bot.db is None:
            return
        try:
            rows = await self.bot.db.expired_giveaways(datetime.now(UTC))
            for row in rows:
                await end_giveaway(self.bot, row)
        except Exception:
            logger.exception("Giveaway watcher failed")

    @watch.before_loop
    async def before_watch(self) -> None:
        await self.bot.wait_until_ready()

    async def active_giveaway(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
    ) -> Giveaway | None:
        db = database(self.bot)
        if ctx.guild is None:
            return None
        row = await db.giveaway(ctx.guild.id, message.id)
        if row is None:
            await require_context(ctx).warn("This message is not a giveaway or it already ended.")
            return None
        return row

    @commands.guild_only()
    @commands.hybrid_group(name="giveaway", aliases=("gw",), fallback="list")  # type: ignore[arg-type]
    async def giveaway(self, ctx: commands.Context[Any]) -> None:
        """List every active giveaway."""
        await self.list_giveaways(ctx)

    @giveaway.command(
        name="list",
        description="List every active giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    async def list_cmd(self, ctx: commands.Context[Any]) -> None:
        await self.list_giveaways(ctx)

    async def list_giveaways(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        db = database(self.bot)
        if ctx.guild is None:
            return
        rows = await db.giveaways(ctx.guild.id)
        if not rows:
            await ctx.warn("There are no active giveaways.")
            return
        lines = [
            f"[**{row.title}**](https://discord.com/channels/{ctx.guild.id}/"
            f"{row.channel_id}/{row.message_id}) ends "
            f"<t:{int(row.finish.timestamp())}:R>"
            for row in rows
        ]
        await ctx.send(
            view=container_view(
                ui.TextDisplay(f"## Giveaways in {ctx.guild.name}\n" + "\n".join(lines))
            )
        )

    @giveaway.command(
        name="create",
        description="Start a giveaway.",
    )
    @app_commands.describe(
        channel="Channel to host the giveaway",
        duration="How long it runs, e.g. 12h",
        winners="Number of winners",
        prize="Prize text; flags: --role --bonus --ignore --server",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel to host the giveaway",
        duration="How long it runs, e.g. 12h",
        winners="Number of winners",
        prize="Prize text; flags: --role --bonus --ignore --server",
    )
    async def create(
        self,
        ctx: commands.Context[Any],
        channel: discord.TextChannel,
        duration: str,
        winners: commands.Range[int, 1, 20],
        *,
        prize: str,
    ) -> None:
        ctx = require_context(ctx)
        db = database(self.bot)
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        seconds = await Duration().convert(ctx, duration)
        if await db.active_giveaway_count(ctx.guild.id) >= MAX_ACTIVE:
            await ctx.warn(f"You can't host more than **{MAX_ACTIVE}** giveaways at once.")
            return
        title, flags = parse_flags(prize)
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        required_roles: list[int] = []
        bonus_roles: list[int] = []
        ignore_roles: list[int] = []
        required_servers: list[int] = []
        try:
            if "--role" in flags:
                roles = await parse_roles(ctx, flags["--role"])
                if len(roles) > MAX_ROLE_REQS:
                    await ctx.warn(f"You can only set up to {MAX_ROLE_REQS} required roles.")
                    return
                required_roles = [role.id for role in roles]
            if "--bonus" in flags:
                roles = await parse_roles(ctx, flags["--bonus"])
                if len(roles) > MAX_ROLE_REQS:
                    await ctx.warn(f"You can only set up to {MAX_ROLE_REQS} bonus roles.")
                    return
                bonus_roles = [role.id for role in roles]
            if "--ignore" in flags:
                roles = await parse_roles(ctx, flags["--ignore"])
                if len(roles) > MAX_ROLE_REQS:
                    await ctx.warn(f"You can only set up to {MAX_ROLE_REQS} ignore roles.")
                    return
                ignore_roles = [role.id for role in roles]
        except commands.BadArgument:
            await ctx.warn("Invalid role(s) provided.")
            return
        if "--server" in flags:
            server_ids = parse_server_ids(flags["--server"])
            if server_ids is None:
                await ctx.warn("Invalid server id(s) provided.")
                return
            if len(server_ids) > MAX_SERVER_REQS:
                await ctx.warn(f"You can only set up to {MAX_SERVER_REQS} sponsored servers.")
                return
            for server_id in server_ids:
                if self.bot.get_guild(server_id) is None:
                    await ctx.warn(f"I'm not in server `{server_id}`, so it can't be required.")
                    return
            required_servers = server_ids
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        embed = build_embed(
            self.bot,
            title=title,
            finish=finish,
            host=ctx.author.mention,
            winners=int(winners),
            entries=0,
            required_roles=required_roles or None,
            bonus_roles=bonus_roles or None,
            ignore_roles=ignore_roles or None,
            required_servers=required_servers or None,
        )
        message = await channel.send(embed=embed, view=GiveawayView())
        await db.create_giveaway(
            message_id=message.id,
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            winners=int(winners),
            finish=finish,
            host_id=ctx.author.id,
            title=title,
            required_roles=required_roles or None,
            bonus_roles=bonus_roles or None,
            ignore_roles=ignore_roles or None,
            required_servers=required_servers or None,
        )
        await ctx.approve(f"Giveaway started in {channel.mention}.")

    @giveaway.command(
        name="end"
        description="End an active giveaway early.",
    )
    @app_commands.describe(
        message="Giveaway message id or link",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message="Giveaway message id or link",
    )
    async def end(self, ctx: commands.Context[Any], message: discord.Message) -> None:
        """End an active giveaway early."""
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        await end_giveaway(self.bot, row)
        channel = message.channel
        target = channel.mention if isinstance(channel, discord.abc.GuildChannel) else "DM"
        await ctx.approve(f"Ended giveaway in {target}.")

    @giveaway.command(
        name="delete",
        description="Delete a giveaway without picking winners.",
    )
    @app_commands.describe(
        message_id="Giveaway message id",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(message_id="Giveaway message id")
    async def delete(self, ctx: commands.Context[Any], message_id: int) -> None:
        """Delete a giveaway without picking winners."""
        ctx = require_context(ctx)
        db = database(self.bot)
        if ctx.guild is None:
            return
        row = await db.giveaway(ctx.guild.id, message_id)
        if row is None:
            await ctx.warn("This message is not a valid giveaway.")
            return
        await db.delete_giveaway(message_id)
        channel = ctx.guild.get_channel(row.channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.HTTPException:
                pass
        await ctx.approve("The giveaway has been deleted.")

    @giveaway.command(
        name="reroll",
        description="Reroll winners for an ended giveaway.",
    )
    @app_commands.describe(
        message="Ended giveaway message id or link",
        winners="How many winners to draw",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message="Ended giveaway message id or link",
        winners="How many winners to draw",
    )
    async def reroll(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        winners: commands.Range[int, 1, 20] = 1,
    ) -> None:
        ctx = require_context(ctx)
        db = database(self.bot)
        members = await db.ended_giveaway(message.channel.id, message.id)
        if members is None:
            await ctx.warn("This message is not an ended giveaway. Use `giveaway end` first.")
            return
        if len(members) < int(winners):
            await ctx.warn(
                f"Not enough participants to reroll {winners} winners. "
                f"There are only {len(members)} entries."
            )
            return
        picks = random.sample(members, int(winners))
        await ctx.approve("**New winners:** " + ", ".join(f"<@{user_id}>" for user_id in picks))

    @giveaway.group(name="edit", invoke_without_command=True)  # type: ignore[arg-type]
    @commands.has_permissions(manage_guild=True)
    async def edit(self, ctx: commands.Context[Any]) -> None:
        """Edit a giveaway's settings."""
        ctx = require_context(ctx)
        await ctx.warn("Use `prize`, `duration`, `host`, or `winners`.")

    @edit.command(
        name="prize",
        description="Edit the prize of a giveaway.",
    )
    @app_commands.describe(
        message="Giveaway message id or link",
        prize="New prize",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_prize(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        *,
        prize: str,
    ) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return
        title = " ".join(prize.split())
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        embed = message.embeds[0]
        embed.title = title
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_title(message.id, title)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) prize to **{title}**.")

    @edit.command(
        name="duration",
        description="Edit the remaining duration of a giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message="Giveaway message id or link",
        duration="New duration",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_duration(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        duration: str,
    ) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return
        seconds = await Duration().convert(ctx, duration)
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        embed = message.embeds[0]
        embed.description = giveaway_description(finish, f"<@{row.host_id}>", row.winners)
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_finish(message.id, finish)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) duration.")

    @edit.command(
        name="host",
        description="Edit the host of a giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message="Giveaway message id or link",
        host="New host",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_host(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        host: discord.User,
    ) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return
        embed = message.embeds[0]
        embed.description = giveaway_description(row.finish, host.mention, row.winners)
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_host(message.id, host.id)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) host to **{host}**.")

    @edit.command(
        name="winners",
        description="Edit the number of winners for a giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message="Giveaway message id or link",
        winners="How many winners to draw",
    )
    async def edit_winners(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        winners: commands.Range[int, 1, 20],
    ) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return
        embed = message.embeds[0]
        embed.description = giveaway_description(
            row.finish,
            f"<@{row.host_id}>",
            int(winners),
        )
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_winners(message.id, int(winners))
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) winners to **{winners}**.")

    @giveaway.group(name="requirements", invoke_without_command=True)  # type: ignore[arg-type]
    @commands.has_permissions(manage_guild=True)
    async def requirements(self, ctx: commands.Context[Any]) -> None:
        """Manage giveaway requirements."""
        ctx = require_context(ctx)
        await ctx.warn(
            "Use `add`, `remove`, or `edit`. Flags: `role`, `bonus`, `ignore`, `server`."
        )

    @requirements.command(
        name="add",
        description="Add a requirement to a giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_add(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        flag: str,
        *,
        value: str,
    ) -> None:
        await self._requirements_mutate(ctx, message, flag.lower(), value, mode="add")

    @requirements.command(
        name="edit",
        description="Replace a requirement on a giveaway.",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_edit(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        flag: str,
        *,
        value: str,
    ) -> None:
        await self._requirements_mutate(ctx, message, flag.lower(), value, mode="edit")

    @requirements.command(
        name="remove"
        description="Remove a requirement from a giveaway, use `all` to remove all requirements.",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_remove(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        flag: str,
        *,
        value: str = "all",
    ) -> None:
        await self._requirements_mutate(ctx, message, flag.lower(), value, mode="remove")

    async def _requirements_mutate(
        self,
        ctx: commands.Context[Any],
        message: discord.Message,
        flag: str,
        value: str,
        *,
        mode: str,
    ) -> None:
        ctx = require_context(ctx)
        if flag not in {"role", "bonus", "ignore", "server"}:
            await ctx.warn("Invalid flag. Use `role`, `bonus`, `ignore`, or `server`.")
            return
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return
        db = database(self.bot)
        embed = message.embeds[0]
        field = _FIELD_NAMES[flag]
        if flag == "server":
            current = list(row.required_servers or [])
            column = "required_servers"
            if mode == "remove":
                if value.lower() == "all":
                    await db.set_giveaway_roles(message.id, column, None)
                    remove_field(embed, field)
                else:
                    ids = parse_server_ids(value)
                    if ids is None:
                        await ctx.warn("Invalid server id(s) provided.")
                        return
                    updated = [item for item in current if item not in ids]
                    await db.set_giveaway_roles(
                        message.id,
                        column,
                        updated or None,
                    )
                    if updated:
                        set_or_add_field(embed, field, server_labels(self.bot, updated))
                    else:
                        remove_field(embed, field)
            else:
                ids = parse_server_ids(value)
                if ids is None:
                    await ctx.warn("Invalid server id(s) provided.")
                    return
                for server_id in ids:
                    if self.bot.get_guild(server_id) is None:
                        await ctx.warn(f"I'm not in server `{server_id}`, so it can't be required.")
                        return
                updated = ids if mode == "edit" else list(dict.fromkeys(current + ids))
                if len(updated) > MAX_SERVER_REQS:
                    await ctx.warn(f"You can only have up to {MAX_SERVER_REQS} sponsored servers.")
                    return
                await db.set_giveaway_roles(message.id, column, updated)
                set_or_add_field(embed, field, server_labels(self.bot, updated))
        else:
            column = _ROLE_COLUMNS[flag]
            current = list(getattr(row, column) or [])
            if mode == "remove":
                if value.lower() == "all":
                    await db.set_giveaway_roles(message.id, column, None)
                    remove_field(embed, field)
                else:
                    try:
                        roles = await parse_roles(ctx, value)
                    except commands.BadArgument:
                        await ctx.warn("Invalid role(s) provided.")
                        return
                    remove_ids = {role.id for role in roles}
                    updated = [role_id for role_id in current if role_id not in remove_ids]
                    await db.set_giveaway_roles(message.id, column, updated or None)
                    if updated:
                        set_or_add_field(embed, field, role_mentions(updated))
                    else:
                        remove_field(embed, field)
            else:
                try:
                    roles = await parse_roles(ctx, value)
                except commands.BadArgument:
                    await ctx.warn("Invalid role(s) provided.")
                    return
                ids = [role.id for role in roles]
                updated = ids if mode == "edit" else list(dict.fromkeys(current + ids))
                if len(updated) > MAX_ROLE_REQS:
                    await ctx.warn(f"You can only have up to {MAX_ROLE_REQS} {flag} roles.")
                    return
                await db.set_giveaway_roles(message.id, column, updated)
                set_or_add_field(embed, field, role_mentions(updated))
        await message.edit(embed=embed)
        await ctx.approve(f"Updated {flag} requirement on [giveaway]({message.jump_url}).")

async def setup(bot: Aspect) -> None:
    await bot.add_cog(Giveaways(bot))
