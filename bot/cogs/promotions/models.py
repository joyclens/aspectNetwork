from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bot.cogs.promotions.constants import (
    BASE_GAP_DAYS,
    MAX_ADVERT_LENGTH,
    MAX_DURATION_SECONDS,
    MAX_WINNERS,
    MIN_PRIZE_ROBUX,
    PICKER_DAYS,
    POST_TIME,
    POST_ZONE,
    SPEED,
)
from bot.shared.converters import parse_duration

_INVITE = re.compile(r"(?:https://)?discord\.gg/([A-Za-z0-9-]+)", re.IGNORECASE)
_ANY_INVITE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_POST_LINK = re.compile(
    r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)
_NUMBER = re.compile(r"\d[\d,]*")
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def post_time(slot: date) -> datetime:
    return datetime.combine(slot, POST_TIME, tzinfo=POST_ZONE).astimezone(UTC)


def post_day(moment: datetime) -> date:
    return moment.astimezone(POST_ZONE).date()


def suggest_slot(today: date, last_slot: date | None, tier: str) -> date:
    base = max(last_slot or today, today)
    wait = (base - today).days + BASE_GAP_DAYS
    return today + timedelta(days=max(1, math.ceil(wait / SPEED[tier])))


def upgraded_slot(today: date, slot: date, old_tier: str, new_tier: str) -> date:
    remaining = (slot - today).days
    if remaining <= 1:
        return slot
    wait = math.ceil(remaining * SPEED[old_tier] / SPEED[new_tier])
    return min(slot, today + timedelta(days=max(1, wait)))


def picker_dates(today: date) -> list[date]:
    return [today + timedelta(days=offset) for offset in range(PICKER_DAYS)]


def parse_date(text: str, order: str, today: date) -> date | None:
    match = _DATE.fullmatch(text.strip())
    if match is None:
        return None
    first, second, year = (int(part) for part in match.groups())
    day, month = (first, second) if order == "dmy" else (second, first)
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed if parsed >= today else None


def invite_url(text: str) -> str | None:
    match = _INVITE.fullmatch(text.strip())
    return f"https://discord.gg/{match[1]}" if match else None


def first_invite_code(text: str) -> str | None:
    match = _ANY_INVITE.search(text)
    return match[1] if match else None


def robux_value(text: str) -> int | None:
    match = _NUMBER.search(text)
    return int(match[0].replace(",", "")) if match else None


def post_link(text: str) -> tuple[int, int, int] | None:
    match = _POST_LINK.fullmatch(text.strip())
    if match is None:
        return None
    guild_id, channel_id, message_id = (int(part) for part in match.groups())
    return guild_id, channel_id, message_id


def giveaway_data(
    prize: str,
    server: str,
    winners: str,
    duration: str,
) -> tuple[dict[str, Any] | None, str | None]:
    prize = prize.strip()
    value = robux_value(prize)
    if not prize or value is None or value < MIN_PRIZE_ROBUX:
        return None, (
            f"The prize must include its Robux value of at least **{MIN_PRIZE_ROBUX}**, "
            "for example `1,000 Robux`."
        )
    url = invite_url(server)
    if url is None:
        return None, "The server must be a `discord.gg/` or `https://discord.gg/` invite."
    count = int(winners.strip()) if winners.strip().isdigit() else 0
    if not 1 <= count <= MAX_WINNERS:
        return None, f"The winner count must be a number from 1 to {MAX_WINNERS}."
    seconds = parse_duration(duration)
    if seconds is None or seconds > MAX_DURATION_SECONDS:
        return None, "The duration must look like `12h`, `3d` or `1w` and be at most `7d`."
    return {
        "prize": prize,
        "server": url,
        "winners": count,
        "duration": duration.strip().lower(),
        "seconds": seconds,
    }, None


def advert_data(text: str) -> tuple[dict[str, Any] | None, str | None]:
    text = text.strip()
    if not text:
        return None, "The advertisement cannot be empty."
    if len(text) > MAX_ADVERT_LENGTH:
        return None, f"The advertisement must be at most {MAX_ADVERT_LENGTH} characters."
    return {"text": text}, None
