from __future__ import annotations

from typing import Any

import discord
from discord import ui

from bot.cogs.packages.constants import IMAGE_TYPES, PACKAGE_BANNER_URL, SELL_LABELS
from bot.core.database import Package
from bot.shared.layout import AspectLayout


def _is_image(content_type: str | None, filename: str) -> bool:
    lowered = (content_type or "").lower()
    if lowered in IMAGE_TYPES:
        return True
    if lowered:
        return False
    return filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def media_components(
    entries: list[tuple[str, str | None]],
) -> list[ui.Item[Any]]:
    """Build MediaGallery (images) + File (video/other) from media URL/attachment refs."""
    gallery: list[discord.MediaGalleryItem] = []
    files: list[ui.File[Any]] = []
    for media, content_type in entries:
        name = media.rsplit("/", 1)[-1].split("?", 1)[0]
        if _is_image(content_type, name):
            gallery.append(discord.MediaGalleryItem(media))
        else:
            files.append(ui.File(media))
    items: list[ui.Item[Any]] = []
    if gallery:
        items.append(ui.MediaGallery(*gallery[:10]))
    items.extend(files[:10])
    return items


def _banner() -> ui.MediaGallery[Any]:
    return ui.MediaGallery(discord.MediaGalleryItem(PACKAGE_BANNER_URL))


def submission_layout(
    package: Package,
    *,
    media: list[tuple[str, str | None]] | None = None,
    showcase_filename: str | None = None,
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
    ]
    resolved = media
    if resolved is None and showcase_filename:
        resolved = [(f"attachment://{showcase_filename}", showcase_content_type)]
    if resolved:
        items.extend(media_components(resolved))
        items.append(ui.Separator())
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
    media: list[tuple[str, str | None]] | None = None,
    showcase_filename: str | None = None,
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
    ]
    resolved = media
    if resolved is None and showcase_filename:
        resolved = [(f"attachment://{showcase_filename}", showcase_content_type)]
    if resolved:
        items.extend(media_components(resolved))
        items.append(ui.Separator())
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


def draft_layout(
    user_id: int,
    step: int,
    lines: list[str],
    *,
    media: list[tuple[str, str | None]] | None = None,
    buttons: list[ui.Item[Any]] | None = None,
) -> AspectLayout:
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(f"## Package Draft · Step {step}/3\n" + "\n".join(lines)),
    ]
    if media:
        items.append(ui.Separator())
        items.extend(media_components(media))
    if buttons:
        items.append(ui.Separator())
        items.append(ui.ActionRow(*buttons))
    view = AspectLayout(timeout=900)
    view.add_item(ui.Container(*items))
    return view
