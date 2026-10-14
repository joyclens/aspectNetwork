from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bot.cogs.packages.constants import (
    DRAFT_TTL_SECONDS,
    KIND_GIFT,
    KIND_PERSONAL,
    MAX_PACKAGE_PRICE,
    PACKAGE_TYPES,
    SELL_MULTIPLE,
    SELL_ONE_TIME,
)


@dataclass
class StoredFile:
    filename: str
    content_type: str
    data: bytes


@dataclass
class PackageDraft:
    user_id: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    package_type: str | None = None
    title: str | None = None
    price: int | None = None
    description: str | None = None
    sell_type: str | None = None
    customizable: bool | None = None
    showcase: StoredFile | None = None
    files: list[StoredFile] = field(default_factory=list)

    def expired(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        return (moment - self.created_at).total_seconds() > DRAFT_TTL_SECONDS

    def touch(self) -> None:
        self.created_at = datetime.now(UTC)


def packager_share(price: int, percent: int = 80) -> tuple[int, int]:
    packager_amount = price * percent // 100
    return packager_amount, price - packager_amount


def parse_price(raw: str) -> int | None:
    cleaned = raw.strip().replace(",", "")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    if value < 1 or value > MAX_PACKAGE_PRICE:
        return None
    return value


def validate_type(value: str) -> str | None:
    return value if value in PACKAGE_TYPES else None


def validate_sell_type(value: str) -> str | None:
    if value in {SELL_ONE_TIME, SELL_MULTIPLE, "One-time", "Multiple"}:
        if value == "One-time":
            return SELL_ONE_TIME
        if value == "Multiple":
            return SELL_MULTIPLE
        return value
    return None


def validate_bool_select(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def resolve_purchase_kind(kind: str, buyer_id: int, recipient_id: int | None) -> str | None:
    if kind not in {KIND_PERSONAL, KIND_GIFT, "Personal", "Gift"}:
        return None
    normalized = KIND_GIFT if kind in {KIND_GIFT, "Gift"} else KIND_PERSONAL
    if normalized == KIND_GIFT:
        if recipient_id is None:
            return None
        if recipient_id == buyer_id:
            return KIND_PERSONAL
        return KIND_GIFT
    return KIND_PERSONAL


def draft_errors(draft: PackageDraft, *, step: int) -> list[str]:
    errors: list[str] = []
    if step >= 1:
        if draft.package_type is None:
            errors.append("Package type is required.")
        if not draft.title or not (1 <= len(draft.title) <= 50):
            errors.append("Title must be 1–50 characters.")
        if draft.price is None:
            errors.append(f"Price must be an integer from 1 to {MAX_PACKAGE_PRICE:,}.")
    if step >= 2:
        if not draft.description or len(draft.description) > 1000:
            errors.append("Description must be 1–1000 characters.")
        if draft.sell_type is None:
            errors.append("Sell type is required.")
        if draft.customizable is None:
            errors.append("Customizable is required.")
    if step >= 3:
        if draft.showcase is None:
            errors.append("Showcase must be exactly one image or video.")
        if not (1 <= len(draft.files) <= 10):
            errors.append("Provide between 1 and 10 package files.")
    return errors


def neutralise_fences(text: str) -> str:
    return text.replace("```", "'''")


def as_dict(draft: PackageDraft) -> dict[str, Any]:
    return {
        "type": draft.package_type,
        "title": draft.title,
        "price": draft.price,
        "description": draft.description,
        "sell_type": draft.sell_type,
        "customizable": draft.customizable,
    }
