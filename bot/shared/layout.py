from __future__ import annotations

from typing import Any

import discord

from bot.shared.errors import report_interaction


class AspectLayout(discord.ui.LayoutView):
    async def on_error(
        self,
        interaction: discord.Interaction[Any],
        error: Exception,
        item: discord.ui.Item[Any],
    ) -> None:
        custom_id = getattr(item, "custom_id", None) or type(item).__name__
        await report_interaction(interaction, error, where=f"Button {custom_id}")


def container_view(*items: discord.ui.Item[Any], timeout: float | None = None) -> AspectLayout:
    view = AspectLayout(timeout=timeout)
    view.add_item(discord.ui.Container(*items))
    return view
