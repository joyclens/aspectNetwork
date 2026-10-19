from __future__ import annotations

import io
import logging
import re
from typing import Any

import aiohttp
import discord
from discord import app_commands, ui
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.database import Ticket
from bot.core.ids import Channels, Emojis, Roles, Secrets, partial_emoji
from bot.services.cookie import CookieError
from bot.shared.checks import database
from bot.shared.context import Confirmation, PromptDeclined, require_context
from bot.shared.errors import DatabaseUnavailable, report_interaction
from bot.shared.layout import AspectLayout, container_view
from bot.shared.persistence import (
    PersistentView,
    disable_view,
    register_persistent,
    unregister_persistent,
)

logger = logging.getLogger("aspect")

FOOTER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png?ex=6ad54760&is=6ad3f5e0&hm=a620cfc6a45f8943e51320363b156c32491524ee8f70116a5cc52fa43faa96c3&"
DASHBOARD_BANNER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553891838950375454/dashboard.png?ex=6ad5440c&is=6ad3f28c&hm=72c2679975b0d1a9a4edd0991deefecdea82a8a178140c56d92e910056e2f90a&"
SUPPORT_BANNER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553891882709291130/support.png?ex=6ad54416&is=6ad3f296&hm=9960a0f7ad85b6bf03112fecbcf4e5c84fc828d2db653dce1ef1728185f76974&"
TICKET_FOOTER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553891965811167284/image.png?ex=6ad5442a&is=6ad3f2aa&hm=9728bf0ce6a60564553ac7b4129c5a0d77d5ddb1cc86b1cce2b6188ab1f6d68a&"
REGULATIONS_BANNER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553891837926838322/regulations.png?ex=6ad5440c&is=6ad3f28c&hm=cf40f0c47129a3c4016d86fca046294aa01128162fd8380cf47141d223496fe3&"
PACKAGES_BANNER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553891841181622362/packages.png?ex=6ad5440c&is=6ad3f28c&hm=c14adb4890683dbf81532b1a986ba58fce6cabf4ef2719957d988bfb0d362a7b&"

_SLUG = re.compile(r"[^a-z0-9-]+")


def channel_slug(value: str) -> str:
    cleaned = _SLUG.sub("-", value.lower().replace(" ", "-")).strip("-")
    return cleaned[:90] or "ticket"


def ticket_channel_name(owner_name: str, *, claimed: bool) -> str:
    return f"{'🟢' if claimed else '🔴'}・{owner_name}"[:100]


def tickets_cog(interaction: discord.Interaction[Any]) -> Tickets | None:
    client = interaction.client
    if not isinstance(client, Aspect):
        return None
    cog = client.get_cog("Tickets")
    return cog if isinstance(cog, Tickets) else None


def regulations_view() -> ui.LayoutView:
    view = ui.LayoutView()
    view.add_item(
        ui.Container(
            ui.MediaGallery(discord.MediaGalleryItem(REGULATIONS_BANNER)),
            ui.TextDisplay(f"## {Emojis.regulations} Aspect Network Regulations"),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Respect**\n"
                "-# In **Aspect Network**, you must respect others regardless of race, "
                "gender, ethnicity, sexuality, and any other factors they themself "
                "don't have control over. Harassment and discrimination are not "
                "welcome here.\n"
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**NSFW Content and Image Usages**\n"
                "-# Not Safe for Work "
                "([urban dictionary]"
                "(https://www.urbandictionary.com/define.php"
                "?term=Not%20Safe%20for%20Work)) "
                "content is prohibited inside of **Aspect Network**. Sending NSFW "
                "content will result in a ban. Using images to harass or discriminate "
                "against someone will result in moderation."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Relevance**\n"
                "-# Use relevant channels and categories for commands, media, "
                "advertising, and discussion.\n"
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Self Promotion**\n"
                "-# Self Promotion must be done in advertising channels. Self "
                "Promoting in a main channel will result in moderation."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Common Sense**\n"
                "-# Use common sense within **Aspect Network** and act responsibly.\n"
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Protection of Assets**\n"
                "-# Please do not steal, copy, or misuse our assets. **Aspect Network** "
                "is a registered trademark, and our embeds and bots are protected by "
                "copyright and intellectual property laws."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Other Regulations**\n"
                "-# While using **Aspect Network**, you must adhere to "
                "[**Discord's Terms of Service**](https://discord.com/terms) and "
                "[**Discord's Community Guidelines**](https://discord.com/guidelines). "
                "Our Marketplace Terms of Service can be found in the "
                f"{Emojis.marketplace} **Aspect Marketplace**."
            ),
            ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
        )
    )
    return view


def packages_view() -> ui.LayoutView:
    view = ui.LayoutView()
    view.add_item(
        ui.Container(
            ui.MediaGallery(discord.MediaGalleryItem(PACKAGES_BANNER)),
            ui.TextDisplay(f"## {Emojis.regulations} Packages Terms of Service"),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**No-Refund Policy**\n"
                "-# All purchases and completed orders are non-refundable. Please "
                "inspect and test all delivered products before agreeing to close "
                "your order ticket. Once the ticket is closed, no refunds, exchanges, "
                "or credits will be issued."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Asset Ownership & Liability**\n"
                "-# Once an order is delivered and the ticket is closed, the client is "
                "responsible for keeping their files safe. **Aspect Network** is not "
                "responsible for lost, corrupted, or deleted files, and is not "
                "required to store backups or resend assets."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Redistribution & Reselling**\n"
                "-# Reselling, leaking, sharing, or redistributing any assets "
                "purchased from **Aspect Network** is strictly prohibited without "
                "written permission from management or the creator. Violations may "
                "result in a permanent blacklist and reports to partner networks."
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(
                "**Terms of Service Updates**\n"
                "-# **Aspect Network** reserves the right to update these Terms of "
                "Service at any time. Clients are responsible for reviewing the terms "
                "before opening an order ticket. Opening a ticket or making a payment "
                "means you agree to the current terms."
            ),
            ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
        )
    )
    return view


class ClaimButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Claim",
            style=discord.ButtonStyle.secondary,
            custom_id="support:claim",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        await cog.claim_button(interaction)


class UnclaimButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Unclaim",
            style=discord.ButtonStyle.secondary,
            custom_id="support:unclaim",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        await cog.unclaim_button(interaction)


class CloseButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Close",
            style=discord.ButtonStyle.danger,
            # LEGACY custom_id — do not rename; live ticket panels use this.
            custom_id="closeSupport:button",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        await cog.close_button(interaction)


class EscalateButton(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Escalate",
            style=discord.ButtonStyle.secondary,
            custom_id="support:escalate",
            disabled=True,
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.send_message(
            view=container_view(ui.TextDisplay("Escalation is not available yet.")),
            ephemeral=True,
        )


def ticket_actions(*, claimed: bool = False) -> ui.ActionRow[Any]:
    claim = UnclaimButton() if claimed else ClaimButton()
    return ui.ActionRow(claim, CloseButton(), EscalateButton())


def ticket_message(
    number: int,
    owner: discord.abc.User | discord.Member,
    reason: str,
    *,
    claimed: bool = False,
) -> AspectLayout:
    view = AspectLayout(timeout=None)
    view.add_item(
        ui.Container(
            ui.MediaGallery(discord.MediaGalleryItem(SUPPORT_BANNER)),
            ui.TextDisplay(
                f"# Ticket #{number:03d}\n"
                f"Hello **{owner.mention}!** Thanks for contacting **Aspect Support**. "
                "Please provide all necessary details and avoid pinging Support members. "
                "Thank you for your patience!\n"
                f"# Inquiry:\n{reason}"
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ticket_actions(claimed=claimed),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.MediaGallery(discord.MediaGalleryItem(TICKET_FOOTER)),
        )
    )
    return view


def claim_notice(member: discord.Member) -> AspectLayout:
    return container_view(
        ui.TextDisplay(f"{member.mention} has claimed this ticket, they'll be assisting you today.")
    )


def unclaim_notice(member: discord.Member) -> AspectLayout:
    return container_view(
        ui.TextDisplay(
            f"{member.mention} has unclaimed this ticket, please wait for someone to claim it."
        )
    )


def ticket_panel_view() -> AspectLayout:
    panel = AspectLayout(timeout=None)
    panel.add_item(
        ui.Container(ui.ActionRow(ClaimButton(), UnclaimButton(), CloseButton(), EscalateButton()))
    )
    return panel


class GetHelp(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Get Support",
            style=discord.ButtonStyle.primary,
            emoji=partial_emoji(Emojis.support),
            custom_id="support:gethelp",
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.send_modal(SupportModal())


class DashboardMenu(ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            custom_id="dashboard:menu",
            placeholder="Select an option",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Discord Regulations",
                    value="discord_regulations",
                    emoji=partial_emoji(Emojis.regulations),
                ),
                discord.SelectOption(
                    label="Package ToS",
                    value="package_tos",
                    emoji=partial_emoji(Emojis.package),
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        if self.values and self.values[0] == "discord_regulations":
            await interaction.response.send_message(view=regulations_view(), ephemeral=True)
            return
        if self.values and self.values[0] == "package_tos":
            await interaction.response.send_message(view=packages_view(), ephemeral=True)
            return
        await interaction.response.send_message(
            view=container_view(ui.TextDisplay("That option is not available.")),
            ephemeral=True,
        )


class Dashboard(AspectLayout):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            ui.Container(
                ui.MediaGallery(discord.MediaGalleryItem(DASHBOARD_BANNER)),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.TextDisplay(
                    f"{Emojis.aspect} **Aspect Network** is the upcoming, biggest "
                    "and purest network. From it's fresh branding to incredible hard working "
                    "staff, we do our best to connect server owners with the right people to "
                    "help their servers grow. Here at Aspect Network we want young and new "
                    "server owners to make the most of their time and to help gain them "
                    "attention."
                ),
                ui.ActionRow(
                    GetHelp(),
                    ui.Button(
                        label="Our Roblox Group",
                        style=discord.ButtonStyle.link,
                        url=("https://www.roblox.com/communities/719648172/Aspect-Network#!/about"),
                    ),
                ),
                ui.ActionRow(DashboardMenu()),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
            )
        )


class SupportModal(ui.Modal, title="General Support - Reason"):
    def __init__(self) -> None:
        super().__init__()
        reason: ui.TextInput[Any] = ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="Enter the reason for your ticket.",
            required=True,
            min_length=3,
            max_length=1000,
        )
        kind: ui.Select[Any] = ui.Select(
            placeholder="Make a selection",
            min_values=1,
            max_values=1,
            required=True,
            options=[
                discord.SelectOption(label="General Support", value="general"),
                discord.SelectOption(label="Management", value="management"),
            ],
        )
        self.add_item(ui.Label(text="Please describe your issue", component=reason))
        self.add_item(ui.Label(text="Support Type", component=kind))
        self._reason = reason
        self._kind = kind

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        reason = " ".join(str(self._reason.value).split())
        kind = self._kind.values[0] if self._kind.values else ""
        if not 3 <= len(reason) <= 1000 or kind not in {"general", "management"}:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("That ticket submission is not valid.")),
                ephemeral=True,
            )
            return
        await cog.open_ticket(interaction, kind=kind, reason=reason)


class CloseRequest(AspectLayout):
    def __init__(self, owner_id: int, staff_id: int, reason: str) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.staff_id = staff_id
        accept: ui.Button[Any] = ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id="ticket:closerequest:accept",
        )
        deny: ui.Button[Any] = ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
            custom_id="ticket:closerequest:deny",
        )

        async def on_accept(interaction: discord.Interaction[Any]) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message(
                    view=container_view(ui.TextDisplay("Only the ticket owner can accept.")),
                    ephemeral=True,
                )
                return
            cog = tickets_cog(interaction)
            if cog is None:
                await interaction.response.send_message(
                    view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                    ephemeral=True,
                )
                return
            await interaction.response.defer()
            self.stop()
            await cog.close_ticket(interaction, closed_by=self.staff_id)

        async def on_deny(interaction: discord.Interaction[Any]) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message(
                    view=container_view(ui.TextDisplay("Only the ticket owner can deny.")),
                    ephemeral=True,
                )
                return
            self.stop()
            await interaction.response.edit_message(
                view=container_view(ui.TextDisplay("The close request was **denied**.")),
            )

        accept.callback = on_accept  # type: ignore[method-assign]
        deny.callback = on_deny  # type: ignore[method-assign]
        self.add_item(
            ui.Container(
                ui.TextDisplay(
                    f"## Close Request\n"
                    f"Hello **{owner.mention}!** <@{staff_id}> has requested to close this ticket, please use the "
                    "buttons below to either accept or deny.",
                ),
                ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.large,
                ),
                ui.TextDisplay(f"```\n{reason}\n```"),
                ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.large,
                ),
                ui.ActionRow(accept, deny),
            )
        )

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            view=container_view(ui.TextDisplay("Only the ticket owner can use this.")),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        await disable_view(self)


class Tickets(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._dashboard_id: int | None = None
        self._persistent: list[PersistentView] = []

    async def cog_load(self) -> None:
        self._persistent = [
            register_persistent(self.bot, Dashboard()),
            register_persistent(self.bot, ticket_panel_view()),
        ]

    async def cog_unload(self) -> None:
        for view in self._persistent:
            unregister_persistent(self.bot, view)
        self._persistent.clear()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.user is not None:
            await self.ensure_dashboard()

    def is_staff(self, member: discord.Member) -> bool:
        role_id = Roles.ticket_support
        return member.guild_permissions.manage_channels or (
            role_id is not None and member.get_role(role_id) is not None
        )

    async def require_ticket(self, ctx: Any) -> Ticket | None:
        db = database(self.bot)
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.warn("This is not a ticket channel.")
            return None
        ticket = await db.ticket(ctx.channel.id)
        if ticket is None:
            await ctx.warn("This is not a ticket channel.")
            return None
        return ticket

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="ticket",
        fallback="claim",
        description="Claim the current support ticket.",
    )
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def ticket(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member):
            return
        panel = (
            await self.find_ticket_panel(ctx.channel)
            if isinstance(ctx.channel, discord.TextChannel)
            else None
        )
        await self.claim_ticket(ctx.channel, ctx.author, reply=ctx, panel=panel)

    @ticket.command(  # type: ignore[arg-type]
        name="add",
        description="Add a member to the current ticket.",
    )
    @app_commands.describe(user="Member to add")
    async def add(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        if await self.require_ticket(ctx) is None:
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        await ctx.channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            reason="Added to ticket",
        )
        await ctx.approve(f"Added **{user.display_name}** to the ticket.")

    @ticket.command(  # type: ignore[arg-type]
        name="remove",
        description="Remove a member from the current ticket.",
    )
    @app_commands.describe(user="Member to remove")
    async def remove(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        ticket = await self.require_ticket(ctx)
        if ticket is None or not isinstance(ctx.channel, discord.TextChannel):
            return
        if user.id == ticket.owner_id:
            await ctx.warn("You cannot remove the ticket owner.")
            return
        await ctx.channel.set_permissions(user, overwrite=None, reason="Removed from ticket")
        await ctx.approve(f"Removed **{user.display_name}** from the ticket.")

    @ticket.command(  # type: ignore[arg-type]
        name="rename",
        description="Rename the current ticket channel.",
    )
    @app_commands.describe(name="New ticket name")
    async def rename(self, ctx: commands.Context[Any], *, name: str) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        ticket = await self.require_ticket(ctx)
        if ticket is None or not isinstance(ctx.channel, discord.TextChannel):
            return
        slug = channel_slug(name)
        if len(slug) < 2:
            await ctx.warn("That name is not valid.")
            return
        final = ticket_channel_name(slug, claimed=ticket.claimed_by is not None)
        await ctx.channel.edit(name=final, reason=f"Renamed by {ctx.author}")
        await ctx.approve(f"Renamed the ticket to **{final}**.")

    @ticket.command(  # type: ignore[arg-type]
        name="unclaim",
        description="Unclaim the current support ticket.",
    )
    async def unclaim(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member):
            return
        panel = (
            await self.find_ticket_panel(ctx.channel)
            if isinstance(ctx.channel, discord.TextChannel)
            else None
        )
        await self.unclaim_ticket(ctx.channel, ctx.author, reply=ctx, panel=panel)

    @ticket.command(  # type: ignore[arg-type]
        name="leaderboard",
        description="Show top support members by claims.",
    )
    @commands.has_permissions(manage_guild=True)
    async def leaderboard(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        rows = await database(self.bot).ticket_leaderboard()
        if not rows:
            await ctx.warn("No ticket claims have been recorded yet.")
            return
        lines = ["## Ticket Leaderboard", ""]
        for index, (user_id, claims) in enumerate(rows, start=1):
            member = ctx.guild.get_member(user_id) if ctx.guild else None
            label = member.display_name if member else f"User {user_id}"
            lines.append(f"`{index}.` **{label}** - `{claims:,}` claims")
        view = ui.LayoutView()
        view.add_item(ui.Container(ui.TextDisplay("\n".join(lines))))
        await ctx.send(view=view)

    @ticket.command(  # type: ignore[arg-type]
        name="remind",
        description="Remind the ticket owner their ticket is open.",
    )
    @commands.cooldown(1, 300, commands.BucketType.channel)
    async def remind(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        ticket = await self.require_ticket(ctx)
        if ticket is None or ctx.guild is None:
            return
        owner = ctx.guild.get_member(ticket.owner_id)
        if owner is None:
            await ctx.warn("The ticket owner is no longer in the server.")
            return
        try:
            await owner.send(
                view=container_view(
                    ui.TextDisplay(
                        "## Ticket Reminder\n"
                        f"Your ticket in **{ctx.guild.name}** is still open.\n"
                        f"Channel: `{ctx.channel}`"
                    )
                )
            )
        except discord.HTTPException:
            await ctx.warn("I could not DM the ticket owner.")
            return
        await ctx.approve(f"Reminded **{owner.display_name}**.")

    @ticket.command(  # type: ignore[arg-type]
        name="close",
        description="Transcript and close the current ticket.",
    )
    async def close(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        if await self.require_ticket(ctx) is None:
            return
        try:
            await ctx.prompt("Are you sure you want to close this ticket?")
        except PromptDeclined:
            return
        await ctx.approve("Closing this ticket...")
        await self.close_ticket(ctx, closed_by=ctx.author.id)

    @ticket.command(  # type: ignore[arg-type]
        name="closerequest",
        description="Ask the owner to confirm closing.",
    )
    @app_commands.describe(reason="Why this ticket should be closed")
    @commands.cooldown(1, 300, commands.BucketType.channel)
    async def closerequest(self, ctx: commands.Context[Any], *, reason: str) -> None:
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        ticket = await self.require_ticket(ctx)
        if ticket is None:
            return
        cleaned = " ".join(reason.split())
        if not 3 <= len(cleaned) <= 200:
            await ctx.warn("That reason is not valid.")
            return
        await ctx.send(
            view=CloseRequest(ticket.owner_id, ctx.author.id, cleaned),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def open_ticket(
        self,
        interaction: discord.Interaction[Any],
        *,
        kind: str,
        reason: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            db = database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        if (
            Roles.ticket_support is None
            or Channels.ticket_logs is None
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        if await db.open_ticket_count(interaction.user.id) > 0:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("You already have an open ticket.")),
                ephemeral=True,
            )
            return
        category = interaction.guild.get_channel(Channels.tickets_category)
        support = interaction.guild.get_role(Roles.ticket_support)
        me = interaction.guild.me
        if not isinstance(category, discord.CategoryChannel) or support is None or me is None:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        number = await db.next_ticket_number()
        overwrites: dict[
            discord.Role | discord.Member | discord.Object,
            discord.PermissionOverwrite,
        ] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
            ),
            support: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
            ),
            me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }
        try:
            channel = await category.create_text_channel(
                name=ticket_channel_name(interaction.user.name, claimed=False),
                overwrites=overwrites,
                reason="Ticket opened",
            )
            await db.create_ticket(
                channel.id,
                interaction.user.id,
                number,
                kind,
                reason,
            )
            await channel.send(
                f"{support.mention} | {interaction.user.mention}",
                allowed_mentions=discord.AllowedMentions(roles=True, users=True),
            )
            await channel.send(view=ticket_message(number, interaction.user, reason))
        except discord.HTTPException:
            logger.warning("Could not open a ticket for %s", interaction.user.id)
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("I could not open a ticket.")),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(ui.TextDisplay(f"Opened {channel.mention}.")),
            ephemeral=True,
        )

    def _button_reply(self, interaction: discord.Interaction[Any]) -> Any:
        class Reply:
            async def warn(self, text: str) -> None:
                await interaction.followup.send(
                    view=container_view(ui.TextDisplay(text)),
                    ephemeral=True,
                )

            async def approve(self, text: str) -> None:
                await interaction.followup.send(
                    view=container_view(ui.TextDisplay(text)),
                    ephemeral=True,
                )

        return Reply()

    async def find_ticket_panel(
        self,
        channel: discord.TextChannel,
    ) -> discord.Message | None:
        if self.bot.user is None:
            return None
        try:
            async for message in channel.history(limit=30):
                if message.author.id != self.bot.user.id:
                    continue
                raw = str(message.components)
                if "support:claim" in raw or "support:unclaim" in raw:
                    return message
        except discord.HTTPException:
            return None
        return None

    async def claim_button(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("You cannot manage tickets.")),
                ephemeral=True,
            )
            return
        try:
            database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This is not a ticket channel.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.claim_ticket(
            interaction.channel,
            interaction.user,
            reply=self._button_reply(interaction),
            panel=interaction.message,
        )

    async def unclaim_button(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("You cannot manage tickets.")),
                ephemeral=True,
            )
            return
        try:
            database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This is not a ticket channel.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.unclaim_ticket(
            interaction.channel,
            interaction.user,
            reply=self._button_reply(interaction),
            panel=interaction.message,
        )

    async def close_button(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member) or not self.is_staff(interaction.user):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("You cannot manage tickets.")),
                ephemeral=True,
            )
            return
        try:
            db = database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This is not a ticket channel.")),
                ephemeral=True,
            )
            return
        if await db.ticket(interaction.channel.id) is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This is not a ticket channel.")),
                ephemeral=True,
            )
            return
        prompt = Confirmation(
            interaction.user.id,
            "Are you sure you want to close this ticket?",
        )
        await interaction.response.send_message(view=prompt, ephemeral=True)
        await prompt.wait()
        if prompt.status is not True:
            try:
                await interaction.edit_original_response(
                    view=container_view(ui.TextDisplay("Close cancelled.")),
                )
            except discord.HTTPException:
                return
            return
        try:
            await interaction.edit_original_response(
                view=container_view(ui.TextDisplay("Closing this ticket...")),
            )
        except discord.HTTPException:
            pass
        await self.close_ticket(interaction, closed_by=interaction.user.id)

    async def _refresh_panel(
        self,
        panel: discord.Message | None,
        ticket: Ticket,
        owner: discord.abc.User | discord.Member,
        *,
        claimed: bool,
    ) -> None:
        if panel is None:
            return
        try:
            await panel.edit(
                view=ticket_message(ticket.number, owner, ticket.reason, claimed=claimed)
            )
        except discord.HTTPException:
            logger.warning("Could not refresh ticket panel %s", panel.id)

    async def claim_ticket(
        self,
        channel: discord.abc.Messageable,
        member: discord.Member,
        *,
        reply: Any,
        panel: discord.Message | None = None,
    ) -> None:
        db = database(self.bot)
        if not self.is_staff(member):
            await reply.warn("You cannot manage tickets.")
            return
        if not isinstance(channel, discord.TextChannel) or channel.guild is None:
            await reply.warn("This is not a ticket channel.")
            return
        ticket = await db.ticket(channel.id)
        if ticket is None:
            await reply.warn("This is not a ticket channel.")
            return
        if ticket.claimed_by is not None:
            await reply.warn("This ticket is already claimed.")
            return
        if not await db.claim_ticket(channel.id, member.id):
            await reply.warn("This ticket is already claimed.")
            return
        role_id = Roles.ticket_support
        role = channel.guild.get_role(role_id) if role_id else None
        try:
            if role is not None:
                await channel.set_permissions(
                    role,
                    view_channel=True,
                    send_messages=False,
                    reason="Ticket claimed",
                )
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                reason="Ticket claimed",
            )
            owner = channel.guild.get_member(ticket.owner_id)
            owner_ref: discord.abc.User | discord.Member
            if owner is not None:
                owner_ref = owner
            else:
                try:
                    owner_ref = await self.bot.fetch_user(ticket.owner_id)
                except discord.HTTPException:
                    owner_ref = member
            await channel.edit(
                name=ticket_channel_name(
                    owner.name if owner else str(ticket.owner_id),
                    claimed=True,
                ),
                reason="Ticket claimed",
            )
        except discord.HTTPException:
            await db.unclaim_ticket(channel.id)
            logger.exception("Could not apply claim permissions for %s", channel.id)
            await reply.warn("Could not claim this ticket.")
            return
        await self._refresh_panel(panel, ticket, owner_ref, claimed=True)
        try:
            await channel.send(
                view=claim_notice(member),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send claim notice in %s", channel.id)
        await reply.approve(f"**{member.display_name}** claimed this ticket.")

    async def unclaim_ticket(
        self,
        channel: discord.abc.Messageable,
        member: discord.Member,
        *,
        reply: Any,
        panel: discord.Message | None = None,
    ) -> None:
        db = database(self.bot)
        if not self.is_staff(member):
            await reply.warn("You cannot manage tickets.")
            return
        if not isinstance(channel, discord.TextChannel) or channel.guild is None:
            await reply.warn("This is not a ticket channel.")
            return
        ticket = await db.ticket(channel.id)
        if ticket is None:
            await reply.warn("This is not a ticket channel.")
            return
        if ticket.claimed_by is None:
            await reply.warn("This ticket is not claimed.")
            return
        if ticket.claimed_by != member.id and not member.guild_permissions.manage_guild:
            await reply.warn("You did not claim this ticket.")
            return
        role_id = Roles.ticket_support
        role = channel.guild.get_role(role_id) if role_id else None
        if role is not None:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                reason="Ticket unclaimed",
            )
        if ticket.claimed_by != member.id:
            previous = channel.guild.get_member(ticket.claimed_by)
            if previous is not None:
                await channel.set_permissions(previous, overwrite=None, reason="Ticket unclaimed")
        owner = channel.guild.get_member(ticket.owner_id)
        owner_ref: discord.abc.User | discord.Member
        if owner is not None:
            owner_ref = owner
        else:
            try:
                owner_ref = await self.bot.fetch_user(ticket.owner_id)
            except discord.HTTPException:
                owner_ref = member
        await channel.edit(
            name=ticket_channel_name(
                owner.name if owner else str(ticket.owner_id),
                claimed=False,
            ),
            reason="Ticket unclaimed",
        )
        await db.unclaim_ticket(channel.id)
        await self._refresh_panel(panel, ticket, owner_ref, claimed=False)
        try:
            await channel.send(
                view=unclaim_notice(member),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send unclaim notice in %s", channel.id)
        await reply.approve("This ticket is no longer claimed.")

    async def close_ticket(self, origin: Any, *, closed_by: int) -> None:
        channel = getattr(origin, "channel", None)
        guild = getattr(origin, "guild", None)
        if not isinstance(channel, discord.TextChannel) or guild is None:
            return
        db = database(self.bot)
        ticket = await db.ticket(channel.id)
        if ticket is None:
            return
        url: str | None = None
        if self.bot.cookie is not None:
            try:
                url = await self.bot.cookie.transcript(
                    channel.id,
                    Secrets.discord_token,
                    title=f"Ticket #{ticket.number:03d}",
                    description=f"{ticket.kind}: {ticket.reason[:200]}",
                )
            except CookieError as exc:
                logger.warning("Ticket transcript failed status=%s", exc.status)
        logs = guild.get_channel(Channels.ticket_logs or 0)
        owner = guild.get_member(ticket.owner_id)
        closer = guild.get_member(closed_by)
        claimed = guild.get_member(ticket.claimed_by) if ticket.claimed_by is not None else None
        owner_label = (
            f"{owner.mention} [`{owner.id}`]" if owner is not None else f"`{ticket.owner_id}`"
        )
        closer_label = (
            f"{closer.mention} [`{closer.id}`]" if closer is not None else f"`{closed_by}`"
        )
        claimed_label = (
            f"{claimed.mention} [`{claimed.id}`]"
            if claimed is not None
            else ("Unclaimed" if ticket.claimed_by is None else f"`{ticket.claimed_by}`")
        )
        body = (
            f"**Ticket:** `#{ticket.number:03d}`\n"
            f"**Type:** `{ticket.kind}`\n"
            f"**Channel:** `{channel.name}`\n"
            f"**Owner:** {owner_label}\n"
            f"**Closed by:** {closer_label}\n"
            f"**Claimed by:** {claimed_label}\n"
            f"**Opened:** <t:{int(ticket.created_at.timestamp())}:f>\n"
            f"**Inquiry:** {ticket.reason[:300]}"
        )
        if url is not None:
            body += f"\n**Transcript:** [View]({url})"
        closed_view = ui.LayoutView()
        items: list[ui.Item[Any]] = [
            ui.TextDisplay("## Ticket Closed\nA support ticket was closed."),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.TextDisplay(body),
        ]
        if url is not None:
            items.append(ui.ActionRow(ui.Button(label="View Transcript", url=url)))
        closed_view.add_item(ui.Container(*items))
        if isinstance(logs, discord.TextChannel):
            try:
                await logs.send(view=closed_view)
            except discord.HTTPException:
                logger.warning("Could not send ticket log")
        await self._dm_owner_closed(ticket, owner, closer, url)
        await db.delete_ticket(channel.id)
        try:
            await channel.delete(reason="Ticket closed")
        except discord.HTTPException:
            logger.warning("Could not delete ticket channel %s", channel.id)

    async def _transcript_attachment(self, url: str, number: int) -> discord.File | None:
        session = self.bot.session
        if session is None or session.closed:
            return None
        try:
            async with session.get(url) as response:
                if response.status >= 300:
                    await response.read()
                    return None
                data = await response.read()
        except (aiohttp.ClientError, OSError, TimeoutError):
            return None
        if not data:
            return None
        return discord.File(io.BytesIO(data), filename=f"ticket-{number:03d}.html")

    async def _dm_owner_closed(
        self,
        ticket: Ticket,
        owner: discord.Member | None,
        closer: discord.Member | None,
        url: str | None,
    ) -> None:
        user: discord.abc.User | None = owner
        if user is None:
            try:
                user = await self.bot.fetch_user(ticket.owner_id)
            except discord.HTTPException:
                return
        if not isinstance(user, discord.abc.Messageable):
            return
        staff = closer.mention if closer is not None else "staff"
        text = (
            "## Ticket Closed\n"
            f"Your ticket in **Aspect Network** has been closed by {staff}, "
            "thank you for contacting us today!\n\n"
            "If you require any more assistance, please don't hesitate to reach back out "
            f"via our <#{Channels.dashboard}> channel: you can view your full ticket "
            "transcript below."
        )
        items: list[ui.Item[Any]] = [
            ui.TextDisplay(text),
            ui.Separator(visible=True),
        ]
        files: list[discord.File] = []
        if url is not None:
            uploaded = await self._transcript_attachment(url, ticket.number)
            if uploaded is not None:
                items.append(ui.File(uploaded.uri))
                files.append(uploaded)
            else:
                items.append(ui.ActionRow(ui.Button(label="View Transcript", url=url)))
        items.append(ui.Separator(visible=True))
        items.append(ui.MediaGallery(discord.MediaGalleryItem(FOOTER)))
        try:
            await user.send(view=container_view(*items), files=files)
        except discord.HTTPException:
            logger.warning("Could not DM ticket owner %s", ticket.owner_id)

    async def ensure_dashboard(self) -> None:
        async with self.bot.lock_for("ticket-dashboard"):
            channel = self.bot.get_channel(Channels.dashboard)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(Channels.dashboard)
                except discord.HTTPException:
                    return
            if not isinstance(channel, discord.TextChannel) or self.bot.user is None:
                return
            if self._dashboard_id is not None:
                try:
                    await channel.fetch_message(self._dashboard_id)
                    return
                except discord.NotFound:
                    self._dashboard_id = None
                except discord.HTTPException:
                    return
            try:
                async for message in channel.history(limit=50):
                    if message.author.id != self.bot.user.id:
                        continue
                    raw = str(message.components)
                    if "support:gethelp" in raw or "dashboard:menu" in raw:
                        self._dashboard_id = message.id
                        return
            except discord.HTTPException:
                return
            try:
                sent = await channel.send(view=Dashboard())
            except discord.HTTPException:
                logger.warning("Could not send the dashboard")
                return
            self._dashboard_id = sent.id


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Tickets(bot))
