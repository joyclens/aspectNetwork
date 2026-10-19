from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.core.bot import Aspect

PersistentView = discord.ui.LayoutView | discord.ui.View


def register_persistent(bot: Aspect, view: PersistentView) -> PersistentView:
    if not view.is_persistent():
        raise ValueError(f"{type(view).__name__} is not persistent")
    bot.add_view(view)
    return view


def unregister_persistent(bot: Aspect, view: PersistentView | None) -> None:
    if view is None:
        return
    bot._connection._view_store.remove_view(view)
    if not view.is_finished():
        view.stop()


async def disable_view(view: PersistentView) -> None:
    for item in view.walk_children():
        if isinstance(item, (discord.ui.Button, discord.ui.Select)):
            item.disabled = True
    message = getattr(view, "message", None)
    if message is None:
        return
    try:
        await message.edit(view=view)
    except discord.HTTPException:
        return
