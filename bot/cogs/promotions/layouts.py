from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

import discord
from discord import ui

from bot.cogs.promotions.constants import (
    KIND_GIVEAWAY,
    KIND_LABELS,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_POSTED,
    STATUS_SUBMITTED,
    TIER_LABELS,
)
from bot.cogs.promotions.views import (
    ApprovePromotionButton,
    DenyPromotionButton,
    EditPromotionButton,
    PostedPromotionButton,
    ReschedulePromotionButton,
    ReviewPromotionButton,
    SubmitPromotionButton,
)
from bot.core.database import Promotion
from bot.core.ids import Emojis
from bot.shared.layout import AspectLayout, container_view

_SMALL = discord.SeparatorSpacing.small
_FOOTER = "https://cdn.discordapp.com/attachments/1553889994538750133/1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"


def slot_datetime(slot: date) -> datetime:
    return datetime.combine(slot, time(12), tzinfo=UTC)


def slot_text(slot: date | None) -> str:
    if slot is None:
        return "Unscheduled"
    moment = slot_datetime(slot)
    return f"{discord.utils.format_dt(moment, 'D')} ({discord.utils.format_dt(moment, 'R')})"


def title(promotion: Promotion) -> str:
    return f"{KIND_LABELS[promotion.kind]} #{promotion.id}"


def summary_text(promotion: Promotion) -> str:
    lines = [
        f"**Type:** {KIND_LABELS[promotion.kind]}",
        f"**Purchaser:** <@{promotion.owner_id}> [`{promotion.owner_id}`]",
        f"**Roblox:** `{promotion.roblox_id}`",
        f"**Transaction:** `{promotion.transaction_id}`",
        f"**Queue:** {TIER_LABELS[promotion.tier]}",
        f"**Status:** {promotion.status.title()}",
        f"**Slot:** {slot_text(promotion.slot)}",
    ]
    if promotion.reviewer_id is not None and promotion.status in {
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_POSTED,
    }:
        verb = "Denied" if promotion.status == STATUS_DENIED else "Approved"
        lines.append(f"**{verb} by:** <@{promotion.reviewer_id}>")
    if promotion.post_url:
        lines.append(f"**Post:** {promotion.post_url}")
    return "\n".join(lines)


def details_text(promotion: Promotion) -> str:
    data = promotion.data
    if not data:
        return "-# No details have been submitted yet."
    if promotion.kind == KIND_GIVEAWAY:
        return (
            f"**Prize:** {data.get('prize', '')}\n"
            f"**Discord Server:** {data.get('server', '')}\n"
            f"**Winner Count:** {data.get('winners', '')}\n"
            f"**Duration:** `{data.get('duration', '')}`"
        )
    quoted = "\n".join(f"> {line}" for line in str(data.get("text", "")).splitlines())
    return f"**Advertisement:**\n{quoted}"


def copyable_text(promotion: Promotion) -> str:
    data = promotion.data
    if promotion.kind == KIND_GIVEAWAY:
        body = (
            f"Prize: {data.get('prize', '')}\n"
            f"Server: {data.get('server', '')}\n"
            f"Winners: {data.get('winners', '')}\n"
            f"Duration: {data.get('duration', '')}"
        )
    else:
        body = str(data.get("text", ""))
    return "```\n" + body.replace("```", "`​``") + "\n```"


def log_layout(promotion: Promotion) -> AspectLayout:
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(f"## {Emojis.marketplace} {title(promotion)}"),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(summary_text(promotion)),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(details_text(promotion)),
    ]
    if promotion.status == STATUS_SUBMITTED:
        items.append(
            ui.ActionRow(
                ApprovePromotionButton(promotion.id).item,
                DenyPromotionButton(promotion.id).item,
                EditPromotionButton(promotion.id).item,
            )
        )
    elif promotion.status == STATUS_APPROVED:
        items.append(ui.ActionRow(EditPromotionButton(promotion.id).item))
    return container_view(*items)


def ticket_container(promotion: Promotion) -> ui.Container[Any]:
    return ui.Container(
        ui.TextDisplay(f"## {Emojis.marketplace} {title(promotion)}"),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(summary_text(promotion)),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(details_text(promotion)),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.ActionRow(
            ReviewPromotionButton(promotion.id).item,
            ReschedulePromotionButton(promotion.id).item,
            PostedPromotionButton(promotion.id).item,
        ),
    )


def review_layout(promotion: Promotion) -> AspectLayout:
    return container_view(
        ui.TextDisplay(f"## Review {title(promotion)}"),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(summary_text(promotion)),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(copyable_text(promotion)),
    )


def notice_layout(heading: str, text: str) -> AspectLayout:
    return container_view(
        ui.TextDisplay(f"## {heading}\n{text}"),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.MediaGallery(discord.MediaGalleryItem(_FOOTER)),
    )


def submit_layout(promotion: Promotion, heading: str, text: str) -> AspectLayout:
    return container_view(
        ui.TextDisplay(f"## {heading}\n{text}"),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.TextDisplay(
            f"**Item:** {KIND_LABELS[promotion.kind]}\n"
            f"**Transaction:** `{promotion.transaction_id}`\n"
            f"**Queue:** {TIER_LABELS[promotion.tier]}"
        ),
        ui.ActionRow(SubmitPromotionButton(promotion.id).item),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.MediaGallery(discord.MediaGalleryItem(_FOOTER)),
    )


def live_layout(promotion: Promotion, url: str) -> AspectLayout:
    return container_view(
        ui.TextDisplay(
            f"## {Emojis.approve} Your {KIND_LABELS[promotion.kind]} is live!\n"
            f"Your {KIND_LABELS[promotion.kind]} `#{promotion.id}` has been posted in "
            "**Aspect Network**. Thank you for your purchase!"
        ),
        ui.ActionRow(ui.Button(label="View Post", url=url)),
        ui.Separator(visible=True, spacing=_SMALL),
        ui.MediaGallery(discord.MediaGalleryItem(_FOOTER)),
    )
