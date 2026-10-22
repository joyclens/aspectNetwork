from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bot.cogs.promotions.constants import (
    ITEMS,
    KIND_ADVERT,
    KIND_GIVEAWAY,
    TIER_DAILY,
    TIER_NORMAL,
    TIER_PRIORITY,
)
from bot.cogs.promotions.models import (
    advert_data,
    first_invite_code,
    giveaway_data,
    invite_url,
    parse_date,
    picker_dates,
    post_day,
    post_link,
    post_time,
    robux_value,
    suggest_slot,
    upgraded_slot,
)
from bot.shared.converters import parse_duration

TODAY = date(2026, 10, 22)


def days(count: int) -> date:
    return TODAY + timedelta(days=count)


def test_items_map_catalog_ids() -> None:
    assert ITEMS[134641402925074] == KIND_GIVEAWAY
    assert ITEMS[113272473148244] == KIND_ADVERT
    assert ITEMS[104447359521852] == TIER_PRIORITY
    assert ITEMS[117463223374082] == TIER_DAILY


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(TIER_NORMAL, 3), (TIER_PRIORITY, 2), (TIER_DAILY, 1)],
)
def test_suggest_empty_queue_matches_between_times(tier: str, expected: int) -> None:
    assert suggest_slot(TODAY, None, tier) == days(expected)


def test_suggest_scales_wait_by_speed() -> None:
    last = days(6)
    assert suggest_slot(TODAY, last, TIER_NORMAL) == days(9)
    assert suggest_slot(TODAY, last, TIER_PRIORITY) == days(6)
    assert suggest_slot(TODAY, last, TIER_DAILY) == days(3)


def test_suggest_ignores_past_slots() -> None:
    assert suggest_slot(TODAY, days(-5), TIER_NORMAL) == days(3)


def test_upgrade_moves_slot_sooner() -> None:
    assert upgraded_slot(TODAY, days(9), TIER_NORMAL, TIER_PRIORITY) == days(6)
    assert upgraded_slot(TODAY, days(9), TIER_NORMAL, TIER_DAILY) == days(3)
    assert upgraded_slot(TODAY, days(6), TIER_PRIORITY, TIER_DAILY) == days(3)


def test_upgrade_never_delays_or_moves_imminent_slots() -> None:
    assert upgraded_slot(TODAY, days(1), TIER_NORMAL, TIER_DAILY) == days(1)
    assert upgraded_slot(TODAY, TODAY, TIER_NORMAL, TIER_DAILY) == TODAY
    assert upgraded_slot(TODAY, days(2), TIER_NORMAL, TIER_DAILY) == days(1)


def test_post_time_is_3pm_eastern() -> None:
    assert post_time(date(2026, 10, 22)) == datetime(2026, 10, 22, 19, tzinfo=UTC)
    assert post_time(date(2026, 12, 1)) == datetime(2026, 12, 1, 20, tzinfo=UTC)


def test_post_day_uses_eastern_date() -> None:
    assert post_day(datetime(2026, 10, 23, 2, tzinfo=UTC)) == date(2026, 10, 22)
    assert post_day(datetime(2026, 10, 23, 5, tzinfo=UTC)) == date(2026, 10, 23)


def test_picker_dates_cover_the_week() -> None:
    assert picker_dates(TODAY) == [days(offset) for offset in range(7)]


def test_parse_date_formats() -> None:
    assert parse_date("03/11/2026", "dmy", TODAY) == date(2026, 11, 3)
    assert parse_date("11/03/2026", "mdy", TODAY) == date(2026, 11, 3)
    assert parse_date("31/02/2027", "dmy", TODAY) is None
    assert parse_date("2026-11-03", "dmy", TODAY) is None
    assert parse_date("21/10/2026", "dmy", TODAY) is None
    assert parse_date("22/10/2026", "dmy", TODAY) == TODAY


def test_invites() -> None:
    assert invite_url("discord.gg/aspect") == "https://discord.gg/aspect"
    assert invite_url("https://discord.gg/Aspect-1") == "https://discord.gg/Aspect-1"
    assert invite_url("http://discord.gg/aspect") is None
    assert invite_url("discord.com/invite/aspect") is None
    assert invite_url("join discord.gg/aspect") is None
    assert first_invite_code("Join us! https://discord.gg/abc today") == "abc"
    assert first_invite_code("no invite") is None


def test_robux_value() -> None:
    assert robux_value("1,000 Robux") == 1000
    assert robux_value("Limited worth 750 robux") == 750
    assert robux_value("A limited") is None


def test_post_link() -> None:
    assert post_link("https://discord.com/channels/1/2/3") == (1, 2, 3)
    assert post_link("https://ptb.discord.com/channels/1/2/3") == (1, 2, 3)
    assert post_link("https://discord.com/channels/1/2") is None
    assert post_link("https://example.com/channels/1/2/3") is None


def test_parse_duration() -> None:
    assert parse_duration("1d12h") == 129600
    assert parse_duration("0d") is None
    assert parse_duration("soon") is None


def test_giveaway_data_valid() -> None:
    data, error = giveaway_data("1,000 Robux", "discord.gg/aspect", "2", "7d")
    assert error is None
    assert data == {
        "prize": "1,000 Robux",
        "server": "https://discord.gg/aspect",
        "winners": 2,
        "duration": "7d",
        "seconds": 604800,
    }


@pytest.mark.parametrize(
    ("prize", "server", "winners", "duration"),
    [
        ("499 Robux", "discord.gg/aspect", "1", "1d"),
        ("A limited", "discord.gg/aspect", "1", "1d"),
        ("500 Robux", "aspect.gg", "1", "1d"),
        ("500 Robux", "discord.gg/aspect", "0", "1d"),
        ("500 Robux", "discord.gg/aspect", "51", "1d"),
        ("500 Robux", "discord.gg/aspect", "two", "1d"),
        ("500 Robux", "discord.gg/aspect", "1", "7d1s"),
        ("500 Robux", "discord.gg/aspect", "1", "later"),
    ],
)
def test_giveaway_data_invalid(prize: str, server: str, winners: str, duration: str) -> None:
    data, error = giveaway_data(prize, server, winners, duration)
    assert data is None
    assert error


def test_advert_data() -> None:
    assert advert_data("  Join us  ") == ({"text": "Join us"}, None)
    assert advert_data("   ")[0] is None
    assert advert_data("x" * 2001)[0] is None
