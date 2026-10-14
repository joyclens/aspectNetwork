from __future__ import annotations

import io
import re
import time
from typing import Any

import discord
from discord import ui

from bot.cogs.packages.constants import (
    APPROVE_TEMPLATE,
    CONFIRM_TEMPLATE,
    DENY_TEMPLATE,
    PURCHASE_TEMPLATE,
    REPORT_TEMPLATE,
    RESEND_TEMPLATE,
    SELL_LABELS,
)
from bot.cogs.packages.layouts import draft_layout
from bot.cogs.packages.models import PackageDraft, draft_errors
from bot.core.bot import Aspect
from bot.shared.errors import report_interaction
from bot.shared.layout import container_view

Interaction = discord.Interaction[Any]

_MAX_DRAFT_ATTACHMENTS = 10


def _service(interaction: Interaction) -> Any:
    client = interaction.client
    if not isinstance(client, Aspect):
        return None
    cog = client.get_cog("Packages")
    return getattr(cog, "service", None) if cog is not None else None


def _unique_name(filename: str, used: set[str]) -> str:
    if filename not in used:
        used.add(filename)
        return filename
    stem, dot, suffix = filename.rpartition(".")
    base = stem if dot else filename
    ext = f".{suffix}" if dot else ""
    index = 2
    while True:
        candidate = f"{base}_{index}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def draft_attachment_bundle(
    draft: PackageDraft,
) -> tuple[list[discord.File], list[tuple[str, str | None]]]:
    files: list[discord.File] = []
    media: list[tuple[str, str | None]] = []
    used: set[str] = set()
    if draft.showcase is not None:
        name = _unique_name(draft.showcase.filename, used)
        files.append(discord.File(io.BytesIO(draft.showcase.data), filename=name))
        media.append((f"attachment://{name}", draft.showcase.content_type))
    for item in draft.files:
        if len(files) >= _MAX_DRAFT_ATTACHMENTS:
            break
        name = _unique_name(item.filename, used)
        files.append(discord.File(io.BytesIO(item.data), filename=name))
        media.append((f"attachment://{name}", item.content_type))
    return files, media


def build_draft_view(user_id: int, step: int, draft: PackageDraft) -> tuple[
    discord.ui.LayoutView,
    list[discord.File],
]:
    lines = format_draft_lines(draft, step)
    files, media = draft_attachment_bundle(draft) if step >= 3 else ([], [])
    view = draft_layout(
        user_id,
        step,
        lines,
        media=media or None,
        buttons=[DraftEdit(user_id, step), DraftContinue(user_id, step)],
    )
    return view, files


async def publish_draft(interaction: Interaction, user_id: int, step: int) -> None:
    service = _service(interaction)
    if service is None:
        return
    draft = service.draft_for(user_id)
    view, files = build_draft_view(user_id, step, draft)
    # Modal opened from a draft button → edit that ephemeral in place.
    # InteractionResponse.edit_message takes new Files via attachments=.
    if interaction.message is not None:
        await interaction.response.edit_message(
            view=view,
            attachments=files,
        )
        return
    await interaction.response.send_message(
        view=view,
        files=files or [],
        ephemeral=True,
    )


class DraftContinue(ui.Button[Any]):
    def __init__(self, user_id: int, step: int) -> None:
        super().__init__(label="Continue", style=discord.ButtonStyle.primary)
        self.user_id = user_id
        self.step = step

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This draft is not yours.")),
                ephemeral=True,
            )
            return
        service = _service(interaction)
        if service is None:
            return
        from bot.cogs.packages.modals import FilesModal, MetaModal

        draft = service.draft_for(self.user_id)
        errors = draft_errors(draft, step=self.step)
        if errors:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("\n".join(f"- {item}" for item in errors))),
                ephemeral=True,
            )
            return
        if self.step == 1:
            await interaction.response.send_modal(MetaModal(self.user_id))
        elif self.step == 2:
            await interaction.response.send_modal(FilesModal(self.user_id))
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                package = await service.submit_final(interaction, draft)
            except Exception as exc:
                await report_interaction(interaction, exc, where="Package submit")
                return
            done = container_view(
                ui.TextDisplay(
                    f"Submitted **{package.title}** for review (`{package.id}`)."
                )
            )
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=done, attachments=[])
                except discord.HTTPException:
                    pass
            await interaction.followup.send(view=done, ephemeral=True)


class DraftEdit(ui.Button[Any]):
    def __init__(self, user_id: int, step: int) -> None:
        super().__init__(label="Edit details", style=discord.ButtonStyle.secondary)
        self.user_id = user_id
        self.step = step

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This draft is not yours.")),
                ephemeral=True,
            )
            return
        from bot.cogs.packages.modals import DetailsModal, FilesModal, MetaModal

        if self.step == 1:
            await interaction.response.send_modal(DetailsModal(self.user_id))
        elif self.step == 2:
            await interaction.response.send_modal(MetaModal(self.user_id))
        else:
            await interaction.response.send_modal(FilesModal(self.user_id))


def draft_summary(user_id: int, step: int, lines: list[str]) -> discord.ui.LayoutView:
    return draft_layout(
        user_id,
        step,
        lines,
        buttons=[DraftEdit(user_id, step), DraftContinue(user_id, step)],
    )


class ApproveButton(ui.DynamicItem[ui.Button[Any]], template=APPROVE_TEMPLATE):
    def __init__(self, package_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Approve Package",
                style=discord.ButtonStyle.success,
                custom_id=f"package:approve:{package_id}",
            )
        )
        self.package_id = package_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ApproveButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            error = await service.approve(interaction, self.package_id)
        except Exception as exc:
            await report_interaction(interaction, exc, where="Package approve")
            return
        if error:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("Package approved.")),
            ephemeral=True,
        )


class DenyButton(ui.DynamicItem[ui.Button[Any]], template=DENY_TEMPLATE):
    def __init__(self, package_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Deny Package",
                style=discord.ButtonStyle.danger,
                custom_id=f"package:deny:{package_id}",
            )
        )
        self.package_id = package_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> DenyButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.packages.modals import DenyModal

        service = _service(interaction)
        if service is None:
            return
        if not isinstance(interaction.user, discord.Member) or not service.is_management(
            interaction.user
        ):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(DenyModal(self.package_id))


class PurchaseButton(ui.DynamicItem[ui.Button[Any]], template=PURCHASE_TEMPLATE):
    def __init__(self, package_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Purchase",
                style=discord.ButtonStyle.secondary,
                custom_id=f"package:purchase:{package_id}",
            )
        )
        self.package_id = package_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> PurchaseButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.packages.modals import PurchaseModal

        await interaction.response.send_modal(PurchaseModal(self.package_id))


class ReportButton(ui.DynamicItem[ui.Button[Any]], template=REPORT_TEMPLATE):
    def __init__(self, package_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Report Package",
                style=discord.ButtonStyle.danger,
                custom_id=f"package:report:{package_id}",
            )
        )
        self.package_id = package_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ReportButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        from bot.cogs.packages.modals import ReportModal

        await interaction.response.send_modal(ReportModal(self.package_id))


class ConfirmPurchaseButton(ui.DynamicItem[ui.Button[Any]], template=CONFIRM_TEMPLATE):
    def __init__(self, purchase_id: int) -> None:
        super().__init__(
            ui.Button(
                label="I've purchased",
                style=discord.ButtonStyle.primary,
                custom_id=f"package:confirm:{purchase_id}",
            )
        )
        self.purchase_id = purchase_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ConfirmPurchaseButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        if not service.confirm_ready(interaction.user.id, time.monotonic()):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Please wait a few seconds.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        from bot.shared.checks import database

        client = interaction.client
        if not isinstance(client, Aspect):
            return
        db = database(client)
        purchase = await db.purchase(self.purchase_id)
        if purchase is None or purchase.buyer_id != interaction.user.id:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Purchase not found.")),
                ephemeral=True,
            )
            return
        if purchase.status != "pending":
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("This purchase is no longer pending.")),
                ephemeral=True,
            )
            return
        package = await db.package(purchase.package_id)
        client_gp = service.gamepass()
        if package is None or package.gamepass_id is None or client_gp is None:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Ownership check is unavailable.")),
                ephemeral=True,
            )
            return
        try:
            owns = await client_gp.owns_pass(purchase.buyer_roblox_id, package.gamepass_id)
        except Exception as exc:
            await report_interaction(interaction, exc, where="Package confirm")
            return
        if not owns:
            await interaction.followup.send(
                view=container_view(
                    ui.TextDisplay("Purchase not detected yet. Buy the game pass, then try again.")
                ),
                ephemeral=True,
            )
            return
        await service.complete_purchase(purchase)
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("Payment detected. Delivering files.")),
            ephemeral=True,
        )


class ResendButton(ui.DynamicItem[ui.Button[Any]], template=RESEND_TEMPLATE):
    def __init__(self, purchase_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Resend files",
                style=discord.ButtonStyle.secondary,
                custom_id=f"package:resend:{purchase_id}",
            )
        )
        self.purchase_id = purchase_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> ResendButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        await interaction.response.defer(ephemeral=True)
        from bot.shared.checks import database

        client = interaction.client
        if not isinstance(client, Aspect):
            return
        db = database(client)
        purchase = await db.purchase(self.purchase_id)
        if purchase is None:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Purchase not found.")),
                ephemeral=True,
            )
            return
        allowed = {purchase.buyer_id}
        if purchase.recipient_id is not None:
            allowed.add(purchase.recipient_id)
        if interaction.user.id not in allowed:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("You cannot resend these files.")),
                ephemeral=True,
            )
            return
        package = await db.package(purchase.package_id)
        if package is None:
            return
        ok = await service.deliver_files(purchase, package)
        if ok:
            await db.mark_purchase_delivered(purchase.id)
        await interaction.followup.send(
            view=container_view(
                ui.TextDisplay("Files resent." if ok else "Could not deliver files.")
            ),
            ephemeral=True,
        )


class SettleConfirm(ui.View):
    def __init__(self, packager_id: int, actor_id: int) -> None:
        super().__init__(timeout=60)
        self.packager_id = packager_id
        self.actor_id = actor_id

    @ui.button(label="Confirm settle", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, _button: ui.Button[Any]) -> None:
        if interaction.user.id != self.actor_id:
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("This confirmation is not yours.")),
                ephemeral=True,
            )
            return
        service = _service(interaction)
        if service is None or not isinstance(interaction.user, discord.Member):
            return
        if not service.is_management(interaction.user):
            await interaction.response.send_message(
                view=container_view(ui.TextDisplay("Management only.")),
                ephemeral=True,
            )
            return
        from bot.shared.checks import database

        client = interaction.client
        if not isinstance(client, Aspect):
            return
        count = await database(client).settle_payouts(self.packager_id, interaction.user.id)
        await interaction.response.edit_message(
            view=container_view(
                ui.TextDisplay(f"Settled **{count}** payout(s) for <@{self.packager_id}>.")
            ),
        )


def purchase_pending_view(purchase_id: int, gamepass_id: int) -> discord.ui.LayoutView:
    return container_view(
        ui.TextDisplay(
            "## Complete Purchase\n"
            "Buy the game pass, then press **I've purchased**.\n"
            f"-# Purchase expires in 30 minutes. ID `{purchase_id}`."
        ),
        ui.ActionRow(
            ui.Button(
                label="Open Game Pass",
                style=discord.ButtonStyle.link,
                url=f"https://www.roblox.com/game-pass/{gamepass_id}",
            ),
            ConfirmPurchaseButton(purchase_id).item,
        ),
    )


def undelivered_view(purchase_id: int) -> discord.ui.LayoutView:
    return container_view(
        ui.TextDisplay("Payment recorded, but files could not be DMed."),
        ui.ActionRow(ResendButton(purchase_id).item),
    )


def format_draft_lines(draft: Any, step: int) -> list[str]:
    lines: list[str] = []
    if draft.package_type:
        lines.append(f"**Type:** `{draft.package_type}`")
    if draft.title:
        lines.append(f"**Title:** `{draft.title}`")
    if draft.price is not None:
        lines.append(f"**Price:** `{draft.price:,}`")
    if step >= 2:
        if draft.sell_type:
            lines.append(f"**Sell Type:** `{SELL_LABELS.get(draft.sell_type, draft.sell_type)}`")
        if draft.customizable is not None:
            lines.append(f"**Customizable:** `{draft.customizable}`")
        if draft.description:
            lines.append(f"**Description:**\n```\n{draft.description[:400]}\n```")
    if step >= 3 and draft.files:
        extra = len(draft.files) - max(0, _MAX_DRAFT_ATTACHMENTS - (1 if draft.showcase else 0))
        if extra > 0:
            lines.append(f"-# Showing first attachments · `{extra}` more on submit.")
    errors = draft_errors(draft, step=step)
    if errors:
        lines.append("")
        lines.extend(f"- {error}" for error in errors)
    return lines or ["Draft started."]
