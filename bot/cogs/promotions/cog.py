from __future__ import annotations

from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from bot.cogs.promotions.constants import POLL_INTERVAL_SECONDS
from bot.cogs.promotions.service import PromotionService
from bot.cogs.promotions.views import (
    ApprovePromotionButton,
    DenyPromotionButton,
    EditPromotionButton,
    PostedPromotionButton,
    ReschedulePromotionButton,
    ReviewPromotionButton,
    SubmitPromotionButton,
)
from bot.core.bot import Aspect
from bot.shared.checks import is_management
from bot.shared.errors import remember_error
from bot.shared.layout import container_view

DYNAMIC_ITEMS = (
    SubmitPromotionButton,
    ApprovePromotionButton,
    DenyPromotionButton,
    EditPromotionButton,
    ReviewPromotionButton,
    ReschedulePromotionButton,
    PostedPromotionButton,
)


class Promotions(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self.service = PromotionService(bot)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*DYNAMIC_ITEMS)
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()
        self.bot.remove_dynamic_items(*DYNAMIC_ITEMS)

    async def ticket_extra(self, channel_id: int) -> ui.Container[Any] | None:
        if self.bot.db is None:
            return None
        return await self.service.ticket_extra(channel_id)

    promotions = app_commands.Group(name="promotions", description="Advertisement queue commands.")

    @promotions.command(name="queue", description="View the advertisement queue.")
    async def queue(self, interaction: discord.Interaction[Any]) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_management(interaction.user):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            view=container_view(ui.TextDisplay(await self.service.queue_text())),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def watch(self) -> None:
        if self.bot.db is None:
            return
        await self.service.auto_claim()
        await self.service.alert_due()

    @watch.before_loop
    async def before_watch(self) -> None:
        await self.bot.wait_until_ready()

    @watch.error
    async def watch_error(self, exc: BaseException) -> None:
        remember_error(self.bot.traceback, exc, where="Promotion watch")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Promotions(bot))
