from __future__ import annotations

from typing import Any

import discord
from discord import ui
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Emojis
from bot.shared.context import require_context


class Economy(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.hybrid_group(  # type: ignore[arg-type]
        name="funds",
        fallback="balance",
        description="Show the group's Robux and pending Robux.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True, manage_roles=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def funds(self, ctx: commands.Context[Any]) -> None:
        ctx = require_context(ctx)
        if self.bot.roblox is None:
            await ctx.warn("Roblox is not ready.")
            return
        robux, pending = await self.bot.roblox.balance()
        view = ui.LayoutView()
        view.add_item(
            ui.Container(
                ui.TextDisplay(
                    f"{Emojis.robux} The group currently has **{robux:,}** "
                    f"robux available, with an additional **{pending:,}** pending."
                ),
                ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6ace0720&is=6accb5a0&hm="
                        "4c4fffa70183ac88e939beabc0dccd963d97cb1f11463d2e77c7a759a2b49567&"
                    ),
                ),
            )
        )
        await ctx.send(view=view)


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Economy(bot))
