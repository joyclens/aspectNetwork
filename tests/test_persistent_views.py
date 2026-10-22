from __future__ import annotations

from collections.abc import Iterator

import discord
import pytest
from discord.ext import commands

from bot.cogs.giveaways import giveaway_persistent_views
from bot.cogs.marketplace import Marketplace
from bot.cogs.packages.views import (
    ApproveButton,
    DenyButton,
    PurchaseButton,
    ReportButton,
    ResendButton,
)
from bot.cogs.promotions.cog import DYNAMIC_ITEMS as PROMOTION_ITEMS
from bot.cogs.tickets import Dashboard, ticket_panel_view
from bot.events.verification import VerificationPanel
from bot.shared.persistence import register_persistent, unregister_persistent

PERSISTENT_EXTENSIONS = (
    "bot.cogs.tickets",
    "bot.cogs.giveaways",
    "bot.cogs.marketplace",
    "bot.cogs.packages",
    "bot.cogs.promotions",
    "bot.events.verification",
)

EXPECTED_CUSTOM_IDS = frozenset(
    {
        "support:claim",
        "support:unclaim",
        "closeSupport:button",  # LEGACY
        "support:escalate",
        "support:gethelp",
        "dashboard:menu",
        "marketplace:menu",
        "marketplace:claim",
        "marketplace:queue",
        "giveaway:join",
        "giveaway:participants",
        "giveaway:participants_ended",
        "verifyButton",  # LEGACY
    }
)

DYNAMIC_ITEMS = (
    ApproveButton,
    DenyButton,
    PurchaseButton,
    ReportButton,
    ResendButton,
    *PROMOTION_ITEMS,
)


def _dispatchable_ids(view: discord.ui.LayoutView | discord.ui.View) -> set[str]:
    found: set[str] = set()
    for item in view.walk_children():
        if not item.is_dispatchable():
            continue
        custom_id = getattr(item, "custom_id", None)
        assert custom_id is not None, f"{type(item).__name__} missing custom_id"
        assert isinstance(custom_id, str)
        assert 1 <= len(custom_id) <= 100
        found.add(custom_id)
    return found


def _store_custom_ids(bot: commands.Bot) -> set[str]:
    store = bot._connection._view_store
    found: set[str] = set()
    for bucket in store._views.values():
        for (_component_type, custom_id), _item in bucket.items():
            found.add(custom_id)
    return found


@pytest.fixture
def bot() -> Iterator[commands.Bot]:
    client = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    yield client


def test_static_persistent_views_have_unique_custom_ids() -> None:
    views = [
        Dashboard(),
        ticket_panel_view(),
        Marketplace(),
        VerificationPanel(),
        *giveaway_persistent_views(),
    ]
    seen: set[str] = set()
    for view in views:
        assert view.timeout is None
        assert view.is_persistent()
        for custom_id in _dispatchable_ids(view):
            assert custom_id not in seen, f"duplicate custom_id {custom_id}"
            seen.add(custom_id)
    missing = EXPECTED_CUSTOM_IDS - seen
    assert not missing, f"missing expected custom_ids: {sorted(missing)}"


@pytest.mark.asyncio
async def test_register_unregister_roundtrip(bot: commands.Bot) -> None:
    view = Dashboard()
    register_persistent(bot, view)  # type: ignore[arg-type]
    assert "dashboard:menu" in _store_custom_ids(bot)
    assert "support:gethelp" in _store_custom_ids(bot)
    unregister_persistent(bot, view)  # type: ignore[arg-type]
    assert "dashboard:menu" not in _store_custom_ids(bot)


@pytest.mark.asyncio
async def test_extensions_load_reload_keep_persistent_items(bot: commands.Bot) -> None:
    for extension in PERSISTENT_EXTENSIONS:
        await bot.load_extension(extension)

    before = _store_custom_ids(bot)
    assert EXPECTED_CUSTOM_IDS <= before

    dynamic = bot._connection._view_store._dynamic_items
    for item in DYNAMIC_ITEMS:
        assert item.__discord_ui_compiled_template__ in dynamic

    for extension in PERSISTENT_EXTENSIONS:
        await bot.reload_extension(extension)

    after = _store_custom_ids(bot)
    assert EXPECTED_CUSTOM_IDS <= after

    dynamic_after = bot._connection._view_store._dynamic_items
    for item in DYNAMIC_ITEMS:
        assert item.__discord_ui_compiled_template__ in dynamic_after

    for custom_id in sorted(EXPECTED_CUSTOM_IDS):
        assert custom_id in after

    await bot.close()
