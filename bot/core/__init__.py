from __future__ import annotations

from typing import Any

__all__ = ["Aspect"]


def __getattr__(name: str) -> Any:
    if name == "Aspect":
        from bot.core.bot import Aspect

        return Aspect
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
