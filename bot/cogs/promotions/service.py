from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import discord
from discord import ui

from bot.cogs.promotions.constants import (
    DAILY_PUSH_DAYS,
    ITEMS,
    KIND_ADVERT,
    KIND_LABELS,
    KINDS,
    STATUS_APPROVED,
    STATUS_CLAIMED,
    STATUS_DENIED,
    STATUS_SUBMITTED,
    TIER_DAILY,
    TIER_LABELS,
    TIER_NORMAL,
    TIER_RANK,
)
from bot.cogs.promotions.layouts import (
    live_layout,
    log_layout,
    notice_layout,
    review_layout,
    slot_text,
    submit_layout,
    ticket_container,
)
from bot.cogs.promotions.models import (
    first_invite_code,
    picker_dates,
    post_link,
    suggest_slot,
    upgraded_slot,
)
from bot.cogs.promotions.views import SubmitPromotionButton, slot_picker
from bot.cogs.tickets import Tickets
from bot.core.bot import Aspect
from bot.core.database import Promotion
from bot.core.ids import App, Channels, Emojis, Guild, Roles
from bot.services.dock import DockError
from bot.services.roblox import Sale
from bot.shared.checks import database, is_management
from bot.shared.errors import DatabaseUnavailable, report_interaction
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Interaction = discord.Interaction[Any]


def today() -> date:
    return datetime.now(UTC).date()


class PromotionService:
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self._server_names: dict[str, str] = {}

    async def reply(self, interaction: Interaction, text: str) -> None:
        view = container_view(ui.TextDisplay(text))
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)

    def management(self, interaction: Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and is_management(interaction.user)

    async def channel(self, channel_id: int | None) -> discord.abc.Messageable | None:
        if channel_id is None:
            return None
        found = self.bot.get_channel(channel_id)
        if found is None:
            try:
                found = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return found if isinstance(found, discord.abc.Messageable) else None

    async def dm(self, user_id: int, view: ui.LayoutView) -> bool:
        user = self.bot.get_user(user_id)
        try:
            if user is None:
                user = await self.bot.fetch_user(user_id)
            await user.send(view=view)
        except discord.HTTPException:
            logger.warning("Could not DM promotion owner %s", user_id)
            return False
        return True

    async def linked_roblox(self, user_id: int) -> int | None:
        dock = self.bot.dock
        if dock is None:
            return None
        try:
            linked = await dock.linked_roblox(user_id, Guild.id)
        except DockError:
            return None
        return int(linked) if linked is not None else None

    async def sync_recent_sales(self) -> None:
        ingest = getattr(self.bot.get_cog("Purchases"), "ingest_new_sales", None)
        if ingest is None:
            return
        try:
            await ingest()
        except Exception:
            logger.exception("Could not refresh group sales for promotion claims")

    async def claim(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            db = database(self.bot)
        except DatabaseUnavailable as exc:
            await report_interaction(interaction, exc, where="Database")
            return
        roblox_id = await self.linked_roblox(interaction.user.id)
        if roblox_id is None:
            await self.reply(
                interaction,
                f"Link your Roblox account in <#{Channels.verify}> first, then press "
                "**Claim Purchase** again.",
            )
            return
        await self.sync_recent_sales()
        lines = await self.process_sales(interaction.user.id, roblox_id)
        waiting = await db.unsubmitted_promotions(interaction.user.id)
        if not lines and not waiting:
            await self.reply(
                interaction,
                "No unclaimed purchases were found for your linked Roblox account. "
                "New purchases can take a minute to appear.",
            )
            return
        items: list[ui.Item[Any]] = [ui.TextDisplay("## Claim Purchase")]
        if lines:
            items.append(ui.TextDisplay("\n".join(lines)))
        for promotion in waiting[:5]:
            items.append(
                ui.Section(
                    f"**{KIND_LABELS[promotion.kind]}** `#{promotion.id}` is waiting for "
                    "its details.",
                    accessory=SubmitPromotionButton(promotion.id).item,
                )
            )
        await interaction.followup.send(view=container_view(*items), ephemeral=True)

    async def process_sales(self, owner_id: int, roblox_id: int) -> list[str]:
        db = database(self.bot)
        lines: list[str] = []
        async with self.bot.lock_for(f"promotion-claim:{roblox_id}"):
            sales = [
                sale
                for sale in await db.unclaimed_sales(App.roblox_group_id, roblox_id, list(ITEMS))
                if sale.item_id in ITEMS
            ]
            sales.sort(key=lambda sale: (ITEMS[sale.item_id or 0] not in KINDS, sale.created))
            for sale in sales:
                kind = ITEMS[sale.item_id or 0]
                if kind in KINDS:
                    line = await self.claim_sale(owner_id, roblox_id, sale, kind)
                else:
                    line = await self.apply_upgrade(owner_id, sale, kind)
                if line:
                    lines.append(line)
        return lines

    async def claim_sale(self, owner_id: int, roblox_id: int, sale: Sale, kind: str) -> str | None:
        promotion = await database(self.bot).claim_promotion(
            sale.id,
            sale.item_id or 0,
            kind,
            owner_id,
            roblox_id,
        )
        if promotion is None:
            return None
        delivered = await self.dm(
            owner_id,
            submit_layout(
                promotion,
                f"{Emojis.approve} Purchase Received",
                f"Thank you for purchasing a **{KIND_LABELS[kind]}** "
                f"({discord.utils.format_dt(sale.created, 'f')}). Press **Submit Details** "
                "below to send it to our Management team.",
            ),
        )
        suffix = "" if delivered else " I could not DM you, so use the button below."
        return f"{Emojis.approve} Claimed **{KIND_LABELS[kind]}** (`{sale.id}`).{suffix}"

    async def apply_upgrade(self, owner_id: int, sale: Sale, tier: str) -> str | None:
        db = database(self.bot)
        label = TIER_LABELS[tier]
        promotion = await db.active_promotion(owner_id)
        if promotion is None:
            return (
                f"{Emojis.warn} Your **{label}** purchase (`{sale.id}`) needs a Sponsored "
                "Giveaway or Paid Advertisement first. Claim one, then press "
                "**Claim Purchase** again."
            )
        if TIER_RANK[tier] <= TIER_RANK[promotion.tier]:
            return (
                f"{Emojis.warn} Your {KIND_LABELS[promotion.kind]} is already in the "
                f"**{TIER_LABELS[promotion.tier]}**, so the **{label}** purchase "
                f"(`{sale.id}`) was not used."
            )
        slot = (
            upgraded_slot(today(), promotion.slot, promotion.tier, tier)
            if promotion.slot is not None
            else None
        )
        updated = await db.claim_upgrade(
            sale.id,
            sale.item_id or 0,
            owner_id,
            promotion.id,
            tier,
            slot,
        )
        if updated is None:
            return None
        shifted = await self.push_back(updated) if tier == TIER_DAILY else []
        text = (
            f"Your **{KIND_LABELS[updated.kind]}** `#{updated.id}` was upgraded to the **{label}**."
        )
        if updated.slot is not None:
            text += f" It is now scheduled for {slot_text(updated.slot)}."
        await self.dm(owner_id, notice_layout(f"{Emojis.approve} Queue Upgraded", text))
        moved = (
            f" The slot moved from {slot_text(promotion.slot)} to {slot_text(updated.slot)}."
            if promotion.slot != updated.slot
            else ""
        )
        await self.alert(
            updated,
            f"<@&{Roles.management}> <@{owner_id}> upgraded **{KIND_LABELS[updated.kind]}** "
            f"`#{updated.id}` to the **{label}** (transaction `{sale.id}`).{moved}",
        )
        await self.refresh(updated)
        for other in shifted:
            await self.notify_slot(other, moved_by_daily=True)
        return f"{Emojis.approve} {text}"

    async def push_back(self, promotion: Promotion) -> list[Promotion]:
        if promotion.slot is None:
            return []
        shifted = await database(self.bot).shift_promotion_slots(
            promotion.slot,
            DAILY_PUSH_DAYS,
            promotion.id,
        )
        for other in shifted:
            await self.refresh(other)
        return shifted

    async def notify_slot(self, promotion: Promotion, *, moved_by_daily: bool = False) -> None:
        reason = " because a Daily Queue item was added ahead of it" if moved_by_daily else ""
        await self.dm(
            promotion.owner_id,
            notice_layout(
                "Posting Slot Updated",
                f"Your **{KIND_LABELS[promotion.kind]}** `#{promotion.id}` is now scheduled "
                f"for {slot_text(promotion.slot)}{reason}.",
            ),
        )

    async def alert(self, promotion: Promotion, text: str) -> None:
        channel = await self.channel(promotion.ticket_channel_id)
        if channel is None:
            channel = await self.channel(Channels.bot_logs)
        if channel is None:
            return
        try:
            await channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True),
            )
        except discord.HTTPException:
            logger.warning("Could not send promotion alert for %s", promotion.id)

    async def publish_log(self, promotion: Promotion) -> None:
        channel = await self.channel(Channels.bot_logs)
        if channel is None:
            return
        view = log_layout(promotion)
        mentions = discord.AllowedMentions.none()
        if promotion.log_message_id is not None:
            try:
                message = await channel.fetch_message(promotion.log_message_id)
                await message.edit(view=view, allowed_mentions=mentions)
                return
            except discord.HTTPException:
                logger.warning("Could not edit promotion log %s", promotion.id)
        try:
            sent = await channel.send(view=view, allowed_mentions=mentions)
        except discord.HTTPException:
            logger.warning("Could not send promotion log %s", promotion.id)
            return
        await database(self.bot).set_promotion_log(promotion.id, sent.id)

    async def refresh(self, promotion: Promotion) -> None:
        await self.publish_log(promotion)
        channel = await self.channel(promotion.ticket_channel_id)
        tickets = self.bot.get_cog("Tickets")
        if isinstance(channel, discord.TextChannel) and isinstance(tickets, Tickets):
            await tickets.refresh_ticket_panel(channel)

    async def ticket_extra(self, channel_id: int) -> ui.Container[Any] | None:
        promotion = await database(self.bot).promotion_by_ticket(channel_id)
        if promotion is None or promotion.status != STATUS_APPROVED:
            return None
        return ticket_container(promotion)

    async def open_submit(self, interaction: Interaction, promotion_id: int) -> None:
        from bot.cogs.promotions.modals import AdvertModal, GiveawayModal

        promotion = await database(self.bot).promotion(promotion_id)
        if promotion is None or promotion.owner_id != interaction.user.id:
            await self.reply(interaction, "This purchase does not belong to you.")
            return
        if promotion.status not in {STATUS_CLAIMED, STATUS_DENIED}:
            await self.reply(interaction, "This purchase has already been submitted.")
            return
        modal = AdvertModal if promotion.kind == KIND_ADVERT else GiveawayModal
        await interaction.response.send_modal(
            modal(promotion.id, editing=False, data=promotion.data)
        )

    async def open_edit(self, interaction: Interaction, promotion_id: int) -> None:
        from bot.cogs.promotions.modals import AdvertModal, GiveawayModal

        promotion = await database(self.bot).promotion(promotion_id)
        if promotion is None or promotion.status not in {STATUS_SUBMITTED, STATUS_APPROVED}:
            await self.reply(interaction, "This submission can no longer be edited.")
            return
        modal = AdvertModal if promotion.kind == KIND_ADVERT else GiveawayModal
        await interaction.response.send_modal(
            modal(promotion.id, editing=True, data=promotion.data)
        )

    async def save(
        self,
        interaction: Interaction,
        promotion_id: int,
        data: dict[str, Any],
        *,
        editing: bool,
    ) -> None:
        db = database(self.bot)
        if editing:
            if not self.management(interaction):
                await self.reply(interaction, "Management only.")
                return
            await interaction.response.defer(ephemeral=True)
            promotion = await db.edit_promotion(promotion_id, data)
            if promotion is None:
                await self.reply(interaction, "This submission can no longer be edited.")
                return
            await self.refresh(promotion)
            await self.reply(interaction, "Submission updated.")
            return
        await interaction.response.defer(ephemeral=True)
        promotion = await db.submit_promotion(promotion_id, interaction.user.id, data)
        if promotion is None:
            await self.reply(interaction, "This purchase can no longer be submitted.")
            return
        await self.publish_log(promotion)
        await self.reply(
            interaction,
            f"{Emojis.approve} Your **{KIND_LABELS[promotion.kind]}** was submitted. "
            "You'll get a DM once Management schedules it.",
        )

    async def review(self, interaction: Interaction, promotion_id: int) -> None:
        promotion = await database(self.bot).promotion(promotion_id)
        if promotion is None:
            await self.reply(interaction, "That submission no longer exists.")
            return
        await interaction.response.send_message(
            view=review_layout(promotion),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def open_picker(
        self,
        interaction: Interaction,
        promotion_id: int,
        *,
        approving: bool,
    ) -> None:
        db = database(self.bot)
        promotion = await db.promotion(promotion_id)
        expected = STATUS_SUBMITTED if approving else STATUS_APPROVED
        if promotion is None or promotion.status != expected:
            await self.reply(
                interaction,
                "This submission has already been reviewed."
                if approving
                else "Only approved submissions can be rescheduled.",
            )
            return
        current = today()
        options = picker_dates(current)
        if approving:
            suggested = suggest_slot(current, await db.last_promotion_slot(), promotion.tier)
            options = [suggested, *(slot for slot in options if slot != suggested)]
        await interaction.response.send_message(
            view=slot_picker(promotion.id, approving, options),
            ephemeral=True,
        )

    async def schedule(
        self,
        interaction: Interaction,
        promotion_id: int,
        slot: date,
        *,
        approving: bool,
    ) -> None:
        if not self.management(interaction):
            await self.reply(interaction, "Management only.")
            return
        if slot < today():
            await self.reply(interaction, "That date is in the past.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        db = database(self.bot)
        if not approving:
            promotion = await db.set_promotion_slot(promotion_id, slot)
            if promotion is None:
                await self.reply(interaction, "Only approved submissions can be rescheduled.")
                return
            await self.notify_slot(promotion)
            await self.refresh(promotion)
            await self.reply(interaction, f"Rescheduled to {slot_text(slot)}.")
            return
        promotion = await db.approve_promotion(promotion_id, slot, interaction.user.id)
        if promotion is None:
            await self.reply(interaction, "This submission has already been reviewed.")
            return
        shifted = await self.push_back(promotion) if promotion.tier == TIER_DAILY else []
        channel = await self.open_ticket(promotion)
        if channel is not None:
            promotion = await db.promotion(promotion.id) or promotion
        await self.dm(
            promotion.owner_id,
            notice_layout(
                f"{Emojis.approve} Submission Approved",
                f"Your **{KIND_LABELS[promotion.kind]}** `#{promotion.id}` was approved and "
                f"is scheduled for {slot_text(slot)} in the "
                f"**{TIER_LABELS[promotion.tier]}**."
                + (f" Follow along in {channel.mention}." if channel is not None else ""),
            ),
        )
        await self.publish_log(promotion)
        for other in shifted:
            await self.notify_slot(other, moved_by_daily=True)
        ticket = (
            f" Ticket: {channel.mention}."
            if channel is not None
            else (" I could not open a ticket for the purchaser.")
        )
        await self.reply(interaction, f"Approved for {slot_text(slot)}.{ticket}")

    async def open_ticket(self, promotion: Promotion) -> discord.TextChannel | None:
        tickets = self.bot.get_cog("Tickets")
        guild = self.bot.get_guild(Guild.id)
        if not isinstance(tickets, Tickets) or guild is None:
            return None
        member = guild.get_member(promotion.owner_id)
        try:
            if member is None:
                member = await guild.fetch_member(promotion.owner_id)
            channel = await tickets.create_ticket_channel(
                guild,
                member,
                kind="management",
                reason=(
                    f"{KIND_LABELS[promotion.kind]} `#{promotion.id}` · "
                    f"Transaction `{promotion.transaction_id}`"
                ),
                extra=ticket_container(promotion),
            )
        except discord.HTTPException:
            logger.warning("Could not open a promotion ticket for %s", promotion.id)
            return None
        if channel is not None:
            await database(self.bot).set_promotion_ticket(promotion.id, channel.id)
        return channel

    async def deny(self, interaction: Interaction, promotion_id: int, reason: str) -> None:
        if not self.management(interaction):
            await self.reply(interaction, "Management only.")
            return
        await interaction.response.defer(ephemeral=True)
        promotion = await database(self.bot).deny_promotion(promotion_id, interaction.user.id)
        if promotion is None:
            await self.reply(interaction, "This submission has already been reviewed.")
            return
        await self.dm(
            promotion.owner_id,
            submit_layout(
                promotion,
                f"{Emojis.error} Submission Denied",
                f"Your **{KIND_LABELS[promotion.kind]}** `#{promotion.id}` was denied.\n"
                f"**Reason:** {reason}\n\nPress **Submit Details** to send it again.",
            ),
        )
        await self.publish_log(promotion)
        await self.reply(interaction, "Submission denied.")

    async def posted(self, interaction: Interaction, promotion_id: int, link: str) -> None:
        if not self.management(interaction):
            await self.reply(interaction, "Management only.")
            return
        parsed = post_link(link)
        if parsed is None or parsed[0] != Guild.id:
            await self.reply(interaction, "That is not a message link from this server.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        _guild_id, channel_id, message_id = parsed
        channel = await self.channel(channel_id)
        message: discord.Message | None = None
        if channel is not None:
            try:
                message = await channel.fetch_message(message_id)
            except discord.HTTPException:
                message = None
        if message is None:
            await self.reply(interaction, "I could not find that message.")
            return
        promotion = await database(self.bot).mark_promotion_posted(
            promotion_id,
            message.jump_url,
        )
        if promotion is None:
            await self.reply(interaction, "Only approved submissions can be marked as posted.")
            return
        await self.publish_log(promotion)
        await self.reply(interaction, "Marked as posted. Closing the ticket.")
        tickets = self.bot.get_cog("Tickets")
        if (
            isinstance(tickets, Tickets)
            and isinstance(interaction.channel, discord.TextChannel)
            and interaction.channel.id == promotion.ticket_channel_id
        ):
            await tickets.close_ticket(interaction, closed_by=interaction.user.id)
        await self.dm(promotion.owner_id, live_layout(promotion, message.jump_url))

    async def alert_due(self) -> None:
        for promotion in await database(self.bot).due_promotions(today()):
            await self.alert(
                promotion,
                f"<@&{Roles.management}> It's <@{promotion.owner_id}>'s turn! Their "
                f"**{KIND_LABELS[promotion.kind]}** `#{promotion.id}` is scheduled for "
                f"{slot_text(promotion.slot)}. Press **Review** for a final check, post it, "
                "then press **Posted**.",
            )
            await self.dm(
                promotion.owner_id,
                notice_layout(
                    "Posting Today",
                    f"Your **{KIND_LABELS[promotion.kind]}** `#{promotion.id}` is scheduled "
                    "to be posted today.",
                ),
            )

    async def claim_known_buyers(self) -> None:
        buyers = await database(self.bot).unclaimed_known_buyers(App.roblox_group_id, list(ITEMS))
        for owner_id, roblox_id in buyers:
            await self.process_sales(owner_id, roblox_id)

    async def server_name(self, promotion: Promotion) -> str:
        source = str(promotion.data.get("server") or promotion.data.get("text") or "")
        code = first_invite_code(source)
        if code is not None:
            if code not in self._server_names:
                try:
                    invite = await self.bot.fetch_invite(code)
                except discord.HTTPException:
                    invite = None
                guild = getattr(invite, "guild", None)
                if guild is not None:
                    self._server_names[code] = str(guild.name)
            if code in self._server_names:
                return self._server_names[code]
        user = self.bot.get_user(promotion.owner_id)
        return user.name if user is not None else f"User {promotion.owner_id}"

    async def queue_text(self) -> str:
        queued = await database(self.bot).queued_promotions()
        if not queued:
            return "## Advertisement Queue\nThe queue is empty."
        lines = ["## Advertisement Queue"]
        for index, promotion in enumerate(queued, start=1):
            mark = "" if promotion.tier == TIER_NORMAL else "!"
            lines.append(
                f"`{index}.` {slot_text(promotion.slot)} · "
                f"**{discord.utils.escape_markdown(await self.server_name(promotion))}{mark}** · "
                f"{KIND_LABELS[promotion.kind]} · {TIER_LABELS[promotion.tier]}"
            )
        return "\n".join(lines)[:4000]
