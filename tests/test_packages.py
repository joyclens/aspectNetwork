from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.cogs.packages.constants import MAX_PACKAGE_PRICE, PACKAGER_SHARE_PERCENT
from bot.cogs.packages.models import (
    PackageDraft,
    packager_share,
    parse_price,
    resolve_purchase_kind,
    validate_sell_type,
    validate_type,
)


def test_packager_share_split() -> None:
    packager, network = packager_share(100, PACKAGER_SHARE_PERCENT)
    assert packager == 80
    assert network == 20
    assert packager + network == 100
    packager, network = packager_share(99, PACKAGER_SHARE_PERCENT)
    assert packager == 79
    assert network == 20


def test_price_validation() -> None:
    assert parse_price("1") == 1
    assert parse_price("1,000") == 1000
    assert parse_price(str(MAX_PACKAGE_PRICE)) == MAX_PACKAGE_PRICE
    assert parse_price("0") is None
    assert parse_price(str(MAX_PACKAGE_PRICE + 1)) is None
    assert parse_price("abc") is None


def test_draft_ttl() -> None:
    draft = PackageDraft(user_id=1)
    assert not draft.expired()
    draft.created_at = datetime.now(UTC) - timedelta(minutes=16)
    assert draft.expired()


def test_gift_rules() -> None:
    assert resolve_purchase_kind("Personal", 1, None) == "personal"
    assert resolve_purchase_kind("Gift", 1, None) is None
    assert resolve_purchase_kind("Gift", 1, 2) == "gift"
    assert resolve_purchase_kind("Gift", 1, 1) == "personal"


def test_type_and_sell() -> None:
    assert validate_type("Branding") == "Branding"
    assert validate_type("Other") is None
    assert validate_sell_type("One-time") == "one_time"
    assert validate_sell_type("Multiple") == "multiple"
    assert validate_sell_type("nope") is None


def test_claim_status_constants() -> None:
    from bot.cogs.packages.constants import (
        STATUS_ACCEPTED,
        STATUS_DENIED,
        STATUS_PENDING,
        STATUS_PROCESSING,
        STATUS_SOLD,
    )

    assert STATUS_PENDING == "pending"
    assert STATUS_PROCESSING == "processing"
    assert STATUS_ACCEPTED == "accepted"
    assert STATUS_DENIED == "denied"
    assert STATUS_SOLD == "sold"
