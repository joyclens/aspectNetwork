from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import discord

from bot.cogs.packages.constants import (
    FORUM_CHANNELS,
    KIND_GIFT,
    PACKAGER_SHARE_PERCENT,
    PURCHASE_TTL_SECONDS,
    REPORT_COOLDOWN_SECONDS,
    SELL_ONE_TIME,
    STATUS_ACCEPTED,
    STATUS_SOLD,
)
from bot.cogs.packages.layouts import (
    delivery_layout,
    forum_layout,
    report_layout,
    submission_layout,
)
from bot.cogs.packages.media import (
    discord_files_and_media,
    files_and_media_from_attachments,
    first_image_showcase,
    is_image,
    media_from_attachments,
    parse_storage_ids,
    safe_filename,
)
from bot.cogs.packages.models import PackageDraft, StoredFile, packager_share, resolve_purchase_kind
from bot.cogs.packages.roblox import GamePassClient, GamePassError, reviewer_message
from bot.core.bot import Aspect
from bot.core.database import Package, PackagePurchase
from bot.core.ids import App, Channels, Guild, Roles
from bot.services.dock import DockError
from bot.shared.checks import database
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

Interaction = discord.Interaction[Any]
DM_BATCH_BYTES = 7_500_000


class PackageService:
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot
        self.drafts: dict[int, PackageDraft] = {}
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
        return GamePassClient(raw, self.bot.settings.roblox_universe_id, self.bot.session)

    def draft_for(self, user_id: int) -> PackageDraft:
        draft = self.drafts.get(user_id)
        if draft is None or draft.expired():
            draft = PackageDraft(user_id=user_id)
            self.drafts[user_id] = draft
        return draft

    def clear_draft(self, user_id: int) -> None:
        self.drafts.pop(user_id, None)

    def has_role(self, member: discord.Member, role_id: int) -> bool:
        return has_role(member, role_id)

    def is_packager(self, member: discord.Member) -> bool:
        return has_role(member, Roles.packager)

    def is_management(self, member: discord.Member) -> bool:
        return is_management(member)

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
        dock = self.bot.dock
        if dock is None:
            return None
        try:
            linked = await dock.linked_roblox(user_id, Guild.id)
        except DockError:
            return None
        return int(linked) if linked is not None else None

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

    def _storage_attachments(self, messages: list[discord.Message]) -> list[discord.Attachment]:
        return [item for message in messages for item in message.attachments]

    async def _storage_files_and_media(
        self,
        messages: list[discord.Message],
        *,
        showcase_only: bool = False,
    ) -> tuple[list[discord.File], list[tuple[str, str | None]]]:
        attachments = self._storage_attachments(messages)
        if showcase_only:
            preferred = [
                item
                for item in attachments
                if item.filename.startswith("showcase_")
                or is_image(item.content_type, item.filename)
            ]
            attachments = preferred[:1] or attachments[:1]
        return await files_and_media_from_attachments(attachments)

    async def submit_final(self, interaction: Interaction, draft: PackageDraft) -> Package:
        from bot.cogs.packages.views import ApproveButton, DenyButton

        channel_id, message_id, showcase_name, _storage_messages = await self.store_files(draft)
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
        files, media = discord_files_and_media(draft.showcases, draft.files)
        posted = await submissions.send(
            view=submission_layout(
                package,
                media=media or None,
                buttons=[ApproveButton(package.id).item, DenyButton(package.id).item],
            ),
            files=files,
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
            storage_messages = await self._storage_messages(claimed)
            storage_files, storage_media = await self._storage_files_and_media(storage_messages)
            icon_note = await self._upload_showcase_icon(
                client,
                claimed,
                gamepass_id,
                storage_messages,
            )
            forum_files, forum_media = await self._storage_files_and_media(
                storage_messages,
                showcase_only=True,
            )
            forum_id = FORUM_CHANNELS.get(claimed.package_type, 0)
            forum = await self.channel(forum_id)
            if not isinstance(forum, discord.ForumChannel):
                raise RuntimeError("Forum channel is unavailable for this package type.")
            thread_with = await forum.create_thread(
                name=claimed.title[:100],
                view=forum_layout(
                    claimed,
                    media=forum_media or None,
                    buttons=[
                        PurchaseButton(claimed.id).item,
                        ReportButton(claimed.id).item,
                    ],
                ),
                files=forum_files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            accepted = await db.accept_package(
                claimed.id,
                gamepass_id=gamepass_id,
                forum_channel_id=forum.id,
                forum_thread_id=thread_with.thread.id,
                forum_message_id=thread_with.message.id,
            )
            if accepted is None:
                raise RuntimeError("Failed to mark package accepted.")
            await self._edit_submission(
                interaction.message,
                submission_layout(
                    accepted,
                    media=storage_media or None,
                    status_line=f"-# Approved by <@{interaction.user.id}>{icon_note}",
                    buttons=None,
                ),
                files=storage_files,
            )
            await self._dm(
                accepted.packager_id,
                f"Your package **{accepted.title}** was approved.",
            )
            return None
        except GamePassError as exc:
            await db.revert_package_pending(package_id)
            return reviewer_message(exc)
        except Exception:
            await db.revert_package_pending(package_id)
            logger.exception("Package approve failed")
            return "Approval failed."

    async def _upload_showcase_icon(
        self,
        client: GamePassClient,
        package: Package,
        gamepass_id: int,
        storage_messages: list[discord.Message],
    ) -> str:
        showcase = self._pick_showcase_attachment(package, storage_messages)
        if showcase is None:
            return ""
        if not is_image(showcase.content_type, showcase.filename):
            return " Showcase is a video; icon upload was skipped."
        try:
            await client.upload_icon(gamepass_id, await showcase.read())
        except GamePassError as exc:
            return f" Icon upload failed: {reviewer_message(exc)}"
        return ""

    async def _edit_submission(
        self,
        message: discord.Message | None,
        view: discord.ui.LayoutView,
        *,
        files: list[discord.File] | None = None,
    ) -> None:
        if message is None:
            return
        try:
            await message.edit(
                view=view,
                attachments=files if files is not None else list(message.attachments),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("Could not update package submission message")

    async def deny(self, interaction: Interaction, package_id: int, reason: str) -> str | None:
        if not isinstance(interaction.user, discord.Member) or not self.is_management(
            interaction.user
        ):
            return "Management only."
        db = database(self.bot)
        denied = await db.deny_package(package_id, interaction.user.id)
        if denied is None:
            return "This package cannot be denied."
        files, media = await self._storage_files_and_media(await self._storage_messages(denied))
        await self._edit_submission(
            interaction.message,
            submission_layout(
                denied,
                media=media or None,
                status_line=f"-# Denied by <@{interaction.user.id}>: {reason}",
                buttons=None,
            ),
            files=files,
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
        if package.gamepass_id is not None and await self.buyer_paid(
            roblox_id,
            package.gamepass_id,
        ):
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

    async def sync_recent_sales(self) -> None:
        cog = self.bot.get_cog("Purchases")
        ingest = getattr(cog, "ingest_new_sales", None)
        if ingest is None:
            return
        try:
            await ingest()
        except Exception:
            logger.exception("Could not refresh group sales for package payment check")

    async def buyer_paid(
        self,
        buyer_roblox_id: int,
        gamepass_id: int,
        *,
        since: datetime | None = None,
        refresh: bool = False,
    ) -> bool:
        if buyer_roblox_id < 1 or gamepass_id < 1:
            return False
        if refresh:
            await self.sync_recent_sales()
        return await database(self.bot).agent_bought_gamepass(
            App.roblox_group_id,
            buyer_roblox_id,
            gamepass_id,
            since=since,
        )

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
        ok = await self._dm_files(target_id, files)
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
            if not isinstance(thread, discord.Thread):
                return
            if sold.forum_message_id is not None:
                message = await thread.fetch_message(sold.forum_message_id)
                await message.edit(
                    view=forum_layout(
                        sold,
                        media=media_from_attachments(message.attachments) or None,
                        status_line="-# Sold",
                        buttons=None,
                    ),
                    attachments=list(message.attachments),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            await thread.edit(archived=True, locked=True)
        except discord.HTTPException:
            logger.warning("Could not update sold forum post for package %s", package.id)

    async def _notify_packager_sale(self, package: Package, purchase: PackagePurchase) -> None:
        text = (
            f"Your package **{package.title}** sold "
            f"(`{package.price:,}` R$), purchase `{purchase.id}`."
        )
        if await self._dm(package.packager_id, text):
            return
        channel = await self.channel(Channels.package_submissions)
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                view=container_view(discord.ui.TextDisplay(f"<@{package.packager_id}> {text}")),
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
        files: list[discord.File],
    ) -> bool:
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            batches: list[list[discord.File]] = []
            batch: list[discord.File] = []
            size = 0
            for item in files:
                raw = item.fp.read()
                item.fp.seek(0)
                if batch and (len(batch) >= 10 or size + len(raw) > DM_BATCH_BYTES):
                    batches.append(batch)
                    batch = []
                    size = 0
                batch.append(discord.File(io.BytesIO(raw), filename=item.filename))
                size += len(raw)
            if batch:
                batches.append(batch)
            if not batches:
                return False
            first, *rest = batches
            await user.send(view=delivery_layout(first), files=first)
            for extra in rest:
                await user.send(
                    view=delivery_layout(extra),
                    files=extra,
                )
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
        messages: list[discord.Message] = []
        for message_id in parse_storage_ids(first.content, first.id):
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
            if not (
                name.startswith("showcase_") or attachment.filename == package.showcase_filename
            ):
                continue
            if is_image(attachment.content_type, attachment.filename):
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
