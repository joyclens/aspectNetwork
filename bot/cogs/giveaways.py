from __future__ import annotations

import contextlib
import logging
import random
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
MAX_ROLES = 5
MAX_SERVERS = 3
PARTICIPANT_PAGE = 40
JOIN_ID = "giveaway:join"
PARTICIPANTS_ID = "giveaway:participants"
PARTICIPANTS_ENDED_ID = "giveaway:participants_ended"
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
FLAG_CHOICES = [
    app_commands.Choice(name="Role", value="role"),
    app_commands.Choice(name="Ignore", value="ignore"),
    app_commands.Choice(name="Server", value="server"),
]


def mention_user(user_id: int) -> str:
    return f"<@{user_id}>"


def mention_roles(role_ids: list[int]) -> str:
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def timestamp(moment: datetime) -> str:
    value = int(moment.timestamp())
    return f"<t:{value}:f> (<t:{value}:R>)"


def parse_flags(prize: str) -> tuple[str, dict[str, str]]:
    flags = {
        match["flag"].lower(): match["value"].strip() for match in FLAG_PATTERN.finditer(prize)
    }
    return " ".join(FLAG_PATTERN.sub("", prize).split()), flags


def invite_code(token: str) -> str | None:
    cleaned = token.strip().strip("<>").rstrip(".,);]")
    if cleaned.isdigit():
        return None
    match = INVITE_PATTERN.search(cleaned)
    if match is not None:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-]{2,32}", cleaned):
        return cleaned
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


def merge_ids(current: list[int], added: list[int], mode: Mode) -> list[int]:
    if mode == "remove":
        return [item for item in current if item not in added]
    if mode == "edit":
        return added
    return list(dict.fromkeys([*current, *added]))


def merge_servers(
    current: list[SponsoredServer],
    added: list[SponsoredServer],
    mode: Mode,
) -> list[SponsoredServer]:
    if mode == "remove":
        drop = {server.invite for server in added}
        return [server for server in current if server.invite not in drop]
    if mode == "edit":
        return added
    return list({server.invite: server for server in [*current, *added]}.values())


def draw_winners(entries: list[int], count: int) -> list[int]:
    pool = list(dict.fromkeys(entries))
    if len(pool) < count:
        return []
    return random.sample(pool, count)


def entry_block(member: discord.Member, row: Giveaway) -> str | None:
    blocked = next(
        (role_id for role_id in row.ignore_roles or [] if member.get_role(role_id)),
        None,
    )
    if blocked is not None:
        return f"You can't join this giveaway with {mention_roles([blocked])}."
    if row.required_roles and not any(member.get_role(role_id) for role_id in row.required_roles):
        return "You need one of these roles to join: " + mention_roles(row.required_roles)
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
            + mention_roles(row.required_roles)
        )
    if row.ignore_roles:
        lines.append(
            "<:userSlash:1559577141216157746> **Restricted Role:** "
            + mention_roles(row.ignore_roles)
        )
    return "\n".join(lines) if lines else None


class JoinButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            emoji=discord.PartialEmoji(name="confetti", id=1551256166074687519),
            style=discord.ButtonStyle.gray,
            custom_id=JOIN_ID,
        )

    async def callback(self, interaction: Interaction) -> None:
        await handle_join(interaction)


class ParticipantsButton(ui.Button[Any]):
    def __init__(self, *, ended: bool = False) -> None:
        super().__init__(
            label="Participants",
            style=discord.ButtonStyle.secondary,
            custom_id=PARTICIPANTS_ENDED_ID if ended else PARTICIPANTS_ID,
        )
        self.ended = ended

    async def callback(self, interaction: Interaction) -> None:
        await show_participants(interaction, ended=self.ended)


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
            await reply(interaction, "This giveaway does not exist or has been removed.")
            return
        members = [user_id for user_id in row.members if user_id != self.member_id]
        await db.set_giveaway_members(self.message.id, members)
        await edit_giveaway(self.bot, self.message, replace(row, members=members))
        await reply(interaction, "You left the giveaway.")


def _layout_items(
    row: Giveaway,
    *,
    ended: bool,
    winners: str | None,
) -> list[ui.Item[Any]]:
    moment = datetime.now(UTC) if ended else row.finish
    label = "Ended" if ended else "Duration"
    winner_line = (
        f"<:confetti:1551256166074687519>  **Winners:** {winners}"
        if winners is not None
        else f"<:confetti:1551256166074687519>  **Winners:** `{row.winners}`"
    )
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(
            f"## <:giveaway:1551256171728347279> {row.title}\n"
            f"{winner_line}\n"
            f"<:event:1551256173901250580> **{label}:** {timestamp(moment)}\n"
            f"<:people:1551256195585540306> **Entries:** `{len(set(row.members)):,}`"
        )
    ]
    reqs = requirements_text(row)
    if reqs is not None:
        items.extend([ui.Separator(visible=True), ui.TextDisplay(reqs)])
    items.extend(
        [
            ui.Separator(visible=True),
            ui.TextDisplay(
                "-# <:person:1551256197456330813> Giveaway hosted by " + mention_user(row.host_id)
            ),
        ]
    )
    if ended:
        items.append(ui.ActionRow(ParticipantsButton(ended=True)))
    else:
        items.append(ui.ActionRow(JoinButton(), ParticipantsButton()))
    items.append(ui.MediaGallery(discord.MediaGalleryItem(FOOTER)))
    return items


def giveaway_layout(
    row: Giveaway,
    *,
    ended: bool = False,
    winners: str | None = None,
) -> AspectLayout:
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*_layout_items(row, ended=ended, winners=winners)))
    return view


def register_persistent_views(bot: Aspect) -> None:
    active = AspectLayout(timeout=None)
    active.add_item(ui.Container(ui.ActionRow(JoinButton(), ParticipantsButton())))
    ended = AspectLayout(timeout=None)
    ended.add_item(ui.Container(ui.ActionRow(ParticipantsButton(ended=True))))
    bot.add_view(active)
    bot.add_view(ended)


async def reply(interaction: Interaction, text: str) -> None:
    await interaction.followup.send(
        view=container_view(ui.TextDisplay(text)),
        ephemeral=True,
    )


async def client_of(interaction: Interaction) -> Aspect | None:
    client = interaction.client
    if not isinstance(client, Aspect):
        return None
    try:
        database(client)
    except DatabaseUnavailable as exc:
        await report_interaction(interaction, exc, where="Database")
        return None
    return client


async def edit_giveaway(bot: Aspect, message: discord.Message, row: Giveaway) -> None:
    try:
        await message.edit(view=giveaway_layout(row))
    except discord.HTTPException:
        logger.warning("Could not refresh giveaway message %s", message.id)


async def show_participants(interaction: Interaction, *, ended: bool) -> None:
    client = await client_of(interaction)
    message = interaction.message
    if client is None or message is None:
        return
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    db = database(client)
    if ended:
        members = await db.ended_giveaway(message.channel.id, message.id)
    elif interaction.guild is None:
        return
    else:
        row = await db.giveaway(interaction.guild.id, message.id)
        members = None if row is None else row.members
    if members is None:
        await reply(interaction, "This giveaway does not exist.")
        return
    if not members:
        await reply(interaction, "This giveaway has no participants yet.")
        return
    unique = list(dict.fromkeys(members))
    body = "\n".join(mention_user(user_id) for user_id in unique[:PARTICIPANT_PAGE])
    if len(unique) > PARTICIPANT_PAGE:
        body += f"\n…and {len(unique) - PARTICIPANT_PAGE} more"
    await reply(interaction, f"## Participants\n{body}")


async def handle_join(interaction: Interaction) -> None:
    client = await client_of(interaction)
    member = interaction.user
    message = interaction.message
    if (
        client is None
        or interaction.guild is None
        or message is None
        or not isinstance(member, discord.Member)
    ):
        return
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    db = database(client)
    row = await db.giveaway(interaction.guild.id, message.id)
    if row is None:
        await reply(interaction, "This giveaway does not exist or has been removed.")
        return
    if reason := entry_block(member, row):
        await reply(interaction, reason)
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
    await edit_giveaway(client, message, replace(row, members=members))
    text = "You joined the giveaway."
    if reminder := server_reminder(row):
        text = f"{text}\n{reminder}"
    await reply(interaction, text)


async def fetch_message(bot: Aspect, row: Giveaway) -> discord.Message | None:
    guild = bot.get_guild(row.guild_id)
    if guild is None:
        try:
            guild = await bot.fetch_guild(row.guild_id)
        except discord.HTTPException:
            return None
    try:
        channel = guild.get_channel(row.channel_id) or await bot.fetch_channel(row.channel_id)
    except discord.HTTPException:
        return None
    if not isinstance(channel, discord.TextChannel):
        return None
    try:
        return await channel.fetch_message(row.message_id)
    except discord.HTTPException:
        return None


async def end_giveaway(bot: Aspect, row: Giveaway) -> None:
    winners = draw_winners(row.members, row.winners)
    result = ", ".join(mention_user(user_id) for user_id in winners) if winners else "None"
    message = await fetch_message(bot, row)
    if message is None:
        logger.warning("Ending giveaway %s without updating its message", row.message_id)
    else:
        try:
            await message.edit(view=giveaway_layout(row, ended=True, winners=result))
        except discord.HTTPException:
            logger.warning("Could not edit ended giveaway %s", row.message_id)
        else:
            if winners:
                with contextlib.suppress(discord.HTTPException):
                    await message.reply(
                        f"**{row.title}** winners:\n"
                        + "\n".join(f"{mention_user(user_id)} (`{user_id}`)" for user_id in winners)
                    )
    await database(bot).store_ended_giveaway(row.channel_id, row.message_id, row.members)


class Giveaways(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        register_persistent_views(self.bot)
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

    async def require_giveaway(self, ctx: Ctx, message: discord.Message) -> Giveaway | None:
        reply = require_context(ctx)
        if reply.guild is None:
            return None
        row = await database(self.bot).giveaway(reply.guild.id, message.id)
        if row is None:
            await reply.warn("This message is not a giveaway or it already ended.")
        return row

    async def updated(self, ctx: Ctx, message: discord.Message, row: Giveaway) -> None:
        await edit_giveaway(self.bot, message, row)
        await require_context(ctx).approve(f"Updated [giveaway]({message.jump_url}).")

    async def parse_role_ids(self, ctx: Ctx, raw: str) -> list[int] | None:
        reply = require_context(ctx)
        converter = commands.RoleConverter()
        try:
            return [(await converter.convert(ctx, token)).id for token in raw.split()]
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
                    f"Invalid Discord invite: `{token}`. "
                    "Use a link like `https://discord.gg/aspect`."
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
        if flag not in {"role", "ignore", "server"}:
            await reply.warn("Invalid flag. Use `role`, `ignore`, or `server`.")
            return
        row = await self.require_giveaway(ctx, message)
        if row is None:
            return
        db = database(self.bot)
        if flag == "server":
            current = list(row.required_servers or [])
            if mode == "remove" and value.lower() == "all":
                servers: list[SponsoredServer] = []
            else:
                parsed = await self.parse_servers(ctx, value)
                if parsed is None:
                    return
                servers = merge_servers(current, parsed, mode)
            if len(servers) > MAX_SERVERS:
                await reply.warn(f"You can only set up to {MAX_SERVERS} sponsored servers.")
                return
            await db.set_giveaway_servers(message.id, servers or None)
            await self.updated(ctx, message, replace(row, required_servers=servers or None))
            return
        column = "required_roles" if flag == "role" else "ignore_roles"
        current_ids = list((row.required_roles if flag == "role" else row.ignore_roles) or [])
        if mode == "remove" and value.lower() == "all":
            ids: list[int] = []
        else:
            parsed_ids = await self.parse_role_ids(ctx, value)
            if parsed_ids is None:
                return
            ids = merge_ids(current_ids, parsed_ids, mode)
        if len(ids) > MAX_ROLES:
            label = "required roles" if flag == "role" else "restricted roles"
            await reply.warn(f"You can only set up to {MAX_ROLES} {label}.")
            return
        await db.set_giveaway_roles(message.id, column, ids or None)
        next_row = (
            replace(row, required_roles=ids or None)
            if flag == "role"
            else replace(row, ignore_roles=ids or None)
        )
        await self.updated(ctx, message, next_row)

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
        if ctx.guild is None:
            return
        rows = await database(self.bot).giveaways(ctx.guild.id)
        if not rows:
            await ctx.warn("There are no active giveaways.")
            return
        lines = [
            f"[**{row.title}**](https://discord.com/channels/{ctx.guild.id}/"
            f"{row.channel_id}/{row.message_id}) ends {timestamp(row.finish)}"
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
        required_roles = [role.id] if role is not None else None
        ignore_roles = [ignore.id] if ignore is not None else None
        required_servers: list[SponsoredServer] | None = None
        if required_roles is None and "role" in flags:
            ids = await self.parse_role_ids(ctx, flags["role"])
            if ids is None:
                return
            if len(ids) > MAX_ROLES:
                await ctx.warn(f"You can only set up to {MAX_ROLES} required roles.")
                return
            required_roles = ids
        if ignore_roles is None and "ignore" in flags:
            ids = await self.parse_role_ids(ctx, flags["ignore"])
            if ids is None:
                return
            if len(ids) > MAX_ROLES:
                await ctx.warn(f"You can only set up to {MAX_ROLES} restricted roles.")
                return
            ignore_roles = ids
        if "server" in flags:
            servers = await self.parse_servers(ctx, flags["server"])
            if servers is None:
                return
            if len(servers) > MAX_SERVERS:
                await ctx.warn(f"You can only set up to {MAX_SERVERS} sponsored servers.")
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
        row = await self.require_giveaway(ctx, message)
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
        if await self.require_giveaway(ctx, message) is None:
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
        if not picks:
            await ctx.warn(
                f"Not enough participants to reroll {winners} winners. "
                f"There are only {len(set(members))} entries."
            )
            return
        await ctx.approve(
            "**New winners:** " + ", ".join(mention_user(user_id) for user_id in picks)
        )

    @giveaway.group(  # type: ignore[arg-type]
        name="edit",
        description="Change the prize, time, host or winners of a running giveaway.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def edit(self, ctx: Ctx) -> None:
        await require_context(ctx).warn("Use `prize`, `duration`, `host`, or `winners`.")

    @edit.command(  # type: ignore[arg-type]
        name="prize",
        description="Change the prize of a running giveaway.",
    )
    @app_commands.describe(message="Giveaway message ID or link", prize="The new prize")
    @commands.has_permissions(manage_guild=True)
    async def edit_prize(self, ctx: Ctx, message: discord.Message, *, prize: str) -> None:
        ctx = require_context(ctx)
        row = await self.require_giveaway(ctx, message)
        if row is None:
            return
        title = " ".join(prize.split())
        if len(title) < 2:
            await ctx.warn("That prize is not valid.")
            return
        await database(self.bot).set_giveaway_title(message.id, title)
        await self.updated(ctx, message, replace(row, title=title))

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
        row = await self.require_giveaway(ctx, message)
        if row is None:
            return
        finish = datetime.now(UTC) + timedelta(seconds=await Duration().convert(ctx, duration))
        await database(self.bot).set_giveaway_finish(message.id, finish)
        await self.updated(ctx, message, replace(row, finish=finish))

    @edit.command(  # type: ignore[arg-type]
        name="host",
        description="Change who is shown as the host of a running giveaway.",
    )
    @app_commands.describe(message="Giveaway message ID or link", host="The new host")
    @commands.has_permissions(manage_guild=True)
    async def edit_host(self, ctx: Ctx, message: discord.Message, host: discord.User) -> None:
        ctx = require_context(ctx)
        row = await self.require_giveaway(ctx, message)
        if row is None:
            return
        await database(self.bot).set_giveaway_host(message.id, host.id)
        await self.updated(ctx, message, replace(row, host_id=host.id))

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
        row = await self.require_giveaway(ctx, message)
        if row is None:
            return
        await database(self.bot).set_giveaway_winners(message.id, winners)
        await self.updated(ctx, message, replace(row, winners=winners))

    @giveaway.group(  # type: ignore[arg-type]
        name="requirements",
        description="Add, replace or remove who can enter a giveaway.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def requirements(self, ctx: Ctx) -> None:
        await require_context(ctx).warn(
            "Use `add`, `remove`, or `edit`. Flags: `role`, `ignore`, `server`."
        )

    @requirements.command(  # type: ignore[arg-type]
        name="add",
        description="Add roles or servers to a giveaway's requirements.",
    )
    @app_commands.describe(
        message="Giveaway message ID or link",
        flag="Requirement type",
        value="Roles, or Discord invites like https://discord.gg/aspect",
    )
    @app_commands.choices(flag=FLAG_CHOICES)
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
    @app_commands.choices(flag=FLAG_CHOICES)
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
    @app_commands.choices(flag=FLAG_CHOICES)
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
