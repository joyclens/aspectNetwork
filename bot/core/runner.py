from __future__ import annotations

import asyncio
import sys
from contextlib import suppress

from dotenv import load_dotenv
from pydantic import ValidationError

from bot.core.bot import Aspect
from bot.core.config import Settings, load_settings
from bot.core.identity import apply as apply_identity
from bot.core.ids import Secrets
from bot.core.logging import setup_logging


async def run(settings: Settings) -> None:
    apply_identity()
    async with Aspect(settings) as bot:
        await bot.start(Secrets.discord_token)


def main() -> None:
    load_dotenv()
    try:
        settings = load_settings()
    except ValidationError:
        print("Invalid configuration.", file=sys.stderr)
        raise SystemExit(1) from None
    setup_logging(settings)
    with suppress(KeyboardInterrupt, ProcessLookupError):
        asyncio.run(run(settings))
