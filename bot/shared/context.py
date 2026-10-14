from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import discord
from discord.ext import commands

from bot.core.ids import Emojis
from bot.shared.layout import AspectLayout, container_view

if TYPE_CHECKING:
    from bot.core.bot import Aspect


class PromptDeclined(commands.CommandError):
    pass


class _Choice(discord.ui.Button[Any]):
    def __init__(self, label: str, style: discord.ButtonStyle, accepted: bool) -> None:
        super().__init__(label=label, style=style)
        self.accepted = accepted

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        view = self.view
        if not isinstance(view, Confirmation):
            return
        view.status = self.accepted
        if not interaction.response.is_done():
            await interaction.response.defer()
        view.stop()


class Confirmation(AspectLayout):
    def __init__(self, author_id: int, text: str) -> None:
        super().__init__(timeout=30)
        self.author_id = author_id
        self.status: bool | None = None
        row = discord.ui.ActionRow(
            _Choice("Confirm", discord.ButtonStyle.green, True),
            _Choice("Decline", discord.ButtonStyle.danger, False),
        )
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text), row))

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        return interaction.user.id == self.author_id


class Context(commands.Context["Aspect"]):
    bot: Aspect

    async def approve(self, text: str) -> discord.Message:
        return await self.send(view=self._view(text, Emojis.approve))

    async def warn(self, text: str, **kwargs: Any) -> discord.Message:
        if self.interaction is not None:
            kwargs.setdefault("ephemeral", True)
        return await self.send(view=self._view(text, Emojis.warn), **kwargs)

    async def prompt(self, text: str) -> Literal[True]:
        command_name = self.command.qualified_name if self.command else "unknown"
        async with self.bot.lock_for(f"prompt:{self.author.id}:{command_name}"):
            view = Confirmation(self.author.id, text)
            message = await self.send(view=view)
            await view.wait()
            await _delete_quietly(message)
            if view.status is not True:
                raise PromptDeclined()
            return True

    def _view(self, text: str, emoji: str) -> discord.ui.LayoutView:
        return container_view(discord.ui.TextDisplay(f"{emoji} {text}"))


async def _delete_quietly(message: discord.Message) -> None:
    try:
        await message.delete()
    except discord.HTTPException:
        return


def require_context(ctx: commands.Context[Any]) -> Context:
    if isinstance(ctx, Context):
        return ctx
    raise commands.CommandError("Unexpected command context")
