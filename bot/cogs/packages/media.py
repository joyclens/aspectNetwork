from __future__ import annotations

import io
import re

import discord

from bot.cogs.packages.constants import IMAGE_TYPES, VIDEO_TYPES
from bot.cogs.packages.models import StoredFile

_SAFE_EXT = re.compile(r"[^a-zA-Z0-9]+")
_MAX_ATTACHMENTS = 10


def is_showcase_type(content_type: str | None, filename: str) -> bool:
    lowered = (content_type or "").lower()
    if lowered in IMAGE_TYPES or lowered in VIDEO_TYPES:
        return True
    name = filename.lower()
    return name.endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm")
    )


def safe_filename(index: int, filename: str, *, prefix: str) -> str:
    raw = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    _stem, dot, ext = raw.rpartition(".")
    cleaned = _SAFE_EXT.sub("", ext.lower())[:12] if dot else "bin"
    if not cleaned:
        cleaned = "bin"
    return f"{prefix}{index}.{cleaned}"


def discord_files_and_media(
    showcases: list[StoredFile],
    packages: list[StoredFile],
    *,
    limit: int = _MAX_ATTACHMENTS,
) -> tuple[list[discord.File], list[tuple[str, str | None]]]:
    """Build upload Files with stable ASCII names and matching attachment:// URIs."""
    files: list[discord.File] = []
    media: list[tuple[str, str | None]] = []
    for index, item in enumerate(showcases):
        if len(files) >= limit:
            break
        name = safe_filename(index, item.filename, prefix="showcase_")
        uploaded = discord.File(io.BytesIO(item.data), filename=name)
        files.append(uploaded)
        media.append((uploaded.uri, item.content_type))
    for index, item in enumerate(packages):
        if len(files) >= limit:
            break
        name = safe_filename(index, item.filename, prefix="package_")
        uploaded = discord.File(io.BytesIO(item.data), filename=name)
        files.append(uploaded)
        media.append((uploaded.uri, item.content_type))
    return files, media


def media_from_attachments(
    attachments: list[discord.Attachment] | tuple[discord.Attachment, ...],
) -> list[tuple[str, str | None]]:
    return [(item.url, item.content_type) for item in attachments]


def first_image_showcase(showcases: list[StoredFile]) -> StoredFile | None:
    for item in showcases:
        lowered = (item.content_type or "").lower()
        if lowered in IMAGE_TYPES or item.filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            return item
    return showcases[0] if showcases else None


def parse_storage_ids(content: str | None, fallback: int) -> list[int]:
    if not content:
        return [fallback]
    # package-storage:{user_id}:{id,id,id}
    parts = content.split(":")
    if len(parts) >= 3 and parts[0] == "package-storage":
        ids: list[int] = []
        for raw in parts[2].split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.append(int(raw))
        if ids:
            return ids
    return [fallback]
