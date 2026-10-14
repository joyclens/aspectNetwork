from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import discord

from bot.cogs.packages.constants import (
    CONFIRM_COOLDOWN_SECONDS,
    FORUM_CHANNELS,
    IMAGE_TYPES,
    KIND_GIFT,
    PACKAGER_SHARE_PERCENT,
    PURCHASE_TTL_SECONDS,
    REPORT_COOLDOWN_SECONDS,
    SELL_ONE_TIME,
    SHOWCASE_TYPES,
    STATUS_ACCEPTED,
    STATUS_SOLD,
)
from bot.cogs.packages.layouts import forum_layout, report_layout, submission_layout
from bot.cogs.packages.models import (
    PackageDraft,
    StoredFile,
    packager_share,
    resolve_purchase_kind,
)
from bot.cogs.packages.roblox import GamePassClient, GamePassError, reviewer_message
from bot.core.bot import Aspect
from bot.core.database import Package, PackagePurchase
from bot.core.ids import Channels, Roles
from bot.services.dock import DockError
from bot.shared.checks import database
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Interaction = discord.Interaction[Any]


class PackageService:
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self.drafts: dict[int, PackageDraft] = {}
        self._confirm_at: dict[int, float] = {}

    def gamepass(self) -> GamePassClient | None:
        key = self.bot.settings.roblox_api_key
        if key is None:
            return None
        raw = key.get_secret_value().strip()
        if not raw:
            return None
        return GamePassClient(
            raw,
            self.bot.settings.roblox_universe_id,
            self.bot.session,
        )

    def draft_for(self, user_id: int) -> PackageDraft:
        draft = self.drafts.get(user_id)
        if draft is None or draft.expired():
            draft = PackageDraft(user_id=user_id)
            self.drafts[user_id] = draft
        return draft

    def clear_draft(self, user_id: int) -> None:
        self.drafts.pop(user_id, None)

    def has_role(self, member: discord.Member, role_id: int) -> bool:
        if role_id < 1:
            return False
        return member.get_role(role_id) is not None or member.guild_permissions.administrator

    def is_packager(self, member: discord.Member) -> bool:
        return self.has_role(member, Roles.packager)

    def is_management(self, member: discord.Member) -> bool:
        return self.has_role(member, Roles.management)

    async def channel(self, channel_id: int) -> discord.abc.MessageableChannel | None:
        if channel_id < 1:
            return None
        found = self.bot.get_channel(channel_id)
        if found is None:
            try:
                found = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return found  # type: ignore[return-value]

    async def linked_roblox(self, user_id: int) -> int | None:
        from bot.core.ids import Guild

        dock = self.bot.dock
        if dock is None:
            return None
        try:
            linked = await dock.linked_roblox(user_id, Guild.id)
        except DockError:
            return None
        if linked is None:
            return None
        return int(linked)

    async def store_files(self, draft: PackageDraft) -> tuple[int, int, str]:
        channel = await self.channel(Channels.package_storage)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("Package storage channel is unavailable.")
        if draft.showcase is None or not draft.files:
            raise RuntimeError("Draft files are incomplete.")
        files = [
            discord.File(io.BytesIO(draft.showcase.data), filename=draft.showcase.filename),
            *[
                discord.File(io.BytesIO(item.data), filename=item.filename)
                for item in draft.files
            ],
        ]
        message = await channel.send(
            content=f"package-storage:{draft.user_id}",
            files=files,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return channel.id, message.id, draft.showcase.filename

    async def submit_final(self, interaction: Interaction, draft: PackageDraft) -> Package:
        from bot.cogs.packages.views import ApproveButton, DenyButton

        channel_id, message_id, showcase_name = await self.store_files(draft)
        submissions = await self.channel(Channels.package_submissions)
        if not isinstance(submissions, discord.TextChannel):
            raise RuntimeError("Package submissions channel is unavailable.")
        assert draft.package_type and draft.title and draft.price is not None
        assert draft.description and draft.sell_type is not None
        assert draft.customizable is not None and draft.showcase is not None
        db = database(self.bot)
        package = await db.create_package(
            packager_id=draft.user_id,
            package_type=draft.package_type,
            title=draft.title,
            price=draft.price,
            description=draft.description,
            sell_type=draft.sell_type,
            customizable=draft.customizable,
            storage_channel_id=channel_id,
            storage_message_id=message_id,
            submission_channel_id=submissions.id,
            submission_message_id=0,
            showcase_filename=showcase_name,
        )
        showcase = discord.File(io.BytesIO(draft.showcase.data), filename=showcase_name)
        posted = await submissions.send(
            view=submission_layout(
                package,
                showcase_filename=showcase_name,
                showcase_content_type=draft.showcase.content_type,
                buttons=[ApproveButton(package.id), DenyButton(package.id)],
            ),
            file=showcase,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await db.set_package_submission(package.id, posted.id)
        self.clear_draft(draft.user_id)
        return package

    async def approve(self, interaction: Interaction, package_id: int) -> str | None:
        from bot.cogs.packages.views import PurchaseButton, ReportButton

        if not isinstance(interaction.user, discord.Member) or not self.is_management(
            interaction.user
        ):
            return "Management only."
        client = self.gamepass()
        if client is None:
            return "Roblox Open Cloud API key is not configured."
        db = database(self.bot)
        claimed = await db.claim_package(package_id, interaction.user.id)
        if claimed is None:
            return "This package is no longer pending."
        try:
            gamepass_id = await client.create_pass(
                name=claimed.title,
                description=claimed.description,
                price=claimed.price,
            )
            icon_note = ""
            showcase = await self._storage_attachment(claimed, claimed.showcase_filename)
            showcase_bytes: bytes | None = None
            content_type = showcase.content_type if showcase else None
            if showcase is not None:
                showcase_bytes = await showcase.read()
                if content_type in IMAGE_TYPES:
                    try:
                        await client.upload_icon(gamepass_id, showcase_bytes)
                    except GamePassError as exc:
                        icon_note = f" Icon upload failed: {reviewer_message(exc)}"
                else:
                    icon_note = " Showcase is a video; icon upload was skipped."
            forum_id = FORUM_CHANNELS.get(claimed.package_type, 0)
            forum = await self.channel(forum_id)
            if not isinstance(forum, discord.ForumChannel):
                raise RuntimeError("Forum channel is unavailable for this package type.")
            thread_kwargs: dict[str, Any] = {
                "name": claimed.title[:100],
                "view": forum_layout(
                    claimed,
                    showcase_filename=claimed.showcase_filename,
                    showcase_content_type=content_type,
                    buttons=[PurchaseButton(claimed.id), ReportButton(claimed.id)],
                ),
                "allowed_mentions": discord.AllowedMentions.none(),
            }
            if showcase is not None and showcase_bytes is not None:
                thread_kwargs["file"] = discord.File(
                    io.BytesIO(showcase_bytes),
                    filename=showcase.filename,
                )
            thread_with = await forum.create_thread(**thread_kwargs)
            accepted = await db.accept_package(
                claimed.id,
                gamepass_id=gamepass_id,
                forum_channel_id=forum.id,
                forum_thread_id=thread_with.thread.id,
                forum_message_id=thread_with.message.id,
            )
            if accepted is None:
                raise RuntimeError("Failed to mark package accepted.")
            status = f"-# Approved by <@{interaction.user.id}>{icon_note}"
            if interaction.message is not None:
                await interaction.message.edit(
                    view=submission_layout(
                        accepted,
                        showcase_filename=accepted.showcase_filename,
                        status_line=status,
                    ),
                    attachments=interaction.message.attachments,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            await self._dm(
                accepted.packager_id,
                f"Your package **{accepted.title}** was approved.",
            )
            return None
        except GamePassError as exc:
            await db.revert_package_pending(package_id)
            return reviewer_message(exc)
        except Exception as exc:
            await db.revert_package_pending(package_id)
            logger.exception("Package approve failed")
            return str(exc) or "Approval failed."

    async def deny(self, interaction: Interaction, package_id: int, reason: str) -> str | None:
        if not isinstance(interaction.user, discord.Member) or not self.is_management(
            interaction.user
        ):
            return "Management only."
        db = database(self.bot)
        denied = await db.deny_package(package_id, interaction.user.id)
        if denied is None:
            return "This package cannot be denied."
        status = f"-# Denied by <@{interaction.user.id}>: {reason}"
        if interaction.message is not None:
            await interaction.message.edit(
                view=submission_layout(
                    denied,
                    showcase_filename=denied.showcase_filename,
                    status_line=status,
                ),
                attachments=interaction.message.attachments,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        await self._dm(
            denied.packager_id,
            f"Your package **{denied.title}** was denied.\nReason: {reason}",
        )
        return None

    async def start_purchase(
        self,
        interaction: Interaction,
        package_id: int,
        kind_raw: str,
        recipient: discord.User | None,
    ) -> tuple[PackagePurchase | None, str | None]:
        if interaction.user.bot:
            return None, "Bots cannot purchase packages."
        db = database(self.bot)
        package = await db.package(package_id)
        if package is None:
            return None, "Package not found."
        if package.status == STATUS_SOLD:
            return None, "This package has been sold."
        if package.status != STATUS_ACCEPTED:
            return None, "This package is not available."
        if package.packager_id == interaction.user.id:
            return None, "You cannot buy your own package."
        kind = resolve_purchase_kind(
            kind_raw,
            interaction.user.id,
            recipient.id if recipient is not None else None,
        )
        if kind is None:
            return None, "Gift purchases require a recipient."
        if kind == KIND_GIFT and recipient is not None and recipient.bot:
            return None, "You cannot gift to a bot."
        roblox_id = await self.linked_roblox(interaction.user.id)
        if roblox_id is None:
            return None, "Verify your Roblox account before purchasing."
        if package.gamepass_id is not None:
            client = self.gamepass()
            if client is not None:
                try:
                    owns = await client.owns_pass(roblox_id, package.gamepass_id)
                except GamePassError as exc:
                    return None, reviewer_message(exc)
                if owns and not await db.buyer_owns_package(package.id, interaction.user.id):
                    return None, "You already own this game pass."
        if await db.buyer_owns_package(package.id, interaction.user.id):
            return None, "You already have an active purchase for this package."
        purchase = await db.create_purchase(
            package_id=package.id,
            buyer_id=interaction.user.id,
            buyer_roblox_id=roblox_id,
            recipient_id=recipient.id if kind == KIND_GIFT and recipient else None,
            kind=kind,
            expires_at=datetime.now(UTC) + timedelta(seconds=PURCHASE_TTL_SECONDS),
        )
        return purchase, None

    def confirm_ready(self, user_id: int, now: float) -> bool:
        last = self._confirm_at.get(user_id, 0)
        if now - last < CONFIRM_COOLDOWN_SECONDS:
            return False
        self._confirm_at[user_id] = now
        return True

    async def complete_purchase(self, purchase: PackagePurchase) -> None:
        db = database(self.bot)
        package = await db.package(purchase.package_id)
        if package is None:
            return
        packager_amount, network_amount = packager_share(package.price, PACKAGER_SHARE_PERCENT)
        paid = await db.mark_purchase_paid(
            purchase.id,
            packager_id=package.packager_id,
            gross=package.price,
            packager_amount=packager_amount,
            network_amount=network_amount,
        )
        if paid is None:
            return
        delivered = await self.deliver_files(paid, package)
        if not delivered:
            await db.mark_purchase_undelivered(paid.id)
        else:
            await db.mark_purchase_delivered(paid.id)
        await self._notify_packager_sale(package, paid)
        if package.sell_type == SELL_ONE_TIME:
            await self._close_one_time(package)

    async def deliver_files(self, purchase: PackagePurchase, package: Package) -> bool:
        target_id = (
            purchase.recipient_id
            if purchase.kind == KIND_GIFT and purchase.recipient_id is not None
            else purchase.buyer_id
        )
        files = await self._storage_files(package)
        if not files:
            return False
        ok = await self._dm_files(target_id, package, files)
        if purchase.kind == KIND_GIFT:
            await self._dm(
                purchase.buyer_id,
                f"Your gift of **{package.title}** was "
                + ("delivered." if ok else "paid but could not be delivered."),
            )
        return ok

    async def report(
        self,
        interaction: Interaction,
        package_id: int,
        issue: str,
    ) -> str | None:
        db = database(self.bot)
        package = await db.package(package_id)
        if package is None:
            return "Package not found."
        since = datetime.now(UTC) - timedelta(seconds=REPORT_COOLDOWN_SECONDS)
        if await db.recent_report(package_id, interaction.user.id, since):
            return "You already reported this package recently."
        await db.add_report(package_id, interaction.user.id, issue)
        jump = (
            f"https://discord.com/channels/{interaction.guild_id}/"
            f"{package.forum_thread_id}/{package.forum_message_id}"
            if package.forum_thread_id and package.forum_message_id
            else "N/A"
        )
        channel = await self.channel(Channels.package_submissions)
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                view=report_layout(package, interaction.user.id, issue, jump),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        return None

    async def _close_one_time(self, package: Package) -> None:
        db = database(self.bot)
        sold = await db.mark_package_sold(package.id)
        if sold is None:
            return
        client = self.gamepass()
        if client is not None and sold.gamepass_id is not None:
            try:
                await client.close_sale(sold.gamepass_id)
            except GamePassError:
                logger.exception("Could not close game pass sale")
        if sold.forum_thread_id is None:
            return
        try:
            thread = self.bot.get_channel(sold.forum_thread_id)
            if thread is None:
                thread = await self.bot.fetch_channel(sold.forum_thread_id)
            if isinstance(thread, discord.Thread):
                if sold.forum_message_id is not None:
                    message = await thread.fetch_message(sold.forum_message_id)
                    await message.edit(
                        view=forum_layout(
                            sold,
                            showcase_filename=sold.showcase_filename,
                            status_line="-# Sold",
                        ),
                        attachments=message.attachments,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                await thread.edit(archived=True, locked=True)
        except discord.HTTPException:
            logger.warning("Could not update sold forum post for package %s", package.id)

    async def _notify_packager_sale(self, package: Package, purchase: PackagePurchase) -> None:
        text = (
            f"Your package **{package.title}** sold "
            f"(`{package.price:,}` R$). Purchase `{purchase.id}`."
        )
        if await self._dm(package.packager_id, text):
            return
        channel = await self.channel(Channels.package_submissions)
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                view=container_view(
                    discord.ui.TextDisplay(f"<@{package.packager_id}> {text}")
                ),
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    async def _dm(self, user_id: int, text: str) -> bool:
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(view=container_view(discord.ui.TextDisplay(text)))
            return True
        except discord.HTTPException:
            return False

    async def _dm_files(
        self,
        user_id: int,
        package: Package,
        files: list[discord.File],
    ) -> bool:
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(
                view=container_view(
                    discord.ui.TextDisplay(f"Files for **{package.title}**:")
                ),
            )
            batch: list[discord.File] = []
            size = 0
            for item in files:
                raw = item.fp.read()
                item.fp.seek(0)
                if batch and size + len(raw) > 7_500_000:
                    await user.send(files=batch)
                    batch = []
                    size = 0
                batch.append(discord.File(io.BytesIO(raw), filename=item.filename))
                size += len(raw)
            if batch:
                await user.send(files=batch)
            return True
        except discord.HTTPException:
            return False

    async def _storage_attachment(
        self,
        package: Package,
        filename: str,
    ) -> discord.Attachment | None:
        if package.storage_channel_id is None or package.storage_message_id is None:
            return None
        channel = await self.channel(package.storage_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            message = await channel.fetch_message(package.storage_message_id)
        except discord.HTTPException:
            return None
        for attachment in message.attachments:
            if attachment.filename == filename:
                return attachment
        return message.attachments[0] if message.attachments else None

    async def _storage_files(self, package: Package) -> list[discord.File]:
        if package.storage_channel_id is None or package.storage_message_id is None:
            return []
        channel = await self.channel(package.storage_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return []
        try:
            message = await channel.fetch_message(package.storage_message_id)
        except discord.HTTPException:
            return []
        files: list[discord.File] = []
        for attachment in message.attachments:
            if attachment.filename == package.showcase_filename:
                continue
            data = await attachment.read()
            files.append(discord.File(io.BytesIO(data), filename=attachment.filename))
        return files


def file_from_upload(attachment: discord.Attachment, data: bytes) -> StoredFile | None:
    content = (attachment.content_type or "").lower()
    if content not in SHOWCASE_TYPES and not content:
        content = "application/octet-stream"
    return StoredFile(
        filename=attachment.filename[:200],
        content_type=content,
        data=data,
    )


def is_showcase_ok(attachment: discord.Attachment) -> bool:
    content = (attachment.content_type or "").lower()
    return content in SHOWCASE_TYPES
