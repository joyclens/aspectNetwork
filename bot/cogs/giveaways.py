from __future__ import annotations

import contextlib
import logging
import random
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple

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

Ctx = commands.Context[Any]
Interaction = discord.Interaction[Any]
Mode = Literal["add", "edit", "remove"]

EMBED_COLOR = 0xFF3171
MAX_ACTIVE = 5
PARTICIPANT_PAGE = 40
FLAG_PATTERN = re.compile(
    r"--(?P<flag>role|bonus|ignore|server)\s+(?P<value>.+?)(?=\s--|\s*$)",
    re.IGNORECASE,
)


class Requirement(NamedTuple):
    column: str
    field: str
    label: str
    limit: int


REQUIREMENTS = {
    "bonus": Requirement("bonus_roles", "Bonus", "bonus roles", 5),
    "role": Requirement("required_roles", "Role", "required roles", 5),
    "server": Requirement("required_servers", "Server", "sponsored servers", 3),
    "ignore": Requirement("ignore_roles", "Ignore", "ignore roles", 5),
}


def user_mention(user_id: int) -> str:
    return f"<@{user_id}>"


def role_mentions(role_ids: list[int]) -> str:
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def server_label(bot: Aspect, server_id: int) -> str:
    guild = bot.get_guild(server_id)
    return guild.name if guild else f"`{server_id}`"


def in_server(bot: Aspect, server_id: int, user_id: int) -> bool:
    guild = bot.get_guild(server_id)
    return guild is not None and guild.get_member(user_id) is not None


def has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    return any(member.get_role(role_id) for role_id in role_ids)


def format_ids(bot: Aspect, flag: str, ids: list[int]) -> str:
    if flag == "server":
        return ", ".join(server_label(bot, server_id) for server_id in ids)
    return role_mentions(ids)


def requirements_of(row: Giveaway) -> dict[str, list[int] | None]:
    return {
        requirement.column: getattr(row, requirement.column)
        for requirement in REQUIREMENTS.values()
    }


def giveaway_description(
    label: str,
    moment: datetime,
    host: str,
    winners: int | str,
) -> str:
    stamp = int(moment.timestamp())
    return (
        f"**{label}:** <t:{stamp}> (<t:{stamp}:R>)\n"
        f"**Hosted by:** {host}\n"
        f"**Winners:** {winners}"
    )


def running_description(
    row: Giveaway,
    *,
    finish: datetime | None = None,
    host: str | None = None,
    winners: int | None = None,
) -> str:
    return giveaway_description(
        "Ends",
        finish or row.finish,
        host or user_mention(row.host_id),
        winners or row.winners,
    )


def build_embed(
    bot: Aspect,
    *,
    title: str,
    description: str,
    entries: int,
    requirements: dict[str, list[int] | None],
) -> discord.Embed:
    embed = discord.Embed(color=EMBED_COLOR, title=title, description=description)
    embed.add_field(name="Entries", value=str(entries))
    for flag, requirement in REQUIREMENTS.items():
        if ids := requirements.get(requirement.column):
            embed.add_field(name=requirement.field, value=format_ids(bot, flag, ids))
    return embed


def update_field(embed: discord.Embed, name: str, value: str | None) -> None:
    index = next(
        (i for i, field in enumerate(embed.fields) if (field.name or "").lower() == name.lower()),
        None,
    )
    if value is None:
        if index is not None:
            embed.remove_field(index)
    elif index is None:
        embed.add_field(name=name, value=value)
    else:
        embed.set_field_at(index, name=name, value=value)


def parse_flags(prize: str) -> tuple[str, dict[str, str]]:
    flags = {
        match["flag"].lower(): match["value"].strip() for match in FLAG_PATTERN.finditer(prize)
    }
    return " ".join(FLAG_PATTERN.sub("", prize).split()), flags


async def parse_roles(ctx: Ctx, raw: str) -> list[discord.Role]:
    converter = commands.RoleConverter()
    return [await converter.convert(ctx, token) for token in raw.split()]


def merge_ids(current: list[int], ids: list[int], mode: Mode) -> list[int]:
    if mode == "remove":
        return [item for item in current if item not in ids]
    if mode == "edit":
        return ids
    return list(dict.fromkeys(current + ids))


def draw_winners(entries: list[int], count: int) -> list[int]:
    pool = list(entries)
    winners: list[int] = []
    while pool and len(winners) < count:
        winner = random.choice(pool)
        winners.append(winner)
        pool = [user_id for user_id in pool if user_id != winner]
    return winners


def entry_block(bot: Aspect, member: discord.Member, row: Giveaway) -> str | None:
    blocked = next((role_id for role_id in row.ignore_roles or [] if member.get_role(role_id)), None)
    if blocked is not None:
        return f"You can't join this giveaway with {role_mentions([blocked])}."
    if row.required_roles and not has_any_role(member, row.required_roles):
        return "You need one of these roles to join: " + role_mentions(row.required_roles)
    missing = [
        server_label(bot, server_id)
        for server_id in row.required_servers or []
        if not in_server(bot, server_id, member.id)
    ]
    if missing:
        return "Join these servers to enter: " + ", ".join(missing)
    return None


async def respond(interaction: Interaction, text: str) -> None:
    await interaction.followup.send(
        view=container_view(ui.TextDisplay(text)),
        ephemeral=True,
    )


async def ready_client(interaction: Interaction) -> Aspect | None:
    client = interaction.client
    if not isinstance(client, Aspect):
        return None
    try:
        database(client)
    except DatabaseUnavailable as exc:
        await report_interaction(interaction, exc, where="Database")
        return None
    return client


async def sync_entries(message: discord.Message, count: int) -> None:
    if not message.embeds or not message.embeds[0].fields:
        return
    embed = message.embeds[0]
    embed.set_field_at(0, name="Entries", value=str(count))
    with contextlib.suppress(discord.HTTPException):
        await message.edit(embed=embed)


async def show_participants(interaction: Interaction, *, ended: bool) -> None:
    client = await ready_client(interaction)
    message = interaction.message
    if client is None or message is None:
        return
    db = database(client)
    await interaction.response.defer(ephemeral=True)
    members: list[int] | None = None
    if ended:
        members = await db.ended_giveaway(message.channel.id, message.id)
    elif interaction.guild is not None:
        row = await db.giveaway(interaction.guild.id, message.id)
        members = row.members if row else None
    if members is None:
        await respond(interaction, "This giveaway does not exist.")
        return
    if not members:
        await respond(interaction, "This giveaway has no participants yet.")
        return
    lines = [
        user_mention(user_id) + (" (Bonus)" if count > 1 else "")
        for user_id, count in Counter(members).items()
    ]
    body = "\n".join(lines[:PARTICIPANT_PAGE])
    if len(lines) > PARTICIPANT_PAGE:
        body += f"\n…and {len(lines) - PARTICIPANT_PAGE} more"
    await respond(interaction, f"## Participants\n{body}")


class LeaveView(ui.View):
    def __init__(self, bot: Aspect, message: discord.Message, member_id: int) -> None:
        super().__init__()
        self.bot = bot
        self.message = message
        self.member_id = member_id

    @ui.button(label="Leave the Giveaway", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: Interaction, _button: ui.Button[Any]) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.defer(ephemeral=True)
        db = database(self.bot)
        row = await db.giveaway(interaction.guild_id, self.message.id)
        if row is None:
            await respond(interaction, "This giveaway does not exist or has been removed.")
            return
        members = [user_id for user_id in row.members if user_id != self.member_id]
        await db.set_giveaway_members(self.message.id, members)
        await sync_entries(self.message, len(set(members)))
        await respond(interaction, "You left the giveaway.")


class GiveawayView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(emoji="🎉", style=discord.ButtonStyle.blurple, custom_id="giveaway:join")
    async def join(self, interaction: Interaction, _button: ui.Button[Any]) -> None:
        client = await ready_client(interaction)
        member = interaction.user
        message = interaction.message
        if (
            client is None
            or interaction.guild is None
            or message is None
            or not isinstance(member, discord.Member)
        ):
            return
        db = database(client)
        await interaction.response.defer(ephemeral=True)
        row = await db.giveaway(interaction.guild.id, message.id)
        if row is None:
            await respond(interaction, "This giveaway does not exist or has been removed.")
            return
        if reason := entry_block(client, member, row):
            await respond(interaction, reason)
            return
        if member.id in row.members:
            await interaction.followup.send(
                "You are already in this giveaway.",
                view=LeaveView(client, message, member.id),
                ephemeral=True,
            )
            return
        bonus = has_any_role(member, row.bonus_roles or [])
        members = [*row.members, *([member.id] * (2 if bonus else 1))]
        await db.set_giveaway_members(message.id, members)
        await sync_entries(message, len(set(members)))
        await respond(
            interaction,
            "You joined the giveaway with **double chances**!"
            if bonus
            else "You joined the giveaway.",
        )

    @ui.button(
        label="Participants",
        style=discord.ButtonStyle.secondary,
        custom_id="giveaway:participants",
    )
    async def participants(self, interaction: Interaction, _button: ui.Button[Any]) -> None:
        await show_participants(interaction, ended=False)


class GiveawayEndedView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Participants",
        style=discord.ButtonStyle.secondary,
        custom_id="giveaway:participants_ended",
    )
    async def participants(self, interaction: Interaction, _button: ui.Button[Any]) -> None:
        await show_participants(interaction, ended=True)


async def fetch_message(bot: Aspect, row: Giveaway) -> discord.Message | None:
    guild = bot.get_guild(row.guild_id)
    if guild is None:
        return None
    try:
        channel = guild.get_channel(row.channel_id) or await guild.fetch_channel(row.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        return await channel.fetch_message(row.message_id)
    except discord.HTTPException:
        return None


async def announce_result(bot: Aspect, row: Giveaway, message: discord.Message) -> None:
    winners = draw_winners(row.members, row.winners)
    if len(winners) < row.winners:
        winners = []
        result = f"{row.winners}\n\n> Not enough entries to determine the winners!"
    else:
        result = ", ".join(user_mention(user_id) for user_id in winners)
    embed = build_embed(
        bot,
        title=row.title,
        description=giveaway_description(
            "Ended",
            datetime.now(UTC),
            user_mention(row.host_id),
            result,
        ),
        entries=len(set(row.members)),
        requirements=requirements_of(row),
    )
    try:
        await message.edit(embed=embed, view=GiveawayEndedView())
    except discord.HTTPException:
        logger.warning("Could not edit ended giveaway %s", row.message_id)
    if winners:
        with contextlib.suppress(discord.HTTPException):
            await message.reply(
                f"**{row.title}** winners:\n"
                + "\n".join(f"{user_mention(user_id)} (`{user_id}`)" for user_id in winners)
            )


async def end_giveaway(bot: Aspect, row: Giveaway) -> None:
    message = await fetch_message(bot, row)
    if message is not None:
        await announce_result(bot, row, message)
    await database(bot).store_ended_giveaway(row.channel_id, row.message_id, row.members)


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
            for row in await self.bot.db.expired_giveaways(datetime.now(UTC)):
                await end_giveaway(self.bot, row)
        except Exception:
            logger.exception("Giveaway watcher failed")

    @watch.before_loop
    async def before_watch(self) -> None:
        await self.bot.wait_until_ready()

    async def active_giveaway(self, ctx: Ctx, message: discord.Message) -> Giveaway | None:
        ctx = require_context(ctx)
        if ctx.guild is None:
            return None
        row = await database(self.bot).giveaway(ctx.guild.id, message.id)
        if row is None:
            await ctx.warn("This message is not a giveaway or it already ended.")
        return row

    async def editable(
        self,
        ctx: Ctx,
        message: discord.Message,
    ) -> tuple[Giveaway, discord.Embed] | None:
        row = await self.active_giveaway(ctx, message)
        if row is None or not message.embeds:
            return None
        return row, message.embeds[0]

    async def parse_ids(
        self,
        ctx: Ctx,
        flag: str,
        raw: str,
        *,
        verify: bool,
    ) -> list[int] | None:
        ctx = require_context(ctx)
        if flag != "server":
            try:
                return [role.id for role in await parse_roles(ctx, raw)]
            except commands.BadArgument:
                await ctx.warn("Invalid role(s) provided.")
                return None
        tokens = raw.split()
        if not all(token.isdigit() for token in tokens):
            await ctx.warn("Invalid server id(s) provided.")
            return None
        ids = [int(token) for token in tokens]
        unknown = next((i for i in ids if verify and self.bot.get_guild(i) is None), None)
        if unknown is not None:
            await ctx.warn(f"I'm not in server `{unknown}`, so it can't be required.")
            return None
        return ids

    async def resolve_ids(
        self,
        ctx: Ctx,
        flag: str,
        raw: str,
        current: list[int],
        mode: Mode,
    ) -> list[int] | None:
        ctx = require_context(ctx)
        if mode == "remove" and raw.lower() == "all":
            return []
        ids = await self.parse_ids(ctx, flag, raw, verify=mode != "remove")
        if ids is None:
            return None
        updated = merge_ids(current, ids, mode)
        requirement = REQUIREMENTS[flag]
        if len(updated) > requirement.limit:
            await ctx.warn(f"You can only set up to {requirement.limit} {requirement.label}.")
            return None
        return updated

    async def mutate_requirement(
        self,
        ctx: Ctx,
        message: discord.Message,
        flag: str,
        value: str,
        mode: Mode,
    ) -> None:
        ctx = require_context(ctx)
        flag = flag.lower()
        requirement = REQUIREMENTS.get(flag)
        if requirement is None:
            await ctx.warn("Invalid flag. Use `role`, `bonus`, `ignore`, or `server`.")
            return
        target = await self.editable(ctx, message)
        if target is None:
            return
        row, embed = target
        current = list(getattr(row, requirement.column) or [])
        updated = await self.resolve_ids(ctx, flag, value, current, mode)
        if updated is None:
            return
        await database(self.bot).set_giveaway_roles(message.id, requirement.column, updated or None)
        update_field(
            embed,
            requirement.field,
            format_ids(self.bot, flag, updated) if updated else None,
        )
        await message.edit(embed=embed)
        await ctx.approve(f"Updated {flag} requirement on [giveaway]({message.jump_url}).")

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="giveaway",
        aliases=("gw",),
        fallback="list",
        description="List every active giveaway in this server.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: Ctx) -> None:
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
            f"{row.channel_id}/{row.message_id}) ends <t:{int(row.finish.timestamp())}:R>"
            for row in rows
        ]
        await ctx.send(
            view=container_view(
                ui.TextDisplay(f"## Giveaways in {ctx.guild.name}\n" + "\n".join(lines))
            )
        )

    @giveaway.command(
        name="create",
        description="Start a giveaway in a channel, with optional entry requirements.",
    )
    @app_commands.describe(
        channel="Channel the giveaway is posted in",
        duration="How long it runs, e.g. 12h or 2d",
        winners="Number of winners (1-20)",
        prize="Prize name, then optional flags: --role --bonus --ignore --server",
    )
    @commands.has_permissions(manage_guild=True)
    async def create(
        self,
        ctx: Ctx,
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
        requirements: dict[str, list[int] | None] = {
            requirement.column: None for requirement in REQUIREMENTS.values()
        }
        for flag, raw in flags.items():
            ids = await self.resolve_ids(ctx, flag, raw, [], "edit")
            if ids is None:
                return
            requirements[REQUIREMENTS[flag].column] = ids
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        message = await channel.send(
            embed=build_embed(
                self.bot,
                title=title,
                description=giveaway_description("Ends", finish, ctx.author.mention, winners),
                entries=0,
                requirements=requirements,
            ),
            view=GiveawayView(),
        )
        await db.create_giveaway(
            message_id=message.id,
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            winners=winners,
            finish=finish,
            host_id=ctx.author.id,
            title=title,
            **requirements,
        )
        await ctx.approve(f"Giveaway started in {channel.mention}.")

    @giveaway.command(
        name="end",
        description="End a giveaway now and draw its winners.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
    )
    @commands.has_permissions(manage_guild=True)
    async def end(self, ctx: Ctx, message: discord.Message) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        await end_giveaway(self.bot, row)
        await ctx.approve(f"Ended [giveaway]({message.jump_url}).")

    @giveaway.command(
        name="delete",
        description="Delete a giveaway without drawing winners.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
    )
    @commands.has_permissions(manage_guild=True)
    async def delete(self, ctx: Ctx, message: discord.Message) -> None:
        ctx = require_context(ctx)
        if await self.active_giveaway(ctx, message) is None:
            return
        await database(self.bot).delete_giveaway(message.id)
        with contextlib.suppress(discord.HTTPException):
            await message.delete()
        await ctx.approve("The giveaway has been deleted.")

    @giveaway.command(
        name="reroll",
        description="Draw new winners for a giveaway that has ended.",
    )
    @app_commands.describe(
        message="Ended giveaway message ID or link",
        winners="How many new winners to draw (1-20)",
    )
    @commands.has_permissions(manage_guild=True)
    async def reroll(
        self,
        ctx: Ctx,
        message: discord.Message,
        winners: commands.Range[int, 1, 20] = 1,
    ) -> None:
        ctx = require_context(ctx)
        members = await database(self.bot).ended_giveaway(message.channel.id, message.id)
        if members is None:
            await ctx.warn("This message is not an ended giveaway. Use `giveaway end` first.")
            return
        picks = draw_winners(members, winners)
        if len(picks) < winners:
            await ctx.warn(
                f"Not enough participants to reroll {winners} winners. "
                f"There are only {len(set(members))} entries."
            )
            return
        await ctx.approve(
            "**New winners:** " + ", ".join(user_mention(user_id) for user_id in picks)
        )

    @giveaway.group(  # type: ignore[arg-type]
        name="edit",
        description="Change the prize, time, host or winners of a running giveaway.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def edit(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        await ctx.warn("Use `prize`, `duration`, `host`, or `winners`.")

    @edit.command(
        name="prize",
        description="Change the prize of a running giveaway.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        prize="The new prize",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_prize(self, ctx: Ctx, message: discord.Message, *, prize: str) -> None:
        ctx = require_context(ctx)
        target = await self.editable(ctx, message)
        if target is None:
            return
        _, embed = target
        title = " ".join(prize.split())
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        embed.title = title
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_title(message.id, title)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) prize to **{title}**.")

    @edit.command(
        name="duration",
        description="Restart a running giveaway's countdown with a new duration.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        duration="New time from now, e.g. 12h or 2d",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_duration(self, ctx: Ctx, message: discord.Message, duration: str) -> None:
        ctx = require_context(ctx)
        target = await self.editable(ctx, message)
        if target is None:
            return
        row, embed = target
        seconds = await Duration().convert(ctx, duration)
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        embed.description = running_description(row, finish=finish)
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_finish(message.id, finish)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) duration.")

    @edit.command(
        name="host",
        description="Change who is shown as the host of a running giveaway.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        host="The new host",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_host(self, ctx: Ctx, message: discord.Message, host: discord.User) -> None:
        ctx = require_context(ctx)
        target = await self.editable(ctx, message)
        if target is None:
            return
        row, embed = target
        embed.description = running_description(row, host=host.mention)
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_host(message.id, host.id)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) host to **{host}**.")

    @edit.command(
        name="winners",
        description="Change how many winners a running giveaway draws.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        winners="Number of winners (1-20)",
    )
    @commands.has_permissions(manage_guild=True)
    async def edit_winners(
        self,
        ctx: Ctx,
        message: discord.Message,
        winners: commands.Range[int, 1, 20],
    ) -> None:
        ctx = require_context(ctx)
        target = await self.editable(ctx, message)
        if target is None:
            return
        row, embed = target
        embed.description = running_description(row, winners=winners)
        await message.edit(embed=embed)
        await database(self.bot).set_giveaway_winners(message.id, winners)
        await ctx.approve(f"Updated [giveaway]({message.jump_url}) winners to **{winners}**.")

    @giveaway.group(  # type: ignore[arg-type]
        name="requirements",
        description="Add, replace or remove who can enter a giveaway.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        await ctx.warn(
            "Use `add`, `remove`, or `edit`. Flags: `role`, `bonus`, `ignore`, `server`."
        )

    @requirements.command(
        name="add",
        description="Add roles or servers to a giveaway's requirements.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type: role, bonus, ignore or server",
        value="Role mentions/IDs or server IDs, separated by spaces",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_add(
        self,
        ctx: Ctx,
        message: discord.Message,
        flag: str,
        *,
        value: str,
    ) -> None:
        await self.mutate_requirement(ctx, message, flag, value, "add")

    @requirements.command(
        name="edit",
        description="Replace one requirement of a giveaway with a new list.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type: role, bonus, ignore or server",
        value="Role mentions/IDs or server IDs, separated by spaces",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_edit(
        self,
        ctx: Ctx,
        message: discord.Message,
        flag: str,
        *,
        value: str,
    ) -> None:
        await self.mutate_requirement(ctx, message, flag, value, "edit")

    @requirements.command(
        name="remove",
        description="Remove roles or servers from a giveaway's requirements.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type: role, bonus, ignore or server",
        value="Roles or server IDs to remove, or `all` to clear the requirement",
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements_remove(
        self,
        ctx: Ctx,
        message: discord.Message,
        flag: str,
        *,
        value: str = "all",
    ) -> None:
        await self.mutate_requirement(ctx, message, flag, value, "remove")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Giveaways(bot))