from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from bot.core.bot import Aspect
from bot.core.ids import App, Channels, Emojis, Guild
from bot.services.dock import DockError
from bot.services.roblox import RobloxError, Sale
from bot.shared.checks import database
from bot.shared.context import require_context
from bot.shared.layout import AspectLayout

logger = logging.getLogger("aspect")

_ROBLOX_BACKOFF = 120.0
_ROBLOX_LOG_EVERY = 300.0


def timeframe_choices(now: datetime) -> list[str]:
    return [
        "Weekly",
        "Monthly",
        "Yearly",
        now.strftime("%B"),
        "All Time",
        str(now.year),
        str(now.year - 1),
    ]


def timeframe_bounds(
    choice: str,
    now: datetime,
) -> tuple[datetime | None, datetime | None] | None:
    if choice not in timeframe_choices(now):
        return None
    if choice == "Weekly":
        return now - timedelta(days=7), now
    if choice == "Monthly":
        return now - timedelta(days=30), now
    if choice == "Yearly":
        return now - timedelta(days=365), now
    if choice == "All Time":
        return None, None
    if choice == now.strftime("%B"):
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        if now.month == 12:
            return start, datetime(now.year + 1, 1, 1, tzinfo=UTC)
        return start, datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    if choice == str(now.year):
        return (
            datetime(now.year, 1, 1, tzinfo=UTC),
            datetime(now.year + 1, 1, 1, tzinfo=UTC),
        )
    if choice == str(now.year - 1):
        year = now.year - 1
        return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
    return None


class History(AspectLayout):
    def __init__(self, author: int, sales: list[Sale]) -> None:
        super().__init__(timeout=120)
        self.author = author
        self.sales = sales
        self.page = 0
        self.render()

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        return interaction.user.id == self.author

    def render(self) -> None:
        self.clear_items()
        pages = (len(self.sales) + 4) // 5 if len(self.sales) > 5 else 1
        chunk = self.sales[self.page * 5 : self.page * 5 + 5] if pages > 1 else self.sales
        lines = [
            f"## {Emojis.marketplace} Purchase History",
            f"Purchases by [**{chunk[0].agent_name}**]"
            f"(https://www.roblox.com/users/{chunk[0].agent_id}/profile).",
            "",
        ]
        for sale in chunk:
            name = sale.item_name.replace("`", "'")
            if sale.item_id and sale.item_type == "GamePass":
                linked = f"[{name}](https://www.roblox.com/game-pass/{sale.item_id})"
            elif sale.item_id and sale.item_type == "Asset":
                linked = f"[{name}](https://www.roblox.com/catalog/{sale.item_id})"
            elif sale.place_id:
                linked = f"[{name}](https://www.roblox.com/games/{sale.place_id})"
            else:
                linked = f"**{name}**"
            lines.append(f"- {linked} · `{sale.amount:,}` · <t:{int(sale.created.timestamp())}:d>")
        if pages > 1:
            lines += ["", f"-# Page {self.page + 1}/{pages}"]

        text = "\n".join(lines)
        if pages == 1:
            self.add_item(ui.Container(ui.TextDisplay(text)))
            return

        back: ui.Button[Any] = ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
        )
        fwd: ui.Button[Any] = ui.Button(
            label="Next",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= pages - 1,
        )

        async def go_back(interaction: discord.Interaction[Any]) -> None:
            self.page -= 1
            self.render()
            await interaction.response.edit_message(view=self)

        async def go_next(interaction: discord.Interaction[Any]) -> None:
            self.page += 1
            self.render()
            await interaction.response.edit_message(view=self)

        back.callback = go_back  # type: ignore[method-assign]
        fwd.callback = go_next  # type: ignore[method-assign]
        self.add_item(ui.Container(ui.TextDisplay(text), ui.ActionRow(back, fwd)))


class Purchases(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._roblox_skip_until = 0.0
        self._roblox_log_at = 0.0

    async def cog_load(self) -> None:
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.hybrid_group(name="purchases", fallback="recent")  # type: ignore[arg-type]
    async def purchases(self, ctx: commands.Context[Any]) -> None:
        """Show the most recent store purchase."""
        ctx = require_context(ctx)
        sale = await database(self.bot).recent_sale(App.roblox_group_id)
        if sale is None:
            await ctx.warn(
                "I was **unable** to find the most recent purchase, "
                "maybe no purchases have been recorded yet?"
            )
            return
        name = sale.item_name.replace("`", "'")
        if sale.item_id and sale.item_type == "GamePass":
            linked = f"[{name}](https://www.roblox.com/game-pass/{sale.item_id})"
        elif sale.item_id and sale.item_type == "Asset":
            linked = f"[{name}](https://www.roblox.com/catalog/{sale.item_id})"
        elif sale.place_id:
            linked = f"[{name}](https://www.roblox.com/games/{sale.place_id})"
        else:
            linked = f"**{name}**"
        profile = (
            f"https://www.roblox.com/groups/{sale.agent_id}"
            if sale.agent_type == "Group"
            else f"https://www.roblox.com/users/{sale.agent_id}/profile"
        )
        view = ui.LayoutView()
        view.add_item(
            ui.Container(
                ui.TextDisplay(
                    f"## {Emojis.marketplace} New Purchase\n"
                    f"[**{sale.agent_name}**]({profile}) has purchased an **item** from our store."
                ),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.TextDisplay(
                    f"**Item:** {linked}\n"
                    f"**Price:** `{sale.amount:,}` after tax\n"
                    f"**Purchase Date:** <t:{int(sale.created.timestamp())}:f>"
                ),
                ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6acf58a0&is=6ace0720&hm="
                        "4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
                    ),
                ),
            )
        )
        await ctx.send(view=view)

    @purchases.command(name="history")  # type: ignore[arg-type]
    @app_commands.describe(user="Discord member whose linked Roblox purchases to show")
    async def history(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        """Show a member's past store purchases."""
        ctx = require_context(ctx)
        db = database(self.bot)
        if self.bot.dock is None:
            await ctx.warn("I was **unable** to show that member's purchase history.")
            return
        try:
            linked = await self.bot.dock.linked_roblox(
                user.id,
                ctx.guild.id if ctx.guild else Guild.id,
            )
        except DockError:
            logger.warning("Dock lookup failed for purchase history user=%s", user.id)
            await ctx.warn("I was **unable** to look up that member's Roblox account.")
            return
        if linked is None:
            await ctx.warn("That member is **not** verified.")
            return
        sales = await db.agent_sales(App.roblox_group_id, int(linked))
        if not sales:
            await ctx.warn("I was **unable** to find any purchases for that member.")
            return
        await ctx.send(view=History(ctx.author.id, sales))

    @purchases.command(name="highest")  # type: ignore[arg-type]
    async def highest(self, ctx: commands.Context[Any]) -> None:
        """Show the highest store purchase."""
        ctx = require_context(ctx)
        sale = await database(self.bot).highest_sale(App.roblox_group_id)
        if sale is None:
            await ctx.warn(
                "I was **unable** to find the highest purchase, "
                "maybe no purchases have been recorded yet?"
            )
            return
        name = sale.item_name.replace("`", "'")
        if sale.item_id and sale.item_type == "GamePass":
            linked = f"[{name}](https://www.roblox.com/game-pass/{sale.item_id})"
        elif sale.item_id and sale.item_type == "Asset":
            linked = f"[{name}](https://www.roblox.com/catalog/{sale.item_id})"
        elif sale.place_id:
            linked = f"[{name}](https://www.roblox.com/games/{sale.place_id})"
        else:
            linked = f"**{name}**"
        profile = (
            f"https://www.roblox.com/groups/{sale.agent_id}"
            if sale.agent_type == "Group"
            else f"https://www.roblox.com/users/{sale.agent_id}/profile"
        )
        view = ui.LayoutView()
        view.add_item(
            ui.Container(
                ui.TextDisplay(
                    f"## {Emojis.marketplace} New Purchase\n"
                    f"[**{sale.agent_name}**]({profile}) has purchased an **item** from our store."
                ),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.TextDisplay(
                    f"**Item:** {linked}\n"
                    f"**Price:** `{sale.amount:,}` after tax\n"
                    f"**Purchase Date:** <t:{int(sale.created.timestamp())}:f>"
                ),
                ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6acf58a0&is=6ace0720&hm="
                        "4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
                    ),
                ),
            )
        )
        await ctx.send(view=view)

    @purchases.command(name="time")  # type: ignore[arg-type]
    @app_commands.describe(timeframe="Weekly, Monthly, Yearly, this month, All Time, or a year")
    async def time(self, ctx: commands.Context[Any], timeframe: str) -> None:
        """Show purchase stats for a timeframe."""
        ctx = require_context(ctx)
        choice = timeframe.strip()
        if len(choice) > 32:
            await ctx.warn("That timeframe is not valid.")
            return
        bounds = timeframe_bounds(choice, datetime.now(UTC))
        if bounds is None:
            await ctx.warn("That timeframe is not valid.")
            return
        start, end = bounds
        count, total = await database(self.bot).sales_summary(
            App.roblox_group_id,
            start,
            end,
        )
        view = ui.LayoutView()
        view.add_item(
            ui.Container(
                ui.TextDisplay(
                    f"## {Emojis.marketplace} Purchase Stats\nStats for **{choice}**."
                ),
                ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                ui.TextDisplay(
                    f"**Purchases:** `{count:,}`\n**Robux Earned:** `{total:,}` after tax"
                ),
                ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "https://cdn.discordapp.com/attachments/1553889994538750133/"
                        "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                        "?ex=6acf58a0&is=6ace0720&hm="
                        "4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
                    ),
                ),
            )
        )
        await ctx.send(view=view)

    @time.autocomplete("timeframe")
    async def timeframe_autocomplete(
        self,
        _interaction: discord.Interaction[Any],
        current: str,
    ) -> list[app_commands.Choice[str]]:
        query = current.strip().lower()[:32]
        return [
            app_commands.Choice(name=name, value=name)
            for name in timeframe_choices(datetime.now(UTC))
            if not query or query in name.lower()
        ]

    @tasks.loop(seconds=30)
    async def watch(self) -> None:
        roblox, db = self.bot.roblox, self.bot.db
        if roblox is None or db is None:
            return
        now = time.monotonic()
        if now < self._roblox_skip_until:
            return
        group = App.roblox_group_id
        try:
            if await db.setting(f"purchases:{group}:seeded") is not True:
                cursor = await db.setting(f"purchases:{group}:cursor")
                cursor = cursor if isinstance(cursor, str) else None
                for _ in range(8):
                    page, cursor = await roblox.sales(cursor=cursor)
                    if page:
                        await db.store_sales(group, page)
                    if cursor is None:
                        await db.store_setting(f"purchases:{group}:seeded", True)
                        await db.drop_setting(f"purchases:{group}:cursor")
                        logger.info("Purchase history recorded")
                        return
                    await db.store_setting(f"purchases:{group}:cursor", cursor)
                return

            found: list[Sale] = []
            cursor = None
            for _ in range(8):
                page, cursor = await roblox.sales(cursor=cursor)
                if not page:
                    break
                known = await db.known_ids([sale.id for sale in page])
                found.extend(sale for sale in page if sale.id not in known)
                if known or cursor is None:
                    break
            if not found:
                return

            channel = self.bot.get_channel(Channels.purchase_logs)
            if channel is None:
                channel = await self.bot.fetch_channel(Channels.purchase_logs)
            if not isinstance(channel, discord.TextChannel):
                return
            funds, _ = await roblox.balance()
            for sale in list(reversed(found))[:20]:
                name = sale.item_name.replace("`", "'")
                if sale.item_id and sale.item_type == "GamePass":
                    linked = f"[{name}](https://www.roblox.com/game-pass/{sale.item_id})"
                elif sale.item_id and sale.item_type == "Asset":
                    linked = f"[{name}](https://www.roblox.com/catalog/{sale.item_id})"
                elif sale.place_id:
                    linked = f"[{name}](https://www.roblox.com/games/{sale.place_id})"
                else:
                    linked = f"**{name}**"
                profile = (
                    f"https://www.roblox.com/groups/{sale.agent_id}"
                    if sale.agent_type == "Group"
                    else f"https://www.roblox.com/users/{sale.agent_id}/profile"
                )
                view = ui.LayoutView()
                view.add_item(
                    ui.Container(
                        ui.TextDisplay(
                            f"## {Emojis.marketplace} New Purchase\n"
                            f"[**{sale.agent_name}**]({profile}) has purchased an **item** "
                            "from our store."
                        ),
                        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                        ui.TextDisplay(
                            f"**Item:** {linked}\n"
                            f"**Price:** `{sale.amount:,}` after tax\n"
                            f"**Purchase Date:** <t:{int(sale.created.timestamp())}:f>\n"
                            f"**Group Funds:** `{funds:,}`"
                        ),
                        ui.MediaGallery(
                            discord.MediaGalleryItem(
                                "https://cdn.discordapp.com/attachments/1553889994538750133/"
                                "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
                                "?ex=6acf58a0&is=6ace0720&hm="
                                "4b79fc195d2f294319e01d01a76782756319a8d26e95abc78e1aed22d3db5ecd&"
                            ),
                        ),
                    )
                )
                await channel.send(view=view)
                await db.store_sales(group, [sale])
        except RobloxError as exc:
            self._roblox_skip_until = time.monotonic() + _ROBLOX_BACKOFF
            if time.monotonic() >= self._roblox_log_at:
                logger.warning("Purchase history is unavailable status=%s", exc.status)
                self._roblox_log_at = time.monotonic() + _ROBLOX_LOG_EVERY
        except discord.HTTPException:
            logger.warning("Could not log a purchase")

    @watch.before_loop
    async def before_watch(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Purchases(bot))
