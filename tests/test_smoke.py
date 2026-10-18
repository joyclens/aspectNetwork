from __future__ import annotations

from typing import Any

import discord
import pytest
from discord.ext import commands

from bot.core.bot import _discover


def _app_commands(root: list[Any], prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for command in root:
        name = f"{prefix}{command.name}" if not prefix else f"{prefix} {command.name}"
        description = getattr(command, "description", None) or ""
        found.append((name, description))
        children = getattr(command, "commands", None)
        if children:
            found.extend(_app_commands(list(children), name))
    return found


def _collect_custom_ids(view: discord.ui.View | discord.ui.LayoutView) -> list[str]:
    ids: list[str] = []
    for child in view.walk_children():
        custom_id = getattr(child, "custom_id", None)
        if isinstance(custom_id, str) and custom_id:
            ids.append(custom_id)
    return ids


@pytest.mark.asyncio
async def test_extensions_load_and_command_tree() -> None:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    modules = _discover("cogs") + _discover("events")
    assert modules
    for module in modules:
        await bot.load_extension(module)

    prefix_names = [command.qualified_name for command in bot.walk_commands()]
    assert prefix_names
    assert len(prefix_names) == len(set(prefix_names))

    app_entries = _app_commands(bot.tree.get_commands())
    app_names = [name for name, _description in app_entries]
    assert app_names
    assert len(app_names) == len(set(app_names))
    for name, description in app_entries:
        assert description, f"{name} is missing a description"
        assert len(description) <= 100, f"{name} description is too long"

    from bot.cogs.giveaways import register_persistent_views
    from bot.cogs.marketplace import Marketplace
    from bot.cogs.tickets import Dashboard
    from bot.events.verification import VerificationPanel

    register_persistent_views(bot)
    persistent = [
        VerificationPanel(),
        Marketplace(),
        Dashboard(),
    ]
    for view in persistent:
        assert view.timeout is None
        assert _collect_custom_ids(view), f"{type(view).__name__} has no custom_id"
    assert any(getattr(view, "timeout", None) is None for view in bot.persistent_views), (
        "giveaway persistent views were not registered"
    )

    from bot.cogs.packages.views import (
        ApproveButton,
        DenyButton,
        PurchaseButton,
        ReportButton,
        ResendButton,
    )

    for item in (
        ApproveButton(1),
        DenyButton(1),
        PurchaseButton(1),
        ReportButton(1),
        ResendButton(1),
    ):
        custom_id = getattr(item.item, "custom_id", None)
        assert isinstance(custom_id, str) and custom_id

    await bot.close()
