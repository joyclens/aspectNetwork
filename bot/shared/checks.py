from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.core.ids import Roles
from bot.shared.errors import DatabaseUnavailable

if TYPE_CHECKING:
    from bot.core.bot import Aspect
    from bot.core.database import Database


def database(bot: Aspect) -> Database:
    if bot.db is None:
        raise DatabaseUnavailable()
    return bot.db


def has_role(member: discord.Member, role_id: int) -> bool:
    if role_id < 1:
        return False
    if member.guild_permissions.administrator:
        return True
    return member.get_role(role_id) is not None or any(role.id == role_id for role in member.roles)


def is_management(member: discord.Member) -> bool:
    return has_role(member, Roles.management)
