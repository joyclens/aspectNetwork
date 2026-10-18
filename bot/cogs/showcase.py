from __future__ import annotations

import asyncio
import io
import logging
import re
from pathlib import Path
from typing import Any, Final

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from bot.core.bot import Aspect
from bot.core.ids import Roles
from bot.shared.layout import container_view

logger = logging.getLogger("aspect")

BASE_PATH: Final[Path] = Path(__file__).resolve().parents[1] / "assets" / "clothing" / "base.png"
_ASSET: Final[str] = "https://assetdelivery.roproxy.com/v1/asset/?id="
_ASSET_ID: Final[re.Pattern[str]] = re.compile(r"<url>.*\?id=(\d+)</url>")
_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

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


class TemplateError(Exception):
    def __init__(self, clothing_id: int, detail: str) -> None:
        self.clothing_id = clothing_id
        self.detail = detail
        super().__init__(f"{clothing_id}: {detail}")


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


async def download_template(
    session: aiohttp.ClientSession,
    clothing_id: int,
    cookie: str,
) -> bytes:
    headers = {
        "User-Agent": _USER_AGENT,
        "Cookie": cookie,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with session.get(
            f"{_ASSET}{clothing_id}",
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status >= 300:
                raise TemplateError(clothing_id, f"asset lookup failed ({response.status})")
            xml = await response.text()
    except (aiohttp.ClientError, TimeoutError, UnicodeError) as exc:
        raise TemplateError(clothing_id, "asset lookup failed") from exc

    match = _ASSET_ID.search(xml)
    if match is None:
        raise TemplateError(clothing_id, "could not resolve template asset")
    image_id = match.group(1)

    try:
        async with session.get(
            f"{_ASSET}{image_id}",
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status >= 300:
                raise TemplateError(clothing_id, f"template download failed ({response.status})")
            data = await response.read()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise TemplateError(clothing_id, "template download failed") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise TemplateError(clothing_id, "downloaded file is not a valid image") from exc
    return data


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
        shirt="Roblox shirt clothing ID",
        pants="Roblox pants clothing ID",
    )
    @app_commands.guild_only()
    async def showcase(
        self,
        interaction: discord.Interaction[Any],
        shirt: app_commands.Range[int, 1, None],
        pants: app_commands.Range[int, 1, None],
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
        session = self.bot.session
        if session is None or session.closed:
            await interaction.response.send_message(
                view=container_view(discord.ui.TextDisplay("Roblox downloads are unavailable.")),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        cookie = self.bot.settings.roblox_cookie.get_secret_value()
        try:
            shirt_data, pants_data = await asyncio.gather(
                download_template(session, int(shirt), cookie),
                download_template(session, int(pants), cookie),
            )
            preview = await asyncio.to_thread(
                generate_preview,
                shirt_data,
                pants_data,
                BASE_PATH,
            )
        except TemplateError as exc:
            logger.warning("Showcase template failed for %s: %s", exc.clothing_id, exc.detail)
            await interaction.followup.send(
                view=container_view(
                    discord.ui.TextDisplay("Could not fetch one of those clothing templates.")
                ),
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Showcase preview failed")
            await interaction.followup.send(
                view=container_view(
                    discord.ui.TextDisplay("Could not build that clothing preview.")
                ),
                ephemeral=True,
            )
            return
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("This channel cannot receive files.")),
                ephemeral=True,
            )
            return
        uploaded = discord.File(io.BytesIO(preview), filename="showcase.png")
        try:
            await channel.send(
                view=container_view(
                    discord.ui.MediaGallery(discord.MediaGalleryItem(uploaded.uri)),
                ),
                files=[uploaded],
            )
        except discord.HTTPException:
            logger.exception("Showcase channel post failed")
            await interaction.followup.send(
                view=container_view(discord.ui.TextDisplay("Could not post the showcase here.")),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=container_view(discord.ui.TextDisplay("Showcase posted.")),
            ephemeral=True,
        )


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Showcase(bot))
