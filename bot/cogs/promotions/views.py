from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from bot.cogs.promotions.constants import (
    APPROVE_TEMPLATE,
    DENY_TEMPLATE,
    EDIT_TEMPLATE,
    POSTED_TEMPLATE,
    RESCHEDULE_TEMPLATE,
    REVIEW_TEMPLATE,
    SUBMIT_TEMPLATE,
)
from bot.core.bot import Aspect
from bot.shared.checks import is_management
from bot.shared.layout import AspectLayout, container_view

if TYPE_CHECKING:
    from bot.cogs.promotions.service import PromotionService

Interaction = discord.Interaction[Any]


def _service(interaction: Interaction) -> PromotionService | None:
    client = interaction.client
    if not isinstance(client, Aspect):
        return None
    cog = client.get_cog("Promotions")
    return getattr(cog, "service", None) if cog is not None else None


async def _reply(interaction: Interaction, text: str) -> None:
    await interaction.response.send_message(
        view=container_view(ui.TextDisplay(text)),
        ephemeral=True,
    )


async def _management(interaction: Interaction) -> PromotionService | None:
    service = _service(interaction)
    if service is None:
        await _reply(interaction, "Promotions are unavailable.")
        return None
    if not isinstance(interaction.user, discord.Member) or not is_management(interaction.user):
        await _reply(interaction, "Management only.")
        return None
    return service


def _button(
    label: str, style: discord.ButtonStyle, action: str, promotion_id: int
) -> ui.Button[Any]:
    return ui.Button(label=label, style=style, custom_id=f"promotion:{action}:{promotion_id}")


class SubmitPromotionButton(ui.DynamicItem[ui.Button[Any]], template=SUBMIT_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(
            _button("Submit Details", discord.ButtonStyle.success, "submit", promotion_id)
        )
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> SubmitPromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            await _reply(interaction, "Promotions are unavailable.")
            return
        await service.open_submit(interaction, self.promotion_id)


class ApprovePromotionButton(ui.DynamicItem[ui.Button[Any]], template=APPROVE_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(_button("Approve", discord.ButtonStyle.success, "approve", promotion_id))
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ApprovePromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = await _management(interaction)
        if service is not None:
            await service.open_picker(interaction, self.promotion_id, approving=True)


class DenyPromotionButton(ui.DynamicItem[ui.Button[Any]], template=DENY_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(_button("Deny", discord.ButtonStyle.danger, "deny", promotion_id))
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> DenyPromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.promotions.modals import DenyPromotionModal

        if await _management(interaction) is not None:
            await interaction.response.send_modal(DenyPromotionModal(self.promotion_id))


class EditPromotionButton(ui.DynamicItem[ui.Button[Any]], template=EDIT_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(_button("Edit", discord.ButtonStyle.secondary, "edit", promotion_id))
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> EditPromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = await _management(interaction)
        if service is not None:
            await service.open_edit(interaction, self.promotion_id)


class ReviewPromotionButton(ui.DynamicItem[ui.Button[Any]], template=REVIEW_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(_button("Review", discord.ButtonStyle.primary, "review", promotion_id))
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ReviewPromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = await _management(interaction)
        if service is not None:
            await service.review(interaction, self.promotion_id)


class ReschedulePromotionButton(ui.DynamicItem[ui.Button[Any]], template=RESCHEDULE_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(
            _button("Reschedule", discord.ButtonStyle.secondary, "reschedule", promotion_id)
        )
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ReschedulePromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = await _management(interaction)
        if service is not None:
            await service.open_picker(interaction, self.promotion_id, approving=False)


class PostedPromotionButton(ui.DynamicItem[ui.Button[Any]], template=POSTED_TEMPLATE):
    def __init__(self, promotion_id: int) -> None:
        super().__init__(_button("Posted", discord.ButtonStyle.success, "posted", promotion_id))
        self.promotion_id = promotion_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> PostedPromotionButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.promotions.modals import PostedPromotionModal

        if await _management(interaction) is not None:
            await interaction.response.send_modal(PostedPromotionModal(self.promotion_id))


class SlotSelect(ui.Select[Any]):
    def __init__(self, promotion_id: int, approving: bool, options: list[date]) -> None:
        choices = [
            discord.SelectOption(
                label=f"{'Suggested: ' if index == 0 and approving else ''}"
                f"{slot.strftime('%A %d %B %Y')}",
                value=slot.isoformat(),
            )
            for index, slot in enumerate(options)
        ]
        choices.append(discord.SelectOption(label="Custom date...", value="custom"))
        super().__init__(placeholder="Choose a posting slot", options=choices)
        self.promotion_id = promotion_id
        self.approving = approving

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.promotions.modals import CustomSlotModal

        service = await _management(interaction)
        if service is None:
            return
        choice = self.values[0] if self.values else ""
        if choice == "custom":
            await interaction.response.send_modal(
                CustomSlotModal(self.promotion_id, approving=self.approving)
            )
            return
        await service.schedule(
            interaction,
            self.promotion_id,
            date.fromisoformat(choice),
            approving=self.approving,
        )


def slot_picker(promotion_id: int, approving: bool, options: list[date]) -> AspectLayout:
    return container_view(
        ui.TextDisplay("## Allocate a Posting Slot" if approving else "## Reschedule Posting Slot"),
        ui.ActionRow(SlotSelect(promotion_id, approving, options)),
        timeout=300,
    )
