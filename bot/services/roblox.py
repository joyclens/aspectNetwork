from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RobloxError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"roblox status {status}")


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: int
    name: str
    display_name: str = Field(alias="displayName")


class GroupCurrency(BaseModel):
    model_config = ConfigDict(extra="ignore")
    robux: int


class RevenueSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    pending_robux: int = Field(default=0, alias="pendingRobux")


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and (host == "roblox.com" or host.endswith(".roblox.com"))
    )


T = TypeVar("T", bound=BaseModel)


def _read(model: type[T], payload: Any) -> T:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise RobloxError(0) from exc


class Roblox:
    def __init__(self, cookie: str, group_id: int) -> None:
        if group_id < 1:
            raise ValueError("invalid group")
        self._cookie = cookie
        self._group_id = group_id
        self._csrf: str | None = None
        self._session: aiohttp.ClientSession | None = None

    def __repr__(self) -> str:
        return "Roblox()"

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"User-Agent": "Aspect/0.1"},
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def authenticated(self) -> AuthenticatedUser:
        payload = await self._request("GET", "https://users.roblox.com/v1/users/authenticated")
        return _read(AuthenticatedUser, payload)

    async def balance(self) -> tuple[int, int]:
        group = self._group_id
        currency, summary = await asyncio.gather(
            self._request("GET", f"https://economy.roblox.com/v1/groups/{group}/currency"),
            self._request(
                "GET",
                f"https://economy.roblox.com/v1/groups/{group}/revenue/summary/Year",
            ),
        )
        return _read(GroupCurrency, currency).robux, _read(RevenueSummary, summary).pending_robux

    async def _request(self, method: str, url: str) -> Any:
        if not _allowed(url):
            raise RobloxError(0)
        session = self._session
        if session is None or session.closed:
            raise RobloxError(0)
        headers = {"Cookie": f".ROBLOSECURITY={self._cookie}"}
        if self._csrf is not None:
            headers["X-CSRF-TOKEN"] = self._csrf
        for attempt in range(3):
            try:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    token = response.headers.get("x-csrf-token")
                    if response.status == 403 and token and attempt == 0:
                        self._csrf = token
                        headers["X-CSRF-TOKEN"] = token
                        await response.read()
                        continue
                    if response.status == 429 and attempt < 2:
                        await response.read()
                        await asyncio.sleep(_retry_after(response.headers.get("Retry-After")))
                        continue
                    if response.status >= 300:
                        await response.read()
                        raise RobloxError(response.status)
                    if response.status == 204:
                        return None
                    try:
                        return await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
                        raise RobloxError(response.status) from exc
            except RobloxError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                raise RobloxError(0) from exc
        raise RobloxError(429)


def _retry_after(header: str | None) -> float:
    try:
        return min(max(float(header or 1), 0.0), 30.0)
    except ValueError:
        return 1.0
