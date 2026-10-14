from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs.packages.constants import POLL_INTERVAL_SECONDS, POLL_RATE_LIMIT, POLL_RATE_WINDOW
from bot.cogs.packages.modals import DetailsModal
from bot.cogs.packages.service import PackageService
from bot.cogs.packages.views import (
    ApproveButton,
    ConfirmPurchaseButton,
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
        self._poll_times: list[float] = []

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(
            ApproveButton,
            DenyButton,
            PurchaseButton,
            ReportButton,
            ConfirmPurchaseButton,
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
            ConfirmPurchaseButton,
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
            # Single response only — never open the modal when denied.
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Packager role required.")),
                ephemeral=True,
            )
            return
        if interaction.response.is_done():
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
        rows = await database(self.bot).payouts_for(interaction.user.id)
        pending = sum(row.packager_amount for row in rows if row.status == "pending")
        paid = sum(row.packager_amount for row in rows if row.status == "paid")
        await interaction.response.send_message(
            view=container_view(
                discord.ui.TextDisplay(
                    "## Your Earnings\n"
                    f"**Pending:** `{pending:,}` R$\n"
                    f"**Paid:** `{paid:,}` R$\n"
                    f"**Payouts:** `{len(rows)}`"
                )
            ),
            ephemeral=True,
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
        rows = await database(self.bot).payouts_for(user.id)
        pending = sum(row.packager_amount for row in rows if row.status == "pending")
        paid = sum(row.packager_amount for row in rows if row.status == "paid")
        await interaction.response.send_message(
            view=container_view(
                discord.ui.TextDisplay(
                    f"## Payouts for {user.mention}\n"
                    f"**Pending:** `{pending:,}` R$\n"
                    f"**Paid:** `{paid:,}` R$\n"
                    f"**Rows:** `{len(rows)}`"
                )
            ),
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
        client = self.service.gamepass()
        if client is None:
            return
        sem = asyncio.Semaphore(5)
        async def one(purchase: Any) -> None:
            async with sem:
                await self._throttle()
                package = await db.package(purchase.package_id)
                if package is None or package.gamepass_id is None:
                    return
                try:
                    owns = await client.owns_pass(purchase.buyer_roblox_id, package.gamepass_id)
                except Exception as exc:
                    remember_error(self.bot.traceback, exc, where="Package inventory")
                    return
                if owns:
                    await self.service.complete_purchase(purchase)

        await asyncio.gather(*(one(item) for item in pending))

    @poll_purchases.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _throttle(self) -> None:
        now = time.monotonic()
        self._poll_times = [stamp for stamp in self._poll_times if now - stamp < POLL_RATE_WINDOW]
        if len(self._poll_times) >= POLL_RATE_LIMIT:
            wait = POLL_RATE_WINDOW - (now - self._poll_times[0])
            if wait > 0:
                await asyncio.sleep(wait)
            now = time.monotonic()
            self._poll_times = [
                stamp for stamp in self._poll_times if now - stamp < POLL_RATE_WINDOW
            ]
        self._poll_times.append(time.monotonic())


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Packages(bot))
