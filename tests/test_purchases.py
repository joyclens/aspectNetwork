from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.cogs.purchases import History
from bot.services.roblox import RobloxError, Sale, normalize_cookie, parse_sales


def _sale(**overrides: object) -> Sale:
    data: dict[str, object] = {
        "id": 10,
        "created": datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        "pending": False,
        "agent_id": 5,
        "agent_name": "Buyer_1",
        "agent_type": "User",
        "item_id": 99,
        "item_name": "Red Shirt",
        "item_type": "Asset",
        "amount": 70,
        "currency": "Robux",
    }
    data.update(overrides)
    return Sale.model_validate(data)


def test_parse_sales() -> None:
    sales, cursor = parse_sales(
        {
            "nextPageCursor": "next",
            "data": [
                {
                    "id": 10,
                    "created": "2026-10-13T12:00:00.000Z",
                    "isPending": False,
                    "agent": {"id": 5, "type": "User", "name": "Buyer_1"},
                    "details": {"id": 99, "name": "Red Shirt", "type": "Asset"},
                    "currency": {"amount": 70, "type": "Robux"},
                },
                {
                    "id": 11,
                    "created": "2026-10-13T12:05:00Z",
                    "isPending": True,
                    "agent": {"id": 8, "type": "User", "name": "Buyer_2"},
                    "details": {
                        "id": 50,
                        "name": "VIP",
                        "type": "GamePass",
                        "place": {"placeId": 77, "universeId": 88, "name": "Plaza"},
                        "currency": {"amount": 35, "type": "Robux"},
                    },
                },
            ],
        }
    )
    assert cursor == "next"
    assert sales[0].item_type == "Asset"
    assert sales[1].place_id == 77


def test_parse_sales_rejects_garbage() -> None:
    with pytest.raises(RobloxError):
        parse_sales({"data": [{"created": "nope"}]})


def test_parse_sales_id_hash() -> None:
    sales, cursor = parse_sales(
        {
            "nextPageCursor": None,
            "data": [
                {
                    "id": 0,
                    "idHash": "vQqd/90s/FTIO0XUpVLnBw",
                    "created": "2026-10-10T17:23:25.801Z",
                    "isPending": True,
                    "agent": {"id": 2733897535, "type": "User", "name": "Derpytoez232"},
                    "details": {"id": 91741173371014, "name": "4000", "type": "Asset"},
                    "currency": {"amount": 2800, "type": "Robux"},
                    "purchaseToken": "2df6e45e-c390-4a92-bc09-a6aae00dafcc",
                }
            ],
        }
    )
    assert cursor is None
    assert len(sales) == 1
    assert sales[0].id > 0
    assert sales[0].pending is True
    assert sales[0].amount == 2800


def test_normalize_cookie_keeps_warning_prefix() -> None:
    raw = (
        "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you"
        "-and-to-steal-your-ROBUX-and-items.|_CAEQAhoGCAIQBBgBIh"
    )
    assert normalize_cookie(raw) == raw
    assert normalize_cookie(f".ROBLOSECURITY={raw}") == raw
    assert normalize_cookie(f'"{raw}"') == raw


def test_history_paginates_only_past_five() -> None:
    sales = [_sale(id=i, item_name=f"Item {i}") for i in range(1, 6)]
    assert len(History(1, sales).children[0].children) == 1

    sales = [_sale(id=i, item_name=f"Item {i}") for i in range(1, 8)]
    assert len(History(1, sales).children[0].children) == 2
