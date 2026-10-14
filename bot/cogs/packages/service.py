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
from bot.cogs.packages.media import (
    first_image_showcase,
    media_from_attachments,
    parse_storage_ids,
    safe_filename,
)
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
        self._submitting: set[int] = set()

    def begin_submit(self, user_id: int) -> bool:
        if user_id in self._submitting:
            return False
        self._submitting.add(user_id)
        return True

    def end_submit(self, user_id: int) -> None:
        self._submitting.discard(user_id)

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
        if member.guild_permissions.administrator:
            return True
        if member.get_role(role_id) is not None:
            return True
        return any(role.id == role_id for role in member.roles)

    def is_packager(self, member: discord.Member) -> bool:
        return self.has_role(member, Roles.packager)

    def is_management(self, member: discord.Member) -> bool:
        return self.has_role(member, Roles.management)

    def can_submit(self, member: discord.Member) -> bool:
        return self.is_packager(member) or self.is_management(member)

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

    async def store_files(
        self,
        draft: PackageDraft,
    ) -> tuple[int, int, str, list[discord.Message]]:
        channel = await self.channel(Channels.package_storage)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("Package storage channel is unavailable.")
        if not draft.showcases or not draft.files:
            raise RuntimeError("Draft files are incomplete.")
        ordered: list[tuple[str, StoredFile]] = [
            ("showcase_", item) for item in draft.showcases
        ] + [("package_", item) for item in draft.files]
        messages: list[discord.Message] = []
        for start in range(0, len(ordered), 10):
            window = ordered[start : start + 10]
            files = [
                discord.File(
                    io.BytesIO(stored.data),
                    filename=safe_filename(index, stored.filename, prefix=prefix),
                )
                for index, (prefix, stored) in enumerate(window)
            ]
            messages.append(
                await channel.send(
                    content=f"package-storage:{draft.user_id}:pending",
                    files=files,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            )
        ids = ",".join(str(message.id) for message in messages)
        await messages[0].edit(content=f"package-storage:{draft.user_id}:{ids}")
        icon = first_image_showcase(draft.showcases) or draft.showcases[0]
        return channel.id, messages[0].id, icon.filename, messages

    async def submit_final(self, interaction: Interaction, draft: PackageDraft) -> Package:
        from bot.cogs.packages.views import ApproveButton, DenyButton

        channel_id, message_id, showcase_name, storage_messages = await self.store_files(
            draft
        )
        submissions = await self.channel(Channels.package_submissions)
        if not isinstance(submissions, discord.TextChannel):
            raise RuntimeError("Package submissions channel is unavailable.")
        assert draft.package_type and draft.title and draft.price is not None
        assert draft.description and draft.sell_type is not None
        assert draft.customizable is not None and draft.showcases
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
        # Use storage CDN URLs in MediaGallery/File — avoids attachment:// mismatch 50035.
        media: list[tuple[str, str | None]] = []
        for message in storage_messages:
            media.extend(media_from_attachments(message.attachments))
        posted = await submissions.send(
            view=submission_layout(
                package,
                media=media,
                buttons=[
                    ApproveButton(package.id).item,
                    DenyButton(package.id).item,
                ],
            ),
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
            storage_messages = await self._storage_messages(claimed)
            storage_media = media_from_attachments(
                [item for message in storage_messages for item in message.attachments]
            )
            showcase = self._pick_showcase_attachment(claimed, storage_messages)
            forum_file: discord.File | None = None
            forum_media: list[tuple[str, str | None]] = []
            if showcase is not None:
                content_type = showcase.content_type
                showcase_bytes = await showcase.read()
                uploaded = discord.File(
                    io.BytesIO(showcase_bytes),
                    filename=safe_filename(0, showcase.filename, prefix="showcase_"),
                )
                forum_file = uploaded
                forum_media = [(uploaded.uri, content_type)]
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
                    media=forum_media or storage_media[:1] or None,
                    buttons=[
                        PurchaseButton(claimed.id).item,
                        ReportButton(claimed.id).item,
                    ],
                ),
                "allowed_mentions": discord.AllowedMentions.none(),
            }
            if forum_file is not None:
                thread_kwargs["file"] = forum_file
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
                        media=storage_media or None,
                        status_line=status,
                        buttons=None,
                    ),
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
            storage_media = media_from_attachments(
                [
                    item
                    for message in await self._storage_messages(denied)
                    for item in message.attachments
                ]
            )
            await interaction.message.edit(
                view=submission_layout(
                    denied,
                    media=storage_media or None,
                    status_line=status,
                    buttons=None,
                ),
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
                    kept = media_from_attachments(message.attachments)
                    await message.edit(
                        view=forum_layout(
                            sold,
                            media=kept or None,
                            status_line="-# Sold",
                            buttons=None,
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

    async def _storage_messages(self, package: Package) -> list[discord.Message]:
        if package.storage_channel_id is None or package.storage_message_id is None:
            return []
        channel = await self.channel(package.storage_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return []
        try:
            first = await channel.fetch_message(package.storage_message_id)
        except discord.HTTPException:
            return []
        ids = parse_storage_ids(first.content, first.id)
        messages: list[discord.Message] = []
        for message_id in ids:
            if message_id == first.id:
                messages.append(first)
                continue
            try:
                messages.append(await channel.fetch_message(message_id))
            except discord.HTTPException:
                continue
        return messages or [first]

    def _pick_showcase_attachment(
        self,
        package: Package,
        messages: list[discord.Message],
    ) -> discord.Attachment | None:
        attachments = [item for message in messages for item in message.attachments]
        if not attachments:
            return None
        for attachment in attachments:
            name = attachment.filename.lower()
            if name.startswith("showcase_") or attachment.filename == package.showcase_filename:
                content = (attachment.content_type or "").lower()
                if content in IMAGE_TYPES or name.endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp")
                ):
                    return attachment
        for attachment in attachments:
            if attachment.filename.startswith("showcase_"):
                return attachment
        return attachments[0]

    async def _storage_files(self, package: Package) -> list[discord.File]:
        files: list[discord.File] = []
        for message in await self._storage_messages(package):
            for attachment in message.attachments:
                if attachment.filename.startswith("showcase_"):
                    continue
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
