from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from discord.ext import commands

from bot.shared.converters import Duration


@pytest.mark.asyncio
async def test_duration_parses_common_forms() -> None:
    converter = Duration()
    ctx = MagicMock(spec=commands.Context[Any])
    assert await converter.convert(ctx, "12h") == 12 * 60 * 60
    assert await converter.convert(ctx, "2d") == 2 * 24 * 60 * 60
    assert await converter.convert(ctx, "30m") == 30 * 60
    assert await converter.convert(ctx, "1w2d3h4m5s") == (
        7 * 24 * 60 * 60 + 2 * 24 * 60 * 60 + 3 * 60 * 60 + 4 * 60 + 5
    )


@pytest.mark.asyncio
async def test_duration_rejects_empty() -> None:
    converter = Duration()
    ctx = MagicMock(spec=commands.Context[Any])
    with pytest.raises(commands.BadArgument):
        await converter.convert(ctx, "")
    with pytest.raises(commands.BadArgument):
        await converter.convert(ctx, "nope")
