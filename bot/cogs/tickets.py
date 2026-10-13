from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.database import Ticket
from bot.services.cookie import CookieError
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.errors import DatabaseUnavailable, report_interaction
from bot.shared.layout import AspectLayout, container_view

logger = logging.getLogger("aspect")

DASHBOARD = 1529141669340123257
CATEGORY = 1531807371095969802
FOOTER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
    "?ex=6acf58a0&is=6ace0720&hm=4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
)
DASHBOARD_BANNER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553891838950375454/dashboard.png"
    "?ex=6acf554c&is=6ace03cc&hm=7bae21e2c184f04e878d8e4d291bb5bdb33814d38fa3592780167289c57bbb75&"
)
SUPPORT_BANNER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553891882709291130/support.png"
    "?ex=6acf5556&is=6ace03d6&hm=9a6006135f4301c18eeb5247356b40ce1f7b65239696d96c84bbe6c9431b2b63&"
)
TICKET_FOOTER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553891965811167284/image.png"
    "?ex=6acf556a&is=6ace03ea&hm=beb8934539bf5ab14f57905a39aaf4931ebec696e60f0f58d949b50fd796c0ad&"
)
REGULATIONS_BANNER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553891837926838322/regulations.png"
    "?ex=6acf554c&is=6ace03cc&hm=a343f05ec299ef049efbe10b6384eab3769e2324227af4b8a766e5b46bd8fb4c&"
)
PACKAGES_BANNER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553891841181622362/packages.png"
    "?ex=6acf554c&is=6ace03cc&hm=36294664a41021a89b3a9bb6257e67f97df102a981ef08081eb8dc86fa69538e&"
)

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
            ui.TextDisplay("## <:regulations:1556098910223728720> Aspect Network Regulations"),
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
                "<:marketplace:1551256187301797970> **Aspect Marketplace**."
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
            ui.TextDisplay("## <:regulations:1556098910223728720> Packages Terms of Service"),
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


def ticket_message(number: int, owner: discord.Member, reason: str) -> ui.LayoutView:
    view = ui.LayoutView()
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
            ui.ActionRow(
                ui.Button(
                    label="Claim",
                    style=discord.ButtonStyle.secondary,
                    custom_id="support:claim",
                ),
                ui.Button(
                    label="Close",
                    style=discord.ButtonStyle.danger,
                    custom_id="closeSupport:button",
                ),
                ui.Button(
                    label="Escalate",
                    style=discord.ButtonStyle.secondary,
                    custom_id="support:escalate",
                    disabled=True,
                ),
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.MediaGallery(discord.MediaGalleryItem(TICKET_FOOTER)),
        )
    )
    return view


class GetHelp(ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Get Support",
            style=discord.ButtonStyle.primary,
            emoji=discord.PartialEmoji(name="support", id=1556395385730367488),
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
                    emoji=discord.PartialEmoji(name="regulations", id=1556098910223728720),
                ),
                discord.SelectOption(
                    label="Package ToS",
                    value="package_tos",
                    emoji=discord.PartialEmoji(name="package", id=1551256156343636040),
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
                    "<:aspect:1553939826103947314> **Aspect Network** is the upcoming, biggest "
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


class TicketButtons(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Claim", style=discord.ButtonStyle.secondary, custom_id="support:claim")
    async def claim(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        await cog.claim_button(interaction)

    @ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="closeSupport:button")
    async def close(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        cog = tickets_cog(interaction)
        if cog is None:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Tickets are unavailable.")),
                ephemeral=True,
            )
            return
        await cog.close_button(interaction)

    @ui.button(
        label="Escalate",
        style=discord.ButtonStyle.secondary,
        custom_id="support:escalate",
        disabled=True,
    )
    async def escalate(
        self,
        interaction: discord.Interaction[Any],
        _button: ui.Button[Any],
    ) -> None:
        await interaction.response.send_message(
            view=container_view(ui.TextDisplay("Escalation is not available yet.")),
            ephemeral=True,
        )


class CloseRequest(AspectLayout):
    def __init__(self, owner_id: int, staff_id: int, reason: str) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.staff_id = staff_id
        accept: ui.Button[Any] = ui.Button(label="Accept", style=discord.ButtonStyle.success)
        deny: ui.Button[Any] = ui.Button(label="Deny", style=discord.ButtonStyle.danger)

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
                    f"## Close Request\nStaff asked to close this ticket.\n**Reason:** {reason}"
                ),
                ui.ActionRow(accept, deny),
            )
        )

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        return interaction.user.id == self.owner_id


class Tickets(commands.Cog):
    """Support ticket management for Aspect Network."""

    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._dashboard_id: int | None = None

    async def cog_load(self) -> None:
        self.bot.add_view(Dashboard())
        self.bot.add_view(TicketButtons())

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.user is not None:
            await self.ensure_dashboard()

    def is_staff(self, member: discord.Member) -> bool:
        role_id = self.bot.settings.ticket_support_role_id
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

    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.hybrid_group(name="ticket", fallback="claim")  # type: ignore[arg-type]
    async def ticket(self, ctx: commands.Context[Any]) -> None:
        """Claim the current support ticket."""
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member):
            return
        await self.claim_ticket(ctx.channel, ctx.author, reply=ctx)

    @ticket.command(name="add", description="Add a member to the current ticket.")  # type: ignore[arg-type]
    @app_commands.describe(user="Member to add")
    async def add(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        """Add a member to the current ticket."""
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

    @ticket.command(name="remove", description="Remove a member from the current ticket.")  # type: ignore[arg-type]
    @app_commands.describe(user="Member to remove")
    async def remove(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        """Remove a member from the current ticket."""
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

    @ticket.command(name="rename", description="Rename the current ticket channel.")  # type: ignore[arg-type]
    @app_commands.describe(name="New ticket name")
    async def rename(self, ctx: commands.Context[Any], *, name: str) -> None:
        """Rename the current ticket channel."""
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

    @ticket.command(name="unclaim", description="Unclaim the current support ticket.")  # type: ignore[arg-type]
    async def unclaim(self, ctx: commands.Context[Any]) -> None:
        """Unclaim the current support ticket."""
        ctx = require_context(ctx)
        db = database(self.bot)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        ticket = await self.require_ticket(ctx)
        if ticket is None or not isinstance(ctx.channel, discord.TextChannel) or ctx.guild is None:
            return
        if ticket.claimed_by is None:
            await ctx.warn("This ticket is not claimed.")
            return
        if ticket.claimed_by != ctx.author.id and not ctx.author.guild_permissions.manage_guild:
            await ctx.warn("You did not claim this ticket.")
            return
        role_id = self.bot.settings.ticket_support_role_id
        role = ctx.guild.get_role(role_id) if role_id else None
        if role is not None:
            await ctx.channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                reason="Ticket unclaimed",
            )
        owner = ctx.guild.get_member(ticket.owner_id)
        await ctx.channel.edit(
            name=ticket_channel_name(
                owner.name if owner else str(ticket.owner_id),
                claimed=False,
            ),
            reason="Ticket unclaimed",
        )
        await db.unclaim_ticket(ctx.channel.id)
        await ctx.approve("This ticket is no longer claimed.")

    @ticket.command(name="leaderboard", description="Show top support members by claims.")  # type: ignore[arg-type]
    @commands.has_permissions(manage_guild=True)
    async def leaderboard(self, ctx: commands.Context[Any]) -> None:
        """Show top support members by claims."""
        ctx = require_context(ctx)
        rows = await database(self.bot).ticket_leaderboard()
        if not rows:
            await ctx.warn("No ticket claims have been recorded yet.")
            return
        lines = ["## Ticket Leaderboard", ""]
        for index, (user_id, claims) in enumerate(rows, start=1):
            member = ctx.guild.get_member(user_id) if ctx.guild else None
            label = member.display_name if member else f"User {user_id}"
            lines.append(f"`{index}.` **{label}** — `{claims:,}` claims")
        view = ui.LayoutView()
        view.add_item(ui.Container(ui.TextDisplay("\n".join(lines))))
        await ctx.send(view=view)

    @ticket.command(name="remind", description="Remind the ticket owner their ticket is open.")  # type: ignore[arg-type]
    @commands.cooldown(1, 300, commands.BucketType.channel)
    async def remind(self, ctx: commands.Context[Any]) -> None:
        """Remind the ticket owner their ticket is open."""
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

    @ticket.command(name="close", description="Transcript and close the current ticket.")  # type: ignore[arg-type]
    async def close(self, ctx: commands.Context[Any]) -> None:
        """Transcript and close the current ticket."""
        ctx = require_context(ctx)
        if not isinstance(ctx.author, discord.Member) or not self.is_staff(ctx.author):
            await ctx.warn("You cannot manage tickets.")
            return
        if await self.require_ticket(ctx) is None:
            return
        await ctx.approve("Closing this ticket...")
        await self.close_ticket(ctx, closed_by=ctx.author.id)

    @ticket.command(name="closerequest", description="Ask the owner to confirm closing.")  # type: ignore[arg-type]
    @app_commands.describe(reason="Why this ticket should be closed")
    @commands.cooldown(1, 300, commands.BucketType.channel)
    async def closerequest(self, ctx: commands.Context[Any], *, reason: str) -> None:
        """Ask the owner to confirm closing."""
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
        await ctx.send(view=CloseRequest(ticket.owner_id, ctx.author.id, cleaned))

    async def open_ticket(
        self,
        interaction: discord.Interaction[Any],
        *,
        kind: str,
        reason: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        settings = self.bot.settings
        try:
            db = database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        if (
            settings.ticket_support_role_id is None
            or settings.ticket_logs_channel_id is None
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
        category = interaction.guild.get_channel(CATEGORY)
        support = interaction.guild.get_role(settings.ticket_support_role_id)
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

    async def claim_button(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member):
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

        await self.claim_ticket(interaction.channel, interaction.user, reply=Reply())

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
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("Closing this ticket...")),
            ephemeral=True,
        )
        await self.close_ticket(interaction, closed_by=interaction.user.id)

    async def claim_ticket(
        self,
        channel: discord.abc.Messageable,
        member: discord.Member,
        *,
        reply: Any,
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
        role_id = self.bot.settings.ticket_support_role_id
        role = channel.guild.get_role(role_id) if role_id else None
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
        await channel.edit(
            name=ticket_channel_name(
                owner.name if owner else str(ticket.owner_id),
                claimed=True,
            ),
            reason="Ticket claimed",
        )
        await db.claim_ticket(channel.id, member.id)
        await reply.approve(f"**{member.display_name}** claimed this ticket.")

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
                    self.bot.settings.discord_token.get_secret_value(),
                    title=f"Ticket #{ticket.number:03d}",
                    description=f"{ticket.kind}: {ticket.reason[:200]}",
                )
            except CookieError as exc:
                logger.warning("Ticket transcript failed status=%s", exc.status)
        logs = guild.get_channel(self.bot.settings.ticket_logs_channel_id or 0)
        owner = guild.get_member(ticket.owner_id)
        closer = guild.get_member(closed_by)
        if isinstance(logs, discord.TextChannel):
            body = (
                f"**Ticket:** `#{ticket.number:03d}`\n"
                f"**Type:** `{ticket.kind}`\n"
                f"**Channel:** `{channel.name}`\n"
                f"**Owner:** {owner.display_name if owner else ticket.owner_id}\n"
                f"**Closed by:** {closer.display_name if closer else closed_by}\n"
                f"**Claimed by:** "
                f"{ticket.claimed_by if ticket.claimed_by else 'Unclaimed'}\n"
                f"**Opened:** <t:{int(ticket.created_at.timestamp())}:f>\n"
                f"**Inquiry:** {ticket.reason[:300]}"
            )
            if url is not None:
                body += f"\n**Transcript:** [View]({url})"
            view = ui.LayoutView()
            items: list[ui.Item[Any]] = [
                ui.TextDisplay("## Ticket Closed\nA support ticket was closed."),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.TextDisplay(body),
            ]
            if url is not None:
                items.append(ui.ActionRow(ui.Button(label="View Transcript", url=url)))
            view.add_item(ui.Container(*items))
            try:
                await logs.send(view=view)
            except discord.HTTPException:
                logger.warning("Could not send ticket log")
        await db.delete_ticket(channel.id)
        try:
            await channel.delete(reason="Ticket closed")
        except discord.HTTPException:
            logger.warning("Could not delete ticket channel %s", channel.id)

    async def ensure_dashboard(self) -> None:
        async with self.bot.lock_for("ticket-dashboard"):
            channel = self.bot.get_channel(DASHBOARD)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(DASHBOARD)
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
