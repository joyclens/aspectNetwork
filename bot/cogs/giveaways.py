from __future__ import annotations

import contextlib
import logging
import random
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from bot.core.bot import Aspect
from bot.core.database import Giveaway, SponsoredServer
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.converters import Duration
from bot.shared.errors import DatabaseUnavailable, report_interaction
from bot.shared.layout import AspectLayout, container_view

logger = logging.getLogger("aspect")

Ctx = commands.Context[Any]
Interaction = discord.Interaction[Any]
Mode = Literal["add", "edit", "remove"]

MAX_ACTIVE = 5
PARTICIPANT_PAGE = 40
FOOTER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
    "?ex=6acf58a0&is=6ace0720&hm=4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
)
FLAG_PATTERN = re.compile(
    r"--(?P<flag>role|ignore|server)\s+(?P<value>.+?)(?=\s--|\s*$)",
    re.IGNORECASE,
)
INVITE_PATTERN = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([a-z0-9-]+)"
)


class Requirement(NamedTuple):
    column: str
    label: str
    limit: int


REQUIREMENTS = {
    "role": Requirement("required_roles", "required roles", 5),
    "ignore": Requirement("ignore_roles", "restricted roles", 5),
    "server": Requirement("required_servers", "sponsored servers", 3),
}


def user_mention(user_id: int) -> str:
    return f"<@{user_id}>"


def role_mentions(role_ids: list[int]) -> str:
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    return any(member.get_role(role_id) for role_id in role_ids)


def stamp(moment: datetime) -> str:
    value = int(moment.timestamp())
    return f"<t:{value}:f> (<t:{value}:R>)"


def parse_flags(prize: str) -> tuple[str, dict[str, str]]:
    flags = {
        match["flag"].lower(): match["value"].strip() for match in FLAG_PATTERN.finditer(prize)
    }
    return " ".join(FLAG_PATTERN.sub("", prize).split()), flags


async def parse_roles(ctx: Ctx, raw: str) -> list[discord.Role]:
    converter = commands.RoleConverter()
    return [await converter.convert(ctx, token) for token in raw.split()]


def invite_code(token: str) -> str | None:
    cleaned = token.strip().strip("<>").rstrip(".,);]")
    if cleaned.isdigit():
        return None
    match = INVITE_PATTERN.search(cleaned)
    if match is not None:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-]{2,32}", cleaned):
        return cleaned
    try:
        return discord.utils.resolve_invite(cleaned).code.split("?")[0] or None
    except ValueError:
        return None


async def resolve_server(bot: Aspect, token: str) -> SponsoredServer | None:
    code = invite_code(token)
    if code is None:
        return None
    url = f"https://discord.gg/{code}"
    try:
        invite = await bot.fetch_invite(code)
    except discord.HTTPException:
        return SponsoredServer(name=code, invite=url)
    guild = invite.guild
    name = guild.name if isinstance(guild, discord.Guild | discord.PartialInviteGuild) else code
    return SponsoredServer(name=name, invite=f"https://discord.gg/{invite.code}")


def merge_ids(current: list[int], ids: list[int], mode: Mode) -> list[int]:
    if mode == "remove":
        return [item for item in current if item not in ids]
    if mode == "edit":
        return ids
    return list(dict.fromkeys(current + ids))


def merge_servers(
    current: list[SponsoredServer],
    servers: list[SponsoredServer],
    mode: Mode,
) -> list[SponsoredServer]:
    if mode == "remove":
        remove = {server.invite for server in servers}
        return [server for server in current if server.invite not in remove]
    if mode == "edit":
        return servers
    seen = {server.invite for server in current}
    merged = list(current)
    for server in servers:
        if server.invite not in seen:
            merged.append(server)
            seen.add(server.invite)
    return merged


def draw_winners(entries: list[int], count: int) -> list[int]:
    pool = list(entries)
    winners: list[int] = []
    while pool and len(winners) < count:
        winner = random.choice(pool)
        winners.append(winner)
        pool = [user_id for user_id in pool if user_id != winner]
    return winners


def entry_block(member: discord.Member, row: Giveaway) -> str | None:
    blocked = next(
        (role_id for role_id in row.ignore_roles or [] if member.get_role(role_id)),
        None,
    )
    if blocked is not None:
        return f"You can't join this giveaway with {role_mentions([blocked])}."
    if row.required_roles and not has_any_role(member, row.required_roles):
        return "You need one of these roles to join: " + role_mentions(row.required_roles)
    return None


def server_reminder(row: Giveaway) -> str | None:
    if not row.required_servers:
        return None
    links = " · ".join(f"[**{server.name}**]({server.invite})" for server in row.required_servers)
    return f"Remember to join the required server(s): {links}"


def requirements_text(row: Giveaway) -> str | None:
    lines: list[str] = []
    if row.required_servers:
        servers = " · ".join(
            f"[**{server.name}**]({server.invite})" for server in row.required_servers
        )
        lines.append(f"<:discord:1551257778109284352>  **Required Server:** {servers}")
    if row.required_roles:
        lines.append(
            "<:userLocked:1559577156399529984> **Required Role:** "
            + role_mentions(row.required_roles)
        )
    if row.ignore_roles:
        lines.append(
            "<:userSlash:1559577141216157746> **Restricted Role:** "
            + role_mentions(row.ignore_roles)
        )
    return "\n".join(lines) if lines else None


def giveaway_layout(
    row: Giveaway,
    *,
    entries: int | None = None,
    ended: bool = False,
    winners: str | None = None,
) -> AspectLayout:
    count = len(set(row.members)) if entries is None else entries
    when = stamp(datetime.now(UTC) if ended else row.finish)
    duration_label = "Ended" if ended else "Duration"
    if winners is None:
        winner_line = f"<:confetti:1551256166074687519>  **Winners:** `{row.winners}`"
    else:
        winner_line = f"<:confetti:1551256166074687519>  **Winners:** {winners}"
    header = (
        f"## <:giveaway:1551256171728347279> {row.title}\n"
        f"{winner_line}\n"
        f"<:event:1551256173901250580> **{duration_label}:** {when}\n"
        f"<:people:1551256195585540306> **Entries:** `{count:,}`"
    )
    items: list[ui.Item[Any]] = [ui.TextDisplay(header)]
    reqs = requirements_text(row)
    if reqs is not None:
        items.extend(
            [
                ui.Separator(visible=True),
                ui.TextDisplay(reqs),
            ]
        )
    items.extend(
        [
            ui.Separator(visible=True),
            ui.TextDisplay(
                "-# <:person:1551256197456330813> Giveaway hosted by " + user_mention(row.host_id)
            ),
        ]
    )
    if ended:
        items.append(ui.ActionRow(ParticipantsButton(ended=True)))
    else:
        items.append(ui.ActionRow(JoinButton(), ParticipantsButton()))
    items.append(ui.MediaGallery(discord.MediaGalleryItem(FOOTER)))
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view


def persistent_giveaway_views() -> tuple[AspectLayout, AspectLayout]:
    active = AspectLayout(timeout=None)
    active.add_item(ui.Container(ui.ActionRow(JoinButton(), ParticipantsButton())))
    ended = AspectLayout(timeout=None)
    ended.add_item(ui.Container(ui.ActionRow(ParticipantsButton(ended=True))))
    return active, ended


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


async def refresh_message(bot: Aspect, message: discord.Message, row: Giveaway) -> None:
    try:
        await message.edit(view=giveaway_layout(row))
    except discord.HTTPException:
        logger.warning("Could not refresh giveaway message %s", message.id)


async def show_participants(interaction: Interaction, *, ended: bool) -> None:
    client = await ready_client(interaction)
    message = interaction.message
    if client is None or message is None:
        return
    db = database(client)
    if not interaction.response.is_done():
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
    unique = list(dict.fromkeys(members))
    body = "\n".join(user_mention(user_id) for user_id in unique[:PARTICIPANT_PAGE])
    if len(unique) > PARTICIPANT_PAGE:
        body += f"\n…and {len(unique) - PARTICIPANT_PAGE} more"
    await respond(interaction, f"## Participants\n{body}")


async def handle_join(interaction: Interaction) -> None:
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
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    row = await db.giveaway(interaction.guild.id, message.id)
    if row is None:
        await respond(interaction, "This giveaway does not exist or has been removed.")
        return
    if reason := entry_block(member, row):
        await respond(interaction, reason)
        return
    if member.id in row.members:
        await interaction.followup.send(
            "You are already in this giveaway.",
            view=LeaveView(client, message, member.id),
            ephemeral=True,
        )
        return
    members = [*row.members, member.id]
    await db.set_giveaway_members(message.id, members)
    await refresh_message(client, message, replace(row, members=members))
    reminder = server_reminder(row)
    text = "You joined the giveaway."
    if reminder is not None:
        text = f"{text}\n{reminder}"
    await respond(interaction, text)


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
        await refresh_message(self.bot, self.message, replace(row, members=members))
        await respond(interaction, "You left the giveaway.")


class JoinButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            emoji=discord.PartialEmoji(name="confetti", id=1551256166074687519),
            style=discord.ButtonStyle.gray,
            custom_id="giveaway:join",
        )

    async def callback(self, interaction: Interaction) -> None:
        await handle_join(interaction)


class ParticipantsButton(ui.Button[Any]):
    def __init__(self, *, ended: bool = False) -> None:
        super().__init__(
            label="Participants",
            style=discord.ButtonStyle.secondary,
            custom_id=("giveaway:participants_ended" if ended else "giveaway:participants"),
        )
        self._ended = ended

    async def callback(self, interaction: Interaction) -> None:
        await show_participants(interaction, ended=self._ended)


async def fetch_message(bot: Aspect, row: Giveaway) -> discord.Message | None:
    guild = bot.get_guild(row.guild_id)
    if guild is None:
        try:
            guild = await bot.fetch_guild(row.guild_id)
        except discord.HTTPException:
            return None
    try:
        found = guild.get_channel(row.channel_id) or await bot.fetch_channel(row.channel_id)
    except discord.HTTPException:
        logger.warning(
            "Could not fetch giveaway channel guild=%s channel=%s",
            row.guild_id,
            row.channel_id,
        )
        return None
    if not isinstance(found, discord.TextChannel):
        return None
    try:
        return await found.fetch_message(row.message_id)
    except discord.HTTPException:
        logger.warning("Could not fetch giveaway message %s", row.message_id)
        return None


async def announce_result(bot: Aspect, row: Giveaway, message: discord.Message) -> None:
    winners = draw_winners(row.members, row.winners)
    if len(winners) < row.winners:
        winners = []
        result = "None"
    else:
        result = ", ".join(user_mention(user_id) for user_id in winners)
    try:
        await message.edit(view=giveaway_layout(row, ended=True, winners=result))
    except discord.HTTPException:
        logger.warning("Could not edit ended giveaway %s", row.message_id)
        return
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
    else:
        logger.warning("Ending giveaway %s without updating its message", row.message_id)
    await database(bot).store_ended_giveaway(row.channel_id, row.message_id, row.members)


class Giveaways(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        for view in persistent_giveaway_views():
            self.bot.add_view(view)
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
        reply = require_context(ctx)
        if reply.guild is None:
            return None
        row = await database(self.bot).giveaway(reply.guild.id, message.id)
        if row is None:
            await reply.warn("This message is not a giveaway or it already ended.")
        return row

    async def refresh(self, ctx: Ctx, message: discord.Message, row: Giveaway) -> None:
        await refresh_message(self.bot, message, row)
        await require_context(ctx).approve(f"Updated [giveaway]({message.jump_url}).")

    async def parse_role_ids(self, ctx: Ctx, raw: str) -> list[int] | None:
        reply = require_context(ctx)
        try:
            return [role.id for role in await parse_roles(ctx, raw)]
        except commands.BadArgument:
            await reply.warn("Invalid role(s) provided.")
            return None

    async def parse_servers(self, ctx: Ctx, raw: str) -> list[SponsoredServer] | None:
        reply = require_context(ctx)
        servers: list[SponsoredServer] = []
        for token in raw.split():
            server = await resolve_server(self.bot, token)
            if server is None:
                await reply.warn(
                    f"Invalid Discord invite: `{token}`, use a link like `https://discord.gg/aspect`."
                )
                return None
            servers.append(server)
        return servers

    async def mutate_requirement(
        self,
        ctx: Ctx,
        message: discord.Message,
        flag: str,
        value: str,
        mode: Mode,
    ) -> None:
        reply = require_context(ctx)
        flag = flag.lower()
        requirement = REQUIREMENTS.get(flag)
        if requirement is None:
            await reply.warn("Invalid flag. Use `role`, `ignore`, or `server`.")
            return
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        db = database(self.bot)
        if flag == "server":
            current = list(row.required_servers or [])
            if mode == "remove" and value.lower() == "all":
                updated_servers: list[SponsoredServer] = []
            else:
                parsed = await self.parse_servers(ctx, value)
                if parsed is None:
                    return
                updated_servers = merge_servers(current, parsed, mode)
            if len(updated_servers) > requirement.limit:
                await reply.warn(f"You can only set up to {requirement.limit} {requirement.label}.")
                return
            await db.set_giveaway_servers(message.id, updated_servers or None)
            row = replace(row, required_servers=updated_servers or None)
        elif flag == "role":
            current_ids = list(row.required_roles or [])
            if mode == "remove" and value.lower() == "all":
                updated_ids: list[int] = []
            else:
                parsed_ids = await self.parse_role_ids(ctx, value)
                if parsed_ids is None:
                    return
                updated_ids = merge_ids(current_ids, parsed_ids, mode)
            if len(updated_ids) > requirement.limit:
                await reply.warn(f"You can only set up to {requirement.limit} {requirement.label}.")
                return
            await db.set_giveaway_roles(message.id, "required_roles", updated_ids or None)
            row = replace(row, required_roles=updated_ids or None)
        else:
            current_ids = list(row.ignore_roles or [])
            if mode == "remove" and value.lower() == "all":
                updated_ids = []
            else:
                parsed_ids = await self.parse_role_ids(ctx, value)
                if parsed_ids is None:
                    return
                updated_ids = merge_ids(current_ids, parsed_ids, mode)
            if len(updated_ids) > requirement.limit:
                await reply.warn(f"You can only set up to {requirement.limit} {requirement.label}.")
                return
            await db.set_giveaway_roles(message.id, "ignore_roles", updated_ids or None)
            row = replace(row, ignore_roles=updated_ids or None)
        await self.refresh(ctx, message, row)

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
            f"{row.channel_id}/{row.message_id}) ends {stamp(row.finish)}"
            for row in rows
        ]
        await ctx.send(
            view=container_view(
                ui.TextDisplay(f"## Giveaways in {ctx.guild.name}\n" + "\n".join(lines))
            )
        )

    @giveaway.command(  # type: ignore[arg-type]
        name="create",
        description="Start a giveaway in a channel, with optional entry requirements.",
    )
    @app_commands.describe(
        channel="Channel the giveaway is posted in",
        duration="How long it runs, e.g. 12h or 2d",
        winners="Number of winners (1-20)",
        prize="Prize name",
        role="Optional required role",
        ignore="Optional role blocked from entering",
        server="Optional sponsored server invite, e.g. https://discord.gg/aspect",
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
        role: discord.Role | None = None,
        ignore: discord.Role | None = None,
        server: str | None = None,
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
        if server:
            flags["server"] = server
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        required_roles: list[int] | None = [role.id] if role is not None else None
        ignore_roles: list[int] | None = [ignore.id] if ignore is not None else None
        required_servers: list[SponsoredServer] | None = None
        if required_roles is None and "role" in flags:
            ids = await self.parse_role_ids(ctx, flags["role"])
            if ids is None:
                return
            if len(ids) > REQUIREMENTS["role"].limit:
                await ctx.warn(
                    f"You can only set up to {REQUIREMENTS['role'].limit} required roles."
                )
                return
            required_roles = ids
        if ignore_roles is None and "ignore" in flags:
            ids = await self.parse_role_ids(ctx, flags["ignore"])
            if ids is None:
                return
            if len(ids) > REQUIREMENTS["ignore"].limit:
                await ctx.warn(
                    f"You can only set up to {REQUIREMENTS['ignore'].limit} restricted roles."
                )
                return
            ignore_roles = ids
        if "server" in flags:
            servers = await self.parse_servers(ctx, flags["server"])
            if servers is None:
                return
            if len(servers) > REQUIREMENTS["server"].limit:
                await ctx.warn(
                    f"You can only set up to {REQUIREMENTS['server'].limit} sponsored servers."
                )
                return
            required_servers = servers
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        draft = Giveaway(
            message_id=0,
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            winners=winners,
            members=[],
            finish=finish,
            host_id=ctx.author.id,
            title=title,
            required_roles=required_roles,
            ignore_roles=ignore_roles,
            required_servers=required_servers,
        )
        message = await channel.send(view=giveaway_layout(draft))
        await db.create_giveaway(
            message_id=message.id,
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            winners=winners,
            finish=finish,
            host_id=ctx.author.id,
            title=title,
            required_roles=required_roles,
            ignore_roles=ignore_roles,
            required_servers=required_servers,
        )
        await ctx.approve(f"Giveaway started in {channel.mention}.")

    @giveaway.command(  # type: ignore[arg-type]
        name="end",
        description="End a giveaway now and draw its winners.",
    )
    @app_commands.describe(message="Giveaway message ID or link")
    @commands.has_permissions(manage_guild=True)
    async def end(self, ctx: Ctx, message: discord.Message) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        await end_giveaway(self.bot, row)
        await ctx.approve(f"Ended [giveaway]({message.jump_url}).")

    @giveaway.command(  # type: ignore[arg-type]
        name="delete",
        description="Delete a giveaway without drawing winners.",
    )
    @app_commands.describe(message="Giveaway message ID or link")
    @commands.has_permissions(manage_guild=True)
    async def delete(self, ctx: Ctx, message: discord.Message) -> None:
        ctx = require_context(ctx)
        if await self.active_giveaway(ctx, message) is None:
            return
        await database(self.bot).delete_giveaway(message.id)
        with contextlib.suppress(discord.HTTPException):
            await message.delete()
        await ctx.approve("The giveaway has been deleted.")

    @giveaway.command(  # type: ignore[arg-type]
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

    @edit.command(  # type: ignore[arg-type]
        name="prize",
        description="Change the prize of a running giveaway.",
    )
    @app_commands.describe(message="Giveaway message ID or link", prize="The new prize")
    @commands.has_permissions(manage_guild=True)
    async def edit_prize(self, ctx: Ctx, message: discord.Message, *, prize: str) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        title = " ".join(prize.split())
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        await database(self.bot).set_giveaway_title(message.id, title)
        await self.refresh(ctx, message, replace(row, title=title))

    @edit.command(  # type: ignore[arg-type]
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
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        seconds = await Duration().convert(ctx, duration)
        finish = datetime.now(UTC) + timedelta(seconds=seconds)
        await database(self.bot).set_giveaway_finish(message.id, finish)
        await self.refresh(ctx, message, replace(row, finish=finish))

    @edit.command(  # type: ignore[arg-type]
        name="host",
        description="Change who is shown as the host of a running giveaway.",
    )
    @app_commands.describe(message="Giveaway message ID or link", host="The new host")
    @commands.has_permissions(manage_guild=True)
    async def edit_host(self, ctx: Ctx, message: discord.Message, host: discord.User) -> None:
        ctx = require_context(ctx)
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        await database(self.bot).set_giveaway_host(message.id, host.id)
        await self.refresh(ctx, message, replace(row, host_id=host.id))

    @edit.command(  # type: ignore[arg-type]
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
        row = await self.active_giveaway(ctx, message)
        if row is None:
            return
        await database(self.bot).set_giveaway_winners(message.id, winners)
        await self.refresh(ctx, message, replace(row, winners=winners))

    @giveaway.group(  # type: ignore[arg-type]
        name="requirements",
        description="Add, replace or remove who can enter a giveaway.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements(self, ctx: Ctx) -> None:
        ctx = require_context(ctx)
        await ctx.warn("Use `add`, `remove`, or `edit`. Flags: `role`, `ignore`, `server`.")

    @requirements.command(  # type: ignore[arg-type]
        name="add",
        description="Add roles or servers to a giveaway's requirements.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type",
        value="Roles, or Discord invites like https://discord.gg/aspect",
    )
    @app_commands.choices(
        flag=[
            app_commands.Choice(name="Role", value="role"),
            app_commands.Choice(name="Ignore", value="ignore"),
            app_commands.Choice(name="Server", value="server"),
        ]
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

    @requirements.command(  # type: ignore[arg-type]
        name="edit",
        description="Replace one requirement of a giveaway with a new list.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type",
        value="Roles, or Discord invites like https://discord.gg/aspect",
    )
    @app_commands.choices(
        flag=[
            app_commands.Choice(name="Role", value="role"),
            app_commands.Choice(name="Ignore", value="ignore"),
            app_commands.Choice(name="Server", value="server"),
        ]
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

    @requirements.command(  # type: ignore[arg-type]
        name="remove",
        description="Remove roles or servers from a giveaway's requirements.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type",
        value="Roles/invites to remove, or `all` to clear",
    )
    @app_commands.choices(
        flag=[
            app_commands.Choice(name="Role", value="role"),
            app_commands.Choice(name="Ignore", value="ignore"),
            app_commands.Choice(name="Server", value="server"),
        ]
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
