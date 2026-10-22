from __future__ import annotations

from datetime import UTC, datetime

ITEM_GIVEAWAY = 134641402925074
ITEM_ADVERT = 113272473148244
ITEM_PRIORITY = 104447359521852
ITEM_DAILY = 117463223374082

KIND_GIVEAWAY = "giveaway"
KIND_ADVERT = "advert"

TIER_NORMAL = "normal"
TIER_PRIORITY = "priority"
TIER_DAILY = "daily"

ITEMS = {
    ITEM_GIVEAWAY: KIND_GIVEAWAY,
    ITEM_ADVERT: KIND_ADVERT,
    ITEM_PRIORITY: TIER_PRIORITY,
    ITEM_DAILY: TIER_DAILY,
}
KINDS = frozenset({KIND_GIVEAWAY, KIND_ADVERT})

KIND_LABELS = {
    KIND_GIVEAWAY: "Sponsored Giveaway",
    KIND_ADVERT: "Paid Advertisement",
}
TIER_LABELS = {
    TIER_NORMAL: "Normal Queue",
    TIER_PRIORITY: "Priority Queue",
    TIER_DAILY: "Daily Queue",
}
TIER_RANK = {TIER_NORMAL: 0, TIER_PRIORITY: 1, TIER_DAILY: 2}
SPEED = {TIER_NORMAL: 1.0, TIER_PRIORITY: 1.5, TIER_DAILY: 3.0}

BASE_GAP_DAYS = 3
PUSH_BACK_DAYS = 2
PICKER_DAYS = 7

MIN_PRIZE_ROBUX = 500
MAX_WINNERS = 50
MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_ADVERT_LENGTH = 2000

STATUS_CLAIMED = "claimed"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_POSTED = "posted"

POLL_INTERVAL_SECONDS = 60
AUTO_CLAIM_SINCE = datetime(2026, 10, 21, tzinfo=UTC)

SUBMIT_TEMPLATE = r"promotion:submit:(?P<id>\d+)"
APPROVE_TEMPLATE = r"promotion:approve:(?P<id>\d+)"
DENY_TEMPLATE = r"promotion:deny:(?P<id>\d+)"
EDIT_TEMPLATE = r"promotion:edit:(?P<id>\d+)"
REVIEW_TEMPLATE = r"promotion:review:(?P<id>\d+)"
RESCHEDULE_TEMPLATE = r"promotion:reschedule:(?P<id>\d+)"
POSTED_TEMPLATE = r"promotion:posted:(?P<id>\d+)"
