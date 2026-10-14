from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs.packages.constants import POLL_INTERVAL_SECONDS
from bot.cogs.packages.layouts import payouts_layout
from bot.cogs.packages.modals import DetailsModal
from bot.cogs.packages.service import PackageService
from bot.cogs.packages.views import (
    ApproveButton,
    DenyButton,
    PurchaseButton,
    ReportButton,
    ResendButton,
    SettleConfirm,
)
from bot.core.bot import Aspect
from bot.shared.checks import database
from bot.shared.errors import remember_error
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")


class Packages(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self.service = PackageService(bot)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(
            ApproveButton,
            DenyButton,
            PurchaseButton,
            ReportButton,
            ResendButton,
        )
        self.poll_purchases.start()

    async def cog_unload(self) -> None:
        self.poll_purchases.cancel()
        self.bot.remove_dynamic_items(
            ApproveButton,
            DenyButton,
            PurchaseButton,
            ReportButton,
            ResendButton,
        )

    package = app_commands.Group(name="package", description="Package marketplace")
    payouts = app_commands.Group(
        name="payouts",
        description="Package payouts",
        parent=package,
    )

    @package.command(name="submit", description="Submit a package for review")
    async def submit(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Guild only.")),
                ephemeral=True,
            )
            return
        member = interaction.user
        if interaction.guild is not None:
            cached = interaction.guild.get_member(interaction.user.id)
            if cached is not None:
                member = cached
        if not self.service.can_submit(member):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Packager role required.")),
                ephemeral=True,
            )
            return
        self.service.draft_for(member.id)
        await interaction.response.send_modal(DetailsModal(member.id))

    @package.command(name="earnings", description="View your package earnings")
    async def earnings(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Guild only.")),
                ephemeral=True,
            )
            return
        if not self.service.is_packager(interaction.user):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Packager role required.")),
                ephemeral=True,
            )
            return
        rows = await database(self.bot).packager_earnings_by_package(interaction.user.id)
        await interaction.response.send_message(
            view=payouts_layout(interaction.user.id, rows, pending_only=False),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @payouts.command(name="summary", description="Pending payout totals per packager")
    async def payouts_summary(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member) or not self.service.is_management(
            interaction.user
        ):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        rows = await database(self.bot).payout_summary()
        if not rows:
            text = "No payouts yet."
        else:
            text = "## Payout Summary\n" + "\n".join(
                f"<@{row.packager_id}> — pending `{row.pending_total:,}` "
                f"(`{row.pending_count}`) · paid `{row.paid_total:,}`"
                for row in rows
            )
        await interaction.response.send_message(
            view=container_view(discord.ui.TextDisplay(text)),
            ephemeral=True,
        )

    @payouts.command(name="view", description="View payouts for a packager")
    @app_commands.describe(user="Packager to inspect")
    async def payouts_view(
        self,
        interaction: discord.Interaction[Any],
        user: discord.User,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self.service.is_management(
            interaction.user
        ):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        rows = await database(self.bot).packager_earnings_by_package(user.id)
        await interaction.response.send_message(
            view=payouts_layout(user.id, rows, pending_only=False),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=[user]),
        )

    @payouts.command(name="settle", description="Mark pending payouts paid for a packager")
    @app_commands.describe(user="Packager to settle")
    async def payouts_settle(
        self,
        interaction: discord.Interaction[Any],
        user: discord.User,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self.service.is_management(
            interaction.user
        ):
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=SettleConfirm(user.id, interaction.user.id),
            ephemeral=True,
        )

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_purchases(self) -> None:
        if self.bot.db is None:
            return
        db = database(self.bot)
        now = datetime.now(UTC)
        try:
            await db.expire_purchases(now)
            pending = await db.pending_purchases(now)
        except Exception as exc:
            remember_error(self.bot.traceback, exc, where="Package poll")
            return
        if not pending:
            return
        await self.service.sync_recent_sales()
        for purchase in pending:
            package = await db.package(purchase.package_id)
            if package is None or package.gamepass_id is None:
                continue
            if await self.service.buyer_paid(
                purchase.buyer_roblox_id,
                package.gamepass_id,
                since=purchase.created_at,
            ):
                await self.service.complete_purchase(purchase)

    @poll_purchases.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Packages(bot))
