from __future__ import annotations

import io
import logging
import secrets
import traceback
from typing import Any

import discord
from discord.ext import commands

from bot.core.ids import Emojis, Users
from bot.core.logging import secret_values

logger = logging.getLogger("aspect")


class DatabaseUnavailable(commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("Database is unavailable")


def error_notice(code: str) -> str:
    return (
        "**Sorry!** I encountered an error, please forward this error ID "
        f"to <@{Users.error_report}>: `{code}`"
    )


def error_mentions() -> discord.AllowedMentions:
    return discord.AllowedMentions(users=[discord.Object(id=Users.error_report)])


def remember_error(
    store: dict[str, BaseException],
    error: BaseException,
    *,
    where: str,
) -> str:
    code = secrets.token_urlsafe(12)
    store[code] = error
    logger.error("%s %s", where, code, exc_info=(type(error), error, error.__traceback__))
    return code


def format_error(settings: Any, error: BaseException) -> str:
    text = "".join(traceback.format_exception(error))
    for secret in secret_values(settings):
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return text


async def deliver_trace(user: discord.abc.Messageable, settings: Any, error: BaseException) -> bool:
    text = format_error(settings, error)
    try:
        if len(text) > 1900:
            await user.send(file=discord.File(io.BytesIO(text.encode()), filename="error.py"))
        else:
            await user.send(f"```py\n{text}\n```")
    except discord.HTTPException:
        return False
    return True


async def report_interaction(
    interaction: discord.Interaction[Any],
    error: BaseException,
    *,
    where: str,
) -> None:
    from bot.core.bot import Aspect

    client = interaction.client
    if not isinstance(client, Aspect):
        logger.error("%s", where, exc_info=(type(error), error, error.__traceback__))
        return
    code = remember_error(client.traceback, error, where=where)
    emoji = Emojis.error
    view = discord.ui.LayoutView()
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(f"{emoji} {error_notice(code)}")))
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                view=view,
                ephemeral=True,
                allowed_mentions=error_mentions(),
            )
        else:
            await interaction.response.send_message(
                view=view,
                ephemeral=True,
                allowed_mentions=error_mentions(),
            )
    except discord.HTTPException:
        logger.error("Could not send error %s", code)
    if await client.is_owner(interaction.user):
        await deliver_trace(interaction.user, client.settings, error)
