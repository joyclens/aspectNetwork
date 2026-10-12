from __future__ import annotations

from typing import Any

import discord


def container_view(
    *items: discord.ui.Item[Any], timeout: float | None = None
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=timeout)
    view.add_item(discord.ui.Container(*items))
    return view
