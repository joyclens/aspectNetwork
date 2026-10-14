from __future__ import annotations

import asyncio
import sys
from contextlib import suppress

from pydantic import ValidationError

from bot.core.bot import Aspect
from bot.core.config import Settings, load_settings
from bot.core.ids import Secrets
from bot.core.logging import setup_logging


async def run(settings: Settings) -> None:
    async with Aspect(settings) as bot:
        await bot.start(Secrets.discord_token)


def main() -> None:
    try:
        settings = load_settings()
    except ValidationError:
        print("Invalid configuration.", file=sys.stderr)
        raise SystemExit(1) from None
    setup_logging(settings)
    with suppress(KeyboardInterrupt, ProcessLookupError):
        asyncio.run(run(settings))
