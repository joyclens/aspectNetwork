from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bot.core.bot import Aspect

_ACCENT = 0xFF3171
_TEMPLATE = (
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("assets", "ascii", "banner.txt")
    .read_text(encoding="utf-8")
)


def render_banner(values: Mapping[str, str]) -> str:
    rendered = _TEMPLATE
    for key, value in values.items():
        rendered = rendered.replace("${" + key + "}", value)
    return rendered


def _accent(colour: int) -> str:
    red = (colour >> 16) & 0xFF
    green = (colour >> 8) & 0xFF
    blue = colour & 0xFF
    return f"\033[38;2;{red};{green};{blue}m"


def print_banner(bot: Aspect) -> None:
    rendered = render_banner(
        {
            "accent": _accent(_ACCENT),
            "reset": "\033[0m",
            "bold_white": "\033[1m",
            "aspect": str(bot.user),
            "version": bot.version,
            "guilds": f"{len(bot.guilds):,}",
            "users": f"{len(bot.users):,}",
            "cogs": str(len(bot.cogs)),
            "commands": str(len(set(bot.walk_commands()))),
            "db": bot.db_version,
        }
    )
    sys.stdout.buffer.write(rendered.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()
