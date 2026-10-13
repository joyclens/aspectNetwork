from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from bot.core.bot import Aspect
from bot.services.dock import DockError
from bot.services.roblox import RobloxError, Sale
from bot.shared.context import require_context
from bot.shared.layout import AspectLayout

logger = logging.getLogger("aspect")


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
            "## <:marketplace:1551256187301797970> Purchase History",
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
            lines.append(
                f"- {linked} · `{sale.amount:,}` · <t:{int(sale.created.timestamp())}:d>"
            )
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

    async def cog_load(self) -> None:
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.hybrid_group(
        name="purchases", 
        fallback="recent"
    )  # type: ignore[arg-type]
    async def purchases(self, ctx: commands.Context[Any]) -> None:
        """Show the most recent store purchase."""
        ctx = require_context(ctx)
        if self.bot.db is None:
            await ctx.warn("The database is not ready.")
            return
        sale = await self.bot.db.recent_sale(self.bot.settings.roblox_group_id)
        if sale is None:
            await ctx.warn("No purchases have been recorded yet.")
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
                    "## <:marketplace:1551256187301797970> New Purchase\n"
                    f"[**{sale.agent_name}**]({profile}) has purchased an **item** from our store."
                ),
                ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
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

    @purchases.command(
        name="history",
        description="Show a member's past store purchases.",
    )  # type: ignore[arg-type]
    @app_commands.describe(user="Discord member whose linked Roblox purchases to show")
    async def history(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        """Show a member's past store purchases."""
        ctx = require_context(ctx)
        if self.bot.db is None or self.bot.dock is None:
            await ctx.warn("Purchases are not ready.")
            return
        try:
            linked = await self.bot.dock.linked_roblox(
                user.id,
                ctx.guild.id if ctx.guild else self.bot.settings.discord_guild_id,
            )
        except DockError:
            await ctx.warn("Could not look up that member's Roblox account.")
            return
        if linked is None:
            await ctx.warn("That member is not verified.")
            return
        sales = await self.bot.db.agent_sales(self.bot.settings.roblox_group_id, int(linked))
        if not sales:
            await ctx.warn("No purchases were found for that member.")
            return
        await ctx.send(view=History(ctx.author.id, sales))

    @purchases.command(
        name="highest",
        description="Show the highest store purchase.",
    )  # type: ignore[arg-type]
    async def highest(self, ctx: commands.Context[Any]) -> None:
        """Show the highest store purchase."""
        ctx = require_context(ctx)
        if self.bot.db is None:
            await ctx.warn("The database is not ready.")
            return
        sale = await self.bot.db.highest_sale(self.bot.settings.roblox_group_id)
        if sale is None:
            await ctx.warn("No purchases have been recorded yet.")
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
                    "## <:marketplace:1551256187301797970> New Purchase\n"
                    f"[**{sale.agent_name}**]({profile}) has purchased an **item** from our store."
                ),
                ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
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

    @tasks.loop(seconds=30)
    async def watch(self) -> None:
        roblox, db = self.bot.roblox, self.bot.db
        if roblox is None or db is None:
            return
        group = self.bot.settings.roblox_group_id
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

            channel = self.bot.get_channel(1529142741110358027)
            if channel is None:
                channel = await self.bot.fetch_channel(1529142741110358027)
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
                            "## <:marketplace:1551256187301797970> New Purchase\n"
                            f"[**{sale.agent_name}**]({profile}) has purchased an **item** "
                            "from our store."
                        ),
                        ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
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
            logger.warning("Purchase history is unavailable status=%s", exc.status)
        except discord.HTTPException:
            logger.warning("Could not log a purchase")

    @watch.before_loop
    async def before_watch(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Purchases(bot))
