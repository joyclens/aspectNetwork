from __future__ import annotations

from typing import Any

import discord
from discord import ui

from bot.cogs.packages.constants import PACKAGE_BANNER_URL, SELL_LABELS
from bot.cogs.packages.media import is_image
from bot.cogs.packages.models import neutralise_fences
from bot.core.database import Package, PackagerPackageEarnings
from bot.core.ids import Guild
from bot.shared.layout import AspectLayout

MediaRef = tuple[str, str | None]


def media_components(entries: list[MediaRef]) -> list[ui.Item[Any]]:
    gallery: list[discord.MediaGalleryItem] = []
    files: list[ui.File[Any]] = []
    for media, content_type in entries:
        name = media.rsplit("/", 1)[-1].split("?", 1)[0]
        if is_image(content_type, name):
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


def _with_media(
    items: list[ui.Item[Any]],
    media: list[MediaRef] | None,
    buttons: list[ui.Item[Any]] | None,
    status_line: str | None,
) -> AspectLayout:
    if media:
        items.extend(media_components(media))
        items.append(ui.Separator())
    if buttons:
        items.append(ui.ActionRow(*buttons))
    if status_line:
        items.append(ui.TextDisplay(status_line))
    items.append(_banner())
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view


def submission_layout(
    package: Package,
    *,
    media: list[MediaRef] | None = None,
    status_line: str | None = None,
    buttons: list[ui.Item[Any]] | None = None,
) -> AspectLayout:
    sell = SELL_LABELS.get(package.sell_type, package.sell_type)
    description = package.description.replace("```", "'''")
    return _with_media(
        [
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
        ],
        media,
        buttons,
        status_line,
    )


def forum_layout(
    package: Package,
    *,
    media: list[MediaRef] | None = None,
    status_line: str | None = None,
    buttons: list[ui.Item[Any]] | None = None,
) -> AspectLayout:
    return _with_media(
        [
            ui.TextDisplay(
                f"## {package.title}\n"
                f"{package.description}\n\n"
                f"-# This package was uploaded by <@{package.packager_id}> "
                "on behalf of **Aspect Network**."
            ),
            ui.Separator(),
            ui.TextDisplay(
                f"**Price:** `{package.price:,}`\n**Customizable:** `{package.customizable}`"
            ),
            ui.Separator(),
        ],
        media,
        buttons,
        status_line,
    )


def report_layout(package: Package, reporter_id: int, issue: str, jump_url: str) -> AspectLayout:
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
    media: list[MediaRef] | None = None,
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


def delivery_layout(files: list[discord.File]) -> AspectLayout:
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(
            "## Thanks for purchasing!\n"
            "On behalf of **Aspect Network**, we appreciate your custom. "
            "The packager has been notified of your purchase, your files are attached below."
        ),
        ui.Separator(visible=False),
    ]
    for uploaded in files[:10]:
        items.append(ui.File(uploaded.uri))
    items.append(_banner())
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view


def _package_jump(row: PackagerPackageEarnings) -> str:
    title = row.title.replace("`", "'")
    if row.forum_thread_id is None:
        return f"**{title}**"
    if row.forum_message_id is not None:
        url = (
            f"https://discord.com/channels/{Guild.id}/"
            f"{row.forum_thread_id}/{row.forum_message_id}"
        )
    else:
        url = f"https://discord.com/channels/{Guild.id}/{row.forum_thread_id}"
    return f"[**{title}**]({url})"


def payouts_layout(
    packager_id: int,
    rows: list[PackagerPackageEarnings],
    *,
    pending_only: bool = False,
) -> AspectLayout:
    pending_total = sum(row.pending_total for row in rows)
    header = (
        "## Pending Payouts\n"
        f"<@{packager_id}> has a total of **{pending_total:,}** R$ pending."
        if pending_only
        else (
            "## Package Earnings\n"
            f"<@{packager_id}> — pending **{pending_total:,}** R$ · "
            f"paid **{sum(row.paid_total for row in rows):,}** R$ · "
            f"**{sum(row.sales for row in rows)}** sale(s)."
        )
    )
    items: list[ui.Item[Any]] = [
        ui.TextDisplay(header),
        ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
    ]
    lines: list[str] = []
    visible = [row for row in rows if not pending_only or row.pending_total > 0]
    if not visible:
        lines.append("-# No packages to show.")
    else:
        for index, row in enumerate(visible[:25], start=1):
            if pending_only:
                lines.append(
                    f"`{index}.` {_package_jump(row)} — "
                    f"**{row.pending_total:,}** R$ pending "
                    f"(`{row.pending_sales}` sale(s))."
                )
            else:
                lines.append(
                    f"`{index}.` {_package_jump(row)} — "
                    f"**{row.earned:,}** R$ earned · `{row.sales}` sale(s) · "
                    f"**{row.pending_total:,}** pending."
                )
    items.append(ui.TextDisplay("\n".join(lines)))
    items.append(ui.Separator(visible=False))
    items.append(_banner())
    view = AspectLayout(timeout=None)
    view.add_item(ui.Container(*items))
    return view
