from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Any, Final

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from bot.core.bot import Aspect
from bot.core.ids import Roles
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

BASE_PATH: Final[Path] = Path(__file__).resolve().parents[1] / "assets" / "clothing" / "base.png"

MAPPING: Final[dict[str, list[dict[str, int]]]] = {
    "shirt": [
        {"x": 151, "y": 355, "width": 64, "height": 128, "drawX": 26, "drawY": 26},
        {"x": 217, "y": 355, "width": 64, "height": 128, "drawX": 105, "drawY": 26},
        {"x": 231, "y": 74, "width": 128, "height": 128, "drawX": 169, "drawY": 26},
        {"x": 308, "y": 355, "width": 64, "height": 128, "drawX": 297, "drawY": 26},
        {"x": 440, "y": 355, "width": 64, "height": 128, "drawX": 390, "drawY": 26},
        {"x": 427, "y": 74, "width": 128, "height": 128, "drawX": 454, "drawY": 26},
        {"x": 85, "y": 355, "width": 64, "height": 128, "drawX": 582, "drawY": 26},
        {"x": 374, "y": 355, "width": 64, "height": 128, "drawX": 661, "drawY": 26},
    ],
    "pants": [
        {"x": 231, "y": 74, "width": 128, "height": 128, "drawX": 169, "drawY": 26},
        {"x": 427, "y": 74, "width": 128, "height": 128, "drawX": 454, "drawY": 26},
        {"x": 151, "y": 355, "width": 64, "height": 128, "drawX": 26, "drawY": 154},
        {"x": 217, "y": 355, "width": 64, "height": 128, "drawX": 169, "drawY": 154},
        {"x": 308, "y": 355, "width": 64, "height": 128, "drawX": 233, "drawY": 154},
        {"x": 440, "y": 355, "width": 64, "height": 128, "drawX": 454, "drawY": 154},
        {"x": 85, "y": 355, "width": 64, "height": 128, "drawX": 518, "drawY": 154},
        {"x": 374, "y": 355, "width": 64, "height": 128, "drawX": 661, "drawY": 154},
    ],
}


def generate_preview(shirt_data: bytes, pants_data: bytes, base_path: Path) -> bytes:
    base = Image.open(base_path).convert("RGBA")
    shirt = Image.open(io.BytesIO(shirt_data)).convert("RGBA")
    pants = Image.open(io.BytesIO(pants_data)).convert("RGBA")
    for clothing_type, img in (("pants", pants), ("shirt", shirt)):
        for region in MAPPING[clothing_type]:
            box = (
                region["x"],
                region["y"],
                region["x"] + region["width"],
                region["y"] + region["height"],
            )
            crop = img.crop(box)
            base.paste(crop, (region["drawX"], region["drawY"]), crop)
    output = io.BytesIO()
    base.save(output, format="PNG")
    return output.getvalue()


def _is_image(attachment: discord.Attachment) -> bool:
    name = attachment.filename.lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return True
    content = (attachment.content_type or "").lower()
    return content.startswith("image/")


def _can_showcase(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return (
        member.get_role(Roles.packager) is not None or member.get_role(Roles.management) is not None
    )


class Showcase(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @app_commands.command(
        name="showcase",
        description="Preview Roblox shirt and pants templates on the clothing base.",
    )
    @app_commands.describe(
        shirt="Roblox shirt template image",
        pants="Roblox pants template image",
    )
    @app_commands.guild_only()
    async def showcase(
        self,
        interaction: discord.Interaction[Any],
        shirt: discord.Attachment,
        pants: discord.Attachment,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_showcase(interaction.user):
            await interaction.response.send_message(
                view=container_view(
                    discord.ui.TextDisplay("Packager or Management role required.")
                ),
                ephemeral=True,
            )
            return
        if not BASE_PATH.is_file():
            await interaction.response.send_message(
                view=container_view(
                    discord.ui.TextDisplay("Clothing base image is not configured.")
                ),
                ephemeral=True,
            )
            return
        if not _is_image(shirt) or not _is_image(pants):
            await interaction.response.send_message(
                view=container_view(
                    discord.ui.TextDisplay("Both attachments must be image files.")
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            shirt_data, pants_data = await asyncio.gather(shirt.read(), pants.read())
            preview = await asyncio.to_thread(
                generate_preview,
                shirt_data,
                pants_data,
                BASE_PATH,
            )
        except Exception:
            logger.exception("Showcase preview failed")
            await interaction.followup.send(
                view=container_view(
                    discord.ui.TextDisplay("Could not build that clothing preview.")
                ),
                ephemeral=True,
            )
            return
        uploaded = discord.File(io.BytesIO(preview), filename="showcase.png")
        await interaction.followup.send(
            view=container_view(
                discord.ui.MediaGallery(discord.MediaGalleryItem(uploaded.uri)),
            ),
            files=[uploaded],
        )


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Showcase(bot))
