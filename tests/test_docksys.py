from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest

from bot.docksys.client import DockClient
from bot.docksys.errors import DockAuthError, DockRateLimitError
from bot.docksys.service import Dock

META = {
    "requestId": "req_test_1",
    "version": "2.0.0",
    "rateLimit": {
        "limit": 1,
        "remaining": 0,
        "resetAt": "2026-05-07T16:30:01.000Z",
        "retryAfter": None,
        "scope": "api_key",
    },
    "tier": "free",
}


def _success(data: Any) -> dict[str, Any]:
    return {
        "status": 200,
        "data": data,
        "meta": META,
        "timestamp": "2026-05-07T16:30:00.000Z",
    }


def _error(
    status: int,
    code: str,
    message: str,
    *,
    retry_after: int | None = None,
) -> dict[str, Any]:
    meta = {
        **META,
        "rateLimit": {
            **META["rateLimit"],
            "retryAfter": retry_after,
        },
    }
    return {
        "status": status,
        "error": {"code": code, "message": message, "details": None},
        "meta": meta,
        "timestamp": "2026-05-07T16:30:00.000Z",
    }


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: dict[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = dict(headers or {})

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[dict[str, Any]] = []
        self._queue: list[tuple[int, dict[str, Any], dict[str, str]]] = []

    def enqueue(
        self,
        status: int,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self._queue.append((status, body, headers or {}))

    @asynccontextmanager
    async def request(self, method: str, url: str, **kwargs: Any) -> AsyncIterator[FakeResponse]:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self._queue:
            raise AssertionError("no queued response")
        status, body, headers = self._queue.pop(0)
        yield FakeResponse(status, body, headers)


@pytest.fixture
def http() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(http: FakeSession) -> DockClient:
    return DockClient("test-api-key-value", "PID-TEST", http)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_auth_header(client: DockClient, http: FakeSession) -> None:
    http.enqueue(
        200,
        _success(
            {
                "discordId": "1",
                "robloxId": "156319135",
                "resolved": {"roblox": None, "discord": None},
            }
        ),
    )
    linked = await client.linked_roblox(1, 2)
    assert linked == "156319135"
    headers = http.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer test-api-key-value"
    assert "test-api-key-value" not in repr(client)


@pytest.mark.asyncio
async def test_error_mapping_keeps_request_id(client: DockClient, http: FakeSession) -> None:
    http.enqueue(401, _error(401, "INVALID_API_KEY", "Invalid API key."))
    with pytest.raises(DockAuthError) as raised:
        await client.linked_roblox(1, 2)
    assert raised.value.code == "INVALID_API_KEY"
    assert raised.value.request_id == "req_test_1"
    assert raised.value.status == 401


@pytest.mark.asyncio
async def test_link_not_found(client: DockClient, http: FakeSession) -> None:
    http.enqueue(404, _error(404, "LINK_NOT_FOUND", "Not found."))
    assert await client.linked_roblox(1, 2) is None


@pytest.mark.asyncio
async def test_rate_limit_retry(
    client: DockClient, http: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("bot.docksys.client.asyncio.sleep", fake_sleep)
    http.enqueue(
        429,
        _error(429, "RATE_LIMITED", "Too many requests.", retry_after=3),
        {"Retry-After": "3"},
    )
    http.enqueue(
        200,
        _success(
            {
                "discordId": "1",
                "robloxId": "99",
                "resolved": {"roblox": None, "discord": None},
            }
        ),
    )
    assert await client.linked_roblox(1, 2) == "99"
    assert sleeps == [3.0]
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_idempotency_in_progress_retry(
    client: DockClient,
    http: FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("bot.docksys.client.asyncio.sleep", fake_sleep)
    http.enqueue(
        503,
        _error(503, "IDEMPOTENCY_IN_PROGRESS", "In progress.", retry_after=2),
        {"Retry-After": "2"},
    )
    http.enqueue(
        200,
        _success(
            {
                "id": "sess_1",
                "pid": "PID-TEST",
                "clientId": "1",
                "status": "pending",
                "expiresAt": "2026-05-07T16:35:00.000Z",
                "verifyUrl": "https://api.docksys.xyz/v2/verifications/discord",
                "reusedExisting": False,
            }
        ),
    )
    created = await client.create_session("1", 2, idempotency_key="key-1")
    assert created.id == "sess_1"
    assert created.sid == "sess_1"
    assert sleeps == [2.0]
    assert http.calls[0]["headers"]["Idempotency-Key"] == "key-1"
    assert http.calls[1]["headers"]["Idempotency-Key"] == "key-1"


@pytest.mark.asyncio
async def test_bulk_lookup(client: DockClient, http: FakeSession) -> None:
    http.enqueue(
        200,
        _success(
            {
                "results": [
                    {
                        "input": {"discordId": "10"},
                        "found": True,
                        "data": {"discordId": "10", "robloxId": "100"},
                        "error": None,
                    },
                    {
                        "input": {"discordId": "11"},
                        "found": False,
                        "data": None,
                        "error": {
                            "code": "LINK_NOT_FOUND",
                            "message": "missing",
                            "details": None,
                            "status": 404,
                        },
                    },
                ],
                "count": 2,
                "foundCount": 1,
                "notFoundCount": 1,
                "errorCount": 0,
                "resolved": False,
            }
        ),
    )
    result = await client.linked_roblox_bulk([10, 11], 99)
    assert result == {10: "100", 11: None}
    assert http.calls[0]["method"] == "POST"
    assert http.calls[0]["url"].endswith("/v2/discord/bulk")


@pytest.mark.asyncio
async def test_roblox_lookup(client: DockClient, http: FakeSession) -> None:
    http.enqueue(
        200,
        _success(
            {
                "robloxId": "156319135",
                "discordIds": ["10", "11"],
                "count": 2,
                "resolved": {"roblox": None, "discord": None},
            }
        ),
    )
    http.enqueue(404, _error(404, "LINK_NOT_FOUND", "Not found."))
    assert await client.linked_discord(156319135, 99) == [10, 11]
    assert http.calls[0]["method"] == "GET"
    assert http.calls[0]["url"].endswith("/v2/roblox")
    assert http.calls[0]["params"] == {"robloxId": "156319135", "guildId": "99"}
    assert await client.linked_discord(1, 99) == []


@pytest.mark.asyncio
async def test_session_state_long_poll(client: DockClient, http: FakeSession) -> None:
    http.enqueue(
        200,
        _success(
            {
                "id": "sess_9",
                "pid": "PID-TEST",
                "clientId": "7",
                "status": "completed",
                "expiresAt": "2026-05-07T16:35:00.000Z",
                "verifyUrl": "https://api.docksys.xyz/v2/verifications/discord",
                "createdAt": "2026-05-07T16:30:00.000Z",
                "terminalAt": "2026-05-07T16:31:00.000Z",
                "result": {
                    "discordId": "7",
                    "robloxId": "55",
                    "verifiedAt": "2026-05-07T16:31:00.000Z",
                    "linkChanged": False,
                    "previousRobloxId": None,
                },
            }
        ),
    )
    state = await client.session_state("sess_9")
    assert state.status == "completed"
    assert state.result is not None
    assert state.result.roblox_id == "55"
    assert http.calls[0]["params"] == {"wait": "25"}


@pytest.mark.asyncio
async def test_rate_limit_exhausted(
    client: DockClient, http: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("bot.docksys.client.asyncio.sleep", fake_sleep)
    for _ in range(5):
        http.enqueue(
            429,
            _error(429, "RATE_LIMITED", "Too many requests.", retry_after=1),
            {"Retry-After": "1"},
        )
    with pytest.raises(DockRateLimitError):
        await client.linked_roblox(1, 2)


@pytest.mark.asyncio
async def test_dock_service_start_close() -> None:
    http = FakeSession()
    dock = Dock("test-api-key-value", "PID-TEST", http)  # type: ignore[arg-type]
    await dock.start()
    http.enqueue(
        200,
        _success(
            {
                "discordId": "1",
                "robloxId": "2",
                "resolved": {"roblox": None, "discord": None},
            }
        ),
    )
    assert await dock.linked_roblox(1, 2) == "2"
    await dock.close()


@pytest.mark.skip(
    reason=(
        "Dock docs MCP/OpenAPI have no verification webhook contract "
        "(signatures, endpoint verification, replay protection, or event payloads). "
        "Cannot implement or test without inventing behavior."
    )
)
def test_webhook_signature_and_replay() -> None:
    raise AssertionError("unreachable")
