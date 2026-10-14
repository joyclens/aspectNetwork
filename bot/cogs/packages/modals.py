from __future__ import annotations

from typing import Any

import discord
from discord import ui

from bot.cogs.packages.constants import PACKAGE_TYPES, SHOWCASE_TYPES
from bot.cogs.packages.models import (
    StoredFile,
    neutralise_fences,
    parse_price,
    validate_bool_select,
    validate_sell_type,
    validate_type,
)
from bot.cogs.packages.views import (
    _service,
    draft_summary,
    format_draft_lines,
    purchase_pending_view,
)
from bot.core.bot import Aspect
from bot.shared.checks import database
from bot.shared.errors import report_interaction
from bot.shared.layout import container_view

Interaction = discord.Interaction[Any]


class DetailsModal(ui.Modal, title="Package Details"):
    def __init__(self, user_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.package_type: ui.Label[Any] = ui.Label(
            text="Package Type",
            component=ui.Select(
                options=[
                    discord.SelectOption(label=name, value=name) for name in PACKAGE_TYPES
                ],
                min_values=1,
                max_values=1,
                required=True,
            ),
        )
        self.package_title: ui.Label[Any] = ui.Label(
            text="Package Title",
            component=ui.TextInput(max_length=50, required=True),
        )
        self.package_price: ui.Label[Any] = ui.Label(
            text="Package Price",
            component=ui.TextInput(
                placeholder="Robux integer",
                max_length=10,
                required=True,
            ),
        )
        self.add_item(self.package_type)
        self.add_item(self.package_title)
        self.add_item(self.package_price)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None or interaction.user.id != self.user_id:
            return
        draft = service.draft_for(self.user_id)
        type_select = self.package_type.component
        title_input = self.package_title.component
        price_input = self.package_price.component
        assert isinstance(type_select, ui.Select)
        assert isinstance(title_input, ui.TextInput)
        assert isinstance(price_input, ui.TextInput)
        package_type = validate_type(type_select.values[0] if type_select.values else "")
        price = parse_price(str(price_input.value))
        draft.package_type = package_type
        draft.title = str(title_input.value).strip()
        draft.price = price
        draft.touch()
        await interaction.response.send_message(
            view=draft_summary(self.user_id, 1, format_draft_lines(draft, 1)),
            ephemeral=True,
        )


class MetaModal(ui.Modal, title="Package Meta"):
    def __init__(self, user_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.description: ui.Label[Any] = ui.Label(
            text="Package Description",
            component=ui.TextInput(
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True,
            ),
        )
        self.sell_type: ui.Label[Any] = ui.Label(
            text="Sell Type",
            component=ui.Select(
                options=[
                    discord.SelectOption(label="One-time", value="One-time"),
                    discord.SelectOption(label="Multiple", value="Multiple"),
                ],
                min_values=1,
                max_values=1,
                required=True,
            ),
        )
        self.customizable: ui.Label[Any] = ui.Label(
            text="Customizable",
            component=ui.Select(
                options=[
                    discord.SelectOption(label="True", value="True"),
                    discord.SelectOption(label="False", value="False"),
                ],
                min_values=1,
                max_values=1,
                required=True,
            ),
        )
        self.add_item(self.description)
        self.add_item(self.sell_type)
        self.add_item(self.customizable)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None or interaction.user.id != self.user_id:
            return
        draft = service.draft_for(self.user_id)
        description = self.description.component
        sell = self.sell_type.component
        custom = self.customizable.component
        assert isinstance(description, ui.TextInput)
        assert isinstance(sell, ui.Select)
        assert isinstance(custom, ui.Select)
        draft.description = neutralise_fences(str(description.value).strip())
        draft.sell_type = validate_sell_type(sell.values[0] if sell.values else "")
        draft.customizable = validate_bool_select(custom.values[0] if custom.values else "")
        draft.touch()
        await interaction.response.send_message(
            view=draft_summary(self.user_id, 2, format_draft_lines(draft, 2)),
            ephemeral=True,
        )


class FilesModal(ui.Modal, title="Package Files"):
    def __init__(self, user_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.showcase: ui.Label[Any] = ui.Label(
            text="Package Showcase",
            component=ui.FileUpload(min_values=1, max_values=1, required=True),
        )
        self.files: ui.Label[Any] = ui.Label(
            text="Package Files",
            component=ui.FileUpload(min_values=1, max_values=10, required=True),
        )
        self.add_item(self.showcase)
        self.add_item(self.files)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None or interaction.user.id != self.user_id:
            return
        draft = service.draft_for(self.user_id)
        showcase_upload = self.showcase.component
        files_upload = self.files.component
        assert isinstance(showcase_upload, ui.FileUpload)
        assert isinstance(files_upload, ui.FileUpload)
        showcases = list(showcase_upload.values)
        packages = list(files_upload.values)
        errors: list[str] = []
        if len(showcases) != 1:
            errors.append("Showcase must be exactly one file.")
        else:
            attachment = showcases[0]
            content = (attachment.content_type or "").lower()
            if content not in SHOWCASE_TYPES:
                errors.append("Showcase must be an image or video.")
            else:
                data = await attachment.read()
                draft.showcase = StoredFile(attachment.filename, content, data)
        if not (1 <= len(packages) <= 10):
            errors.append("Provide between 1 and 10 package files.")
        else:
            stored: list[StoredFile] = []
            for attachment in packages:
                data = await attachment.read()
                stored.append(
                    StoredFile(
                        attachment.filename,
                        (attachment.content_type or "application/octet-stream").lower(),
                        data,
                    )
                )
            draft.files = stored
        draft.touch()
        lines = format_draft_lines(draft, 3)
        if errors:
            lines.extend(f"- {error}" for error in errors)
        await interaction.response.send_message(
            view=draft_summary(self.user_id, 3, lines),
            ephemeral=True,
        )


class DenyModal(ui.Modal, title="Deny Package"):
    def __init__(self, package_id: int) -> None:
        super().__init__()
        self.package_id = package_id
        self.reason: ui.Label[Any] = ui.Label(
            text="Reason",
            component=ui.TextInput(
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True,
            ),
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        reason_input = self.reason.component
        assert isinstance(reason_input, ui.TextInput)
        await interaction.response.defer(ephemeral=True)
        error = await service.deny(interaction, self.package_id, str(reason_input.value).strip())
        if error:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("Package denied.")),
            ephemeral=True,
        )


class PurchaseModal(ui.Modal, title="Purchase Package"):
    def __init__(self, package_id: int) -> None:
        super().__init__()
        self.package_id = package_id
        self.purchase_type: ui.Label[Any] = ui.Label(
            text="Purchase Type",
            component=ui.Select(
                options=[
                    discord.SelectOption(label="Personal", value="Personal"),
                    discord.SelectOption(label="Gift", value="Gift"),
                ],
                min_values=1,
                max_values=1,
                required=True,
            ),
        )
        self.recipient: ui.Label[Any] = ui.Label(
            text="Gift Recipient",
            component=ui.UserSelect(min_values=0, max_values=1, required=False),
        )
        self.add_item(self.purchase_type)
        self.add_item(self.recipient)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        type_select = self.purchase_type.component
        user_select = self.recipient.component
        assert isinstance(type_select, ui.Select)
        assert isinstance(user_select, ui.UserSelect)
        kind = type_select.values[0] if type_select.values else ""
        users = list(user_select.values)
        recipient = users[0] if users else None
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            purchase, error = await service.start_purchase(
                interaction,
                self.package_id,
                kind,
                recipient,
            )
        except Exception as exc:
            await report_interaction(interaction, exc, where="Package purchase")
            return
        if error or purchase is None:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay(error or "Purchase failed.")),
                ephemeral=True,
            )
            return
        client = interaction.client
        if not isinstance(client, Aspect):
            return
        package = await database(client).package(self.package_id)
        if package is None or package.gamepass_id is None:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay("Game pass is missing.")),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=purchase_pending_view(purchase.id, package.gamepass_id),
            ephemeral=True,
        )


class ReportModal(ui.Modal, title="Report Package"):
    def __init__(self, package_id: int) -> None:
        super().__init__()
        self.package_id = package_id
        self.issue: ui.Label[Any] = ui.Label(
            text="What is wrong?",
            component=ui.TextInput(
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True,
            ),
        )
        self.add_item(self.issue)

    async def on_submit(self, interaction: Interaction) -> None:
        service = _service(interaction)
        if service is None:
            return
        issue_input = self.issue.component
        assert isinstance(issue_input, ui.TextInput)
        await interaction.response.defer(ephemeral=True)
        error = await service.report(
            interaction,
            self.package_id,
            str(issue_input.value).strip(),
        )
        if error:
            await interaction.followup.send(
                view=container_view(ui.TextDisplay(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(ui.TextDisplay("Report submitted.")),
            ephemeral=True,
        )
