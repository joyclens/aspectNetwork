from __future__ import annotations

from typing import Any

from discord import app_commands
from discord.ext import commands

from bot.core.bot import Aspect
from bot.shared.context import require_context
from bot.shared.errors import deliver_trace

_CODE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _code_ok(code: str) -> bool:
    return 8 <= len(code) <= 32 and all(char in _CODE for char in code)


class Developer(commands.Cog):
    def __init__(self, bot: Aspect) -> None:
        self.bot = bot

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="traceback",
        aliases=("trace", "error"),
        description="Show a stored traceback by error code.",
    )
    @app_commands.describe(error_code="Error code from a failed command or button")
    @commands.is_owner()
    async def traceback(
        self,
        ctx: commands.Context[Any],
        error_code: str | None = None,
    ) -> None:
        ctx = require_context(ctx)
        code = error_code
        if code is None:
            if not self.bot.traceback:
                await ctx.warn(
                    "I was **unable** to find a traceback, "
                    "maybe no tracebacks have been raised recently?"
                )
                return
            code = next(reversed(self.bot.traceback))
        elif not _code_ok(code):
            await ctx.warn("That error code is **not** valid.")
            return
        exc = self.bot.traceback.get(code)
        if exc is None:
            await ctx.warn("I was **unable** to find a traceback with that error code.")
            return
        if not await deliver_trace(ctx.author, self.bot.settings, exc):
            await ctx.warn("I was **unable** to send you the traceback.")


async def setup(bot: Aspect) -> None:
    await bot.add_cog(Developer(bot))
