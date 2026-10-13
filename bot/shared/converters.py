from __future__ import annotations

import re
from typing import Any

from discord.ext import commands

_DURATION = re.compile(
    r"^(?:(?P<weeks>\d+)w)?(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?"
    r"(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$",
    re.IGNORECASE,
)
_UNITS = {
    "weeks": 7 * 24 * 60 * 60,
    "days": 24 * 60 * 60,
    "hours": 60 * 60,
    "minutes": 60,
    "seconds": 1,
}


class Duration(commands.Converter[int]):
    async def convert(self, ctx: commands.Context[Any], argument: str) -> int:
        match = _DURATION.fullmatch(argument.strip())
        if match is None or not any(match.groups()):
            raise commands.BadArgument("That duration is not valid. Use `12h`, `1d`, `30m`.")
        total = sum(int(match[name] or 0) * seconds for name, seconds in _UNITS.items())
        if total <= 0:
            raise commands.BadArgument("That duration is not valid. Use `12h`, `1d`, `30m`.")
        return total
