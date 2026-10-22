from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import discord
from discord import ui

from bot.cogs.promotions.constants import MAX_ADVERT_LENGTH
from bot.cogs.promotions.models import advert_data, giveaway_data, parse_date
from bot.cogs.promotions.views import _service
from bot.shared.layout import container_view

Interaction = discord.Interaction[Any]


def _text(label: ui.Label[Any]) -> str:
    component = label.component
    assert isinstance(component, ui.TextInput)
    return str(component.value)


def _input(
    default: Any = None,
    *,
    placeholder: str | None = None,
    max_length: int = 100,
    paragraph: bool = False,
) -> ui.TextInput[Any]:
    return ui.TextInput(
        default=str(default) if default not in (None, "") else None,
        placeholder=placeholder,
        max_length=max_length,
        style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
        required=True,
    )


async def _error(interaction: Interaction, text: str) -> None:
    await interaction.response.send_message(
        view=container_view(ui.TextDisplay(text)),
        ephemeral=True,
    )


class GiveawayModal(ui.Modal, title="Sponsored Giveaway"):
    def __init__(self, promotion_id: int, *, editing: bool, data: dict[str, Any]) -> None:
        super().__init__()
        self.promotion_id = promotion_id
        self.editing = editing
        self.prize: ui.Label[Any] = ui.Label(
            text="Prize",
            description="Include its Robux value (minimum 500).",
            component=_input(data.get("prize"), placeholder="1,000 Robux", max_length=200),
        )
        self.server: ui.Label[Any] = ui.Label(
            text="Discord Server",
            component=_input(data.get("server"), placeholder="discord.gg/invite"),
        )
        self.winners: ui.Label[Any] = ui.Label(
            text="Winner Count",
            component=_input(data.get("winners"), placeholder="1", max_length=3),
        )
        self.duration: ui.Label[Any] = ui.Label(
            text="Duration",
            description="Maximum 7d.",
            component=_input(data.get("duration"), placeholder="3d", max_length=10),
        )
        self.add_item(self.prize)
        self.add_item(self.server)
        self.add_item(self.winners)
        self.add_item(self.duration)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        data, error = giveaway_data(
            _text(self.prize),
            _text(self.server),
            _text(self.winners),
            _text(self.duration),
        )
        if data is None:
            await _error(interaction, error or "Those details are not valid.")
            return
        await service.save(interaction, self.promotion_id, data, editing=self.editing)


class AdvertModal(ui.Modal, title="Paid Advertisement"):
    def __init__(self, promotion_id: int, *, editing: bool, data: dict[str, Any]) -> None:
        super().__init__()
        self.promotion_id = promotion_id
        self.editing = editing
        self.advert: ui.Label[Any] = ui.Label(
            text="Advertisement",
            description="Paste your full advertisement.",
            component=_input(data.get("text"), max_length=MAX_ADVERT_LENGTH, paragraph=True),
        )
        self.add_item(self.advert)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        data, error = advert_data(_text(self.advert))
        if data is None:
            await _error(interaction, error or "That advertisement is not valid.")
            return
        await service.save(interaction, self.promotion_id, data, editing=self.editing)


class DenyPromotionModal(ui.Modal, title="Deny Submission"):
    def __init__(self, promotion_id: int) -> None:
        super().__init__()
        self.promotion_id = promotion_id
        self.reason: ui.Label[Any] = ui.Label(
            text="Reason",
            component=_input(max_length=1000, paragraph=True),
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is not None:
            await service.deny(interaction, self.promotion_id, _text(self.reason).strip())


class PostedPromotionModal(ui.Modal, title="Mark as Posted"):
    def __init__(self, promotion_id: int) -> None:
        super().__init__()
        self.promotion_id = promotion_id
        self.link: ui.Label[Any] = ui.Label(
            text="Message Link",
            component=_input(
                placeholder="https://discord.com/channels/...",
                max_length=200,
            ),
        )
        self.add_item(self.link)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is not None:
            await service.posted(interaction, self.promotion_id, _text(self.link))


class CustomSlotModal(ui.Modal, title="Custom Posting Slot"):
    def __init__(self, promotion_id: int, *, approving: bool) -> None:
        super().__init__()
        self.promotion_id = promotion_id
        self.approving = approving
        self.date: ui.Label[Any] = ui.Label(
            text="Date",
            component=_input(placeholder="24/10/2026", max_length=10),
        )
        self.order: ui.Label[Any] = ui.Label(
            text="Format",
            component=ui.Select(
                options=[
                    discord.SelectOption(label="DD/MM/YYYY", value="dmy", default=True),
                    discord.SelectOption(label="MM/DD/YYYY", value="mdy"),
                ],
                min_values=1,
                max_values=1,
                required=True,
            ),
        )
        self.add_item(self.date)
        self.add_item(self.order)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        order_select = self.order.component
        assert isinstance(order_select, ui.Select)
        order = order_select.values[0] if order_select.values else "dmy"
        slot = parse_date(_text(self.date), order, datetime.now(UTC).date())
        if slot is None:
            await _error(interaction, "That date is not valid, or it is in the past.")
            return
        await service.schedule(interaction, self.promotion_id, slot, approving=self.approving)
