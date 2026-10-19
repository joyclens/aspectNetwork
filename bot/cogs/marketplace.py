from __future__ import annotations

import logging
from typing import Any

import discord
from discord import ui
from discord.ext import commands

from bot.core.bot import Aspect
from bot.core.ids import Channels, Emojis, partial_emoji
from bot.shared.layout import AspectLayout, container_view
from bot.shared.persistence import PersistentView, register_persistent, unregister_persistent

logger = logging.getLogger("aspect")

MARKETPLACE_BANNER = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/1553891840795742268/marketplace.png"
)
FOOTER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"

_SMALL = discord.SeparatorSpacing.small


def _purchase(label_text: str, url: str) -> ui.Section[Any]:
    return ui.Section(
        label_text,
        accessory=ui.Button(label="Purchase", style=discord.ButtonStyle.link, url=url),
    )


def advertisements_view() -> AspectLayout:
    view = AspectLayout()
    view.add_item(
        ui.Container(
            ui.MediaGallery(discord.MediaGalleryItem(MARKETPLACE_BANNER)),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                f"The {Emojis.newsletter} **Aspect Advertisement** catalog will help you "
                "boost your server's recognition. All products come with a ping."
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            _purchase(
                f"{Emojis.confetti} **Sponsored Giveaway**\n"
                "-# Boost your server with a Sponsored Giveaway. Sponsored Giveaways come "
                "with an **@everyone** ping and require a prize greater than or equal to "
                "**500 robux** in value.",
                "https://www.roblox.com/catalog/134641402925074/",
            ),
            _purchase(
                f"{Emojis.event} **Paid Advertisement**\n"
                "-# Get recognised with a Paid Advertisement. Paid Advertisements come "
                "with an **@everyone** ping.",
                "https://www.roblox.com/catalog/113272473148244/Paid-Advertisement-Everyone-Ping",
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            _purchase(
                f"{Emojis.suggestion} **Priority Queue**\n"
                "-# Put your advertisement in our Priority Queue. Priority Queue items "
                "are posted 1.5x sooner compared to Normal Queue items. Must be purchased "
                "with a SPGW or PA.",
                "http://roblox.com/catalog/104447359521852/",
            ),
            _purchase(
                f"{Emojis.fullstar} **Daily Queue**\n"
                "-# Get your advertisement posted as soon as tomorrow. Daily Queue items "
                "are posted 2x sooner than Priority Queue items and 3x sooner than Normal "
                "Queue items. Must be purchased with a SPGW or QA.",
                "https://www.roblox.com/catalog/117463223374082",
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
        )
    )
    return view


def tos_view() -> AspectLayout:
    view = AspectLayout()
    view.add_item(
        ui.Container(
            ui.MediaGallery(discord.MediaGalleryItem(MARKETPLACE_BANNER)),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(f"## {Emojis.regulations} **Aspect Marketplace Terms of Service**"),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                "**Refunds**\n"
                "-# **Aspect Network** does not offer refunds. All sales are final. "
                "Exceptions may be given in extremely rare circumstances with a full "
                "consensus from the **Aspect Management** team."
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                "**Scamming and Defrauding**\n"
                "-# Anyone who attempts to scam or defraud **Aspect Network** will "
                f"receive a permanent ban from all {Emojis.affiliate} **Aspect Affiliates**."
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                "**Formatting**\n"
                "-# All Paid Advertisement products are prohibited from containing custom "
                "emojis (they don't render) and hyperlinks. All Sponsored Giveaways will "
                "be posted with a specific format and *will not be changed*."
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                "**Images**\n"
                "-# Absolutely no image (links) will be allowed in Sponsored Giveaways "
                "or Paid Advertisements."
            ),
            ui.Separator(visible=True, spacing=_SMALL),
            ui.TextDisplay(
                "**Advertisement Queues**\n"
                "-# Advertisements (including both SPGWs and PAs) are placed in a joint "
                "queue that is available through our ticket system. Advertisements will "
                "be 'locked' 12 hours before their set post, meaning they can not be "
                "moved to a different day **due to another advertisement**. "
                "**Aspect Network** reserves the right to delay or cancel advertisements "
                "at any time for any reason.\n"
                "-# **Between Time:** *Normal Queue - 3 Days* **|** *Priority Queue - 2 Days* "
                "**|** *Daily Queue - 1 Day*"
            ),
            ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
        )
    )
    return view


def aspect_plus_view() -> AspectLayout:
    return container_view(ui.TextDisplay("## Aspect+\nComing soon."))


class MarketplaceMenu(ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            custom_id="marketplace:menu",
            placeholder="Select an option...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Advertisements",
                    value="advertisements",
                    emoji=partial_emoji(Emojis.newsletter),
                ),
                discord.SelectOption(
                    label="Aspect+",
                    value="aspectplus",
                    emoji=partial_emoji(Emojis.aspect),
                ),
                discord.SelectOption(
                    label="Terms of Service",
                    value="tos",
                    emoji=partial_emoji(Emojis.regulations),
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        choice = self.values[0] if self.values else ""
        if choice == "advertisements":
            await interaction.response.send_message(
                view=advertisements_view(),
                ephemeral=True,
            )
            return
        if choice == "aspectplus":
            await interaction.response.send_message(
                view=aspect_plus_view(),
                ephemeral=True,
            )
            return
        if choice == "tos":
            await interaction.response.send_message(view=tos_view(), ephemeral=True)
            return
        await interaction.response.send_message(
            view=container_view(ui.TextDisplay("That option is not available.")),
            ephemeral=True,
        )


class Marketplace(AspectLayout):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            ui.Container(
                ui.MediaGallery(discord.MediaGalleryItem(MARKETPLACE_BANNER)),
                ui.Separator(visible=True, spacing=_SMALL),
                ui.TextDisplay(
                    "Find your ideal product in the **Aspect Marketplace**. Browse a wide "
                    "range of products selected for you, including everything from sponsored "
                    "giveaways to curated subscriptions.\n\n"
                    "All sales are final. Read our **Marketplace Terms of Service** for "
                    "more information."
                ),
                ui.Separator(visible=True, spacing=_SMALL),
                ui.ActionRow(MarketplaceMenu()),
                ui.Separator(visible=True, spacing=_SMALL),
                ui.TextDisplay(
                    "-# Purchases must be claimed through our ticket system within 24 hours."
                ),
                ui.MediaGallery(discord.MediaGalleryItem(FOOTER)),
            )
        )


class MarketplaceCog(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._panel_id: int | None = None
        self._persistent: list[PersistentView] = []

    async def cog_load(self) -> None:
        self._persistent = [register_persistent(self.bot, Marketplace())]

    async def cog_unload(self) -> None:
        for view in self._persistent:
            unregister_persistent(self.bot, view)
        self._persistent.clear()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.user is not None:
            await self.ensure_marketplace()

    async def ensure_marketplace(self) -> None:
        async with self.bot.lock_for("marketplace-panel"):
            channel = self.bot.get_channel(Channels.marketplace)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(Channels.marketplace)
                except discord.HTTPException:
                    return
            if not isinstance(channel, discord.TextChannel) or self.bot.user is None:
                return
            if self._panel_id is not None:
                try:
                    await channel.fetch_message(self._panel_id)
                    return
                except discord.NotFound:
                    self._panel_id = None
                except discord.HTTPException:
                    return
            try:
                async for message in channel.history(limit=50):
                    if message.author.id != self.bot.user.id:
                        continue
                    if "marketplace:menu" in str(message.components):
                        self._panel_id = message.id
                        return
            except discord.HTTPException:
                return
            try:
                sent = await channel.send(view=Marketplace())
            except discord.HTTPException:
                logger.warning("Could not send the marketplace panel")
                return
            self._panel_id = sent.id


async def setup(bot: Aspect) -> None:
    await bot.add_cog(MarketplaceCog(bot))
