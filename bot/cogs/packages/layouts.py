from __future__ import annotations

from typing import Any

import discord
from discord import ui

from bot.cogs.packages.constants import PACKAGE_BANNER_URL, SELL_LABELS, VIDEO_TYPES
from bot.core.database import Package
from bot.shared.layout import AspectLayout


def _showcase_item(
    filename: str,
    *,
    content_type: str | None = None,
    url: str | None = None,
) -> ui.Item[Any]:
    media = url or f"attachment://{filename}"
    if content_type and content_type.lower() in VIDEO_TYPES:
        return ui.File(media)
    return ui.MediaGallery(discord.MediaGalleryItem(media))


def _banner() -> ui.MediaGallery[Any]:
    return ui.MediaGallery(discord.MediaGalleryItem(PACKAGE_BANNER_URL))


def submission_layout(
    package: Package,
    *,
    showcase_filename: str,
    showcase_content_type: str | None = None,
    status_line: str | None = None,
    buttons: list[ui.Item[Any]] | None = None,
) -> AspectLayout:
    sell = SELL_LABELS.get(package.sell_type, package.sell_type)
    description = package.description.replace("```", "'''")
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(
            "## Package Submission\n"
            f"<@{package.packager_id}> has requested for their **{package.package_type}** "
            "to be submitted.\n"
            "-# Use the buttons below to make the decision."
        ),
        ui.Separator(),
        ui.TextDisplay(
            f"**Package Type:** `{package.package_type}`\n"
            f"**Package Title:** `{package.title}`\n"
            f"**Package Price:** `{package.price:,}`\n"
            f"**Sell Type:** `{sell}`\n"
            f"**Customizable:** `{package.customizable}`\n\n"
            f"```\n{description}\n```"
        ),
        ui.Separator(),
        _showcase_item(showcase_filename, content_type=showcase_content_type),
        ui.Separator(),
    ]
    if buttons:
        items.append(ui.ActionRow(*buttons))
    if status_line:
        items.append(ui.TextDisplay(status_line))
    items.append(_banner())
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view


def forum_layout(
    package: Package,
    *,
    showcase_filename: str,
    showcase_content_type: str | None = None,
    status_line: str | None = None,
    buttons: list[ui.Item[Any]] | None = None,
) -> AspectLayout:
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(
            f"## {package.title}\n"
            f"{package.description}\n\n"
            f"-# This package was uploaded by <@{package.packager_id}> "
            "on behalf of **Aspect Network**."
        ),
        ui.Separator(),
        ui.TextDisplay(
            f"**Price:** `{package.price:,}`\n"
            f"**Customizable:** `{package.customizable}`"
        ),
        ui.Separator(),
        _showcase_item(showcase_filename, content_type=showcase_content_type),
        ui.Separator(),
    ]
    if buttons:
        items.append(ui.ActionRow(*buttons))
    if status_line:
        items.append(ui.TextDisplay(status_line))
    items.append(_banner())
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view


def report_layout(package: Package, reporter_id: int, issue: str, jump_url: str) -> AspectLayout:
    from bot.cogs.packages.models import neutralise_fences

    safe = neutralise_fences(issue)
    view = AspectLayout()
    view.add_item(
        ui.Container(
            ui.TextDisplay(
                "## Package Report\n"
                f"**Package:** `{package.title}` (`{package.id}`)\n"
                f"**Forum:** {jump_url}\n"
                f"**Reporter:** <@{reporter_id}>\n\n"
                f"```\n{safe}\n```"
            ),
            _banner(),
        )
    )
    return view
