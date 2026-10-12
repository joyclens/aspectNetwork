from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar
from urllib.parse import urljoin, urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bot.shared.http import session


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


class _RobloxName(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str


class _Headshot(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    state: str
    image_url: str | None = Field(default=None, alias="imageUrl")


class _Headshots(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[_Headshot] = Field(default_factory=list)


_NAME = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _roblox_name(name: str) -> bool:
    return 3 <= len(name) <= 20 and all(char in _NAME for char in name)


def _image_allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and (host == "rbxcdn.com" or host.endswith(".rbxcdn.com"))
    )


def _image_bytes(body: bytes) -> bytes:
    if not body or len(body) > 256 * 1024:
        raise RobloxError(0)
    if not body.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")):
        raise RobloxError(0)
    return body


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
    def __init__(
        self,
        cookie: str,
        group_id: int,
        http: aiohttp.ClientSession | None = None,
    ) -> None:
        if group_id < 1:
            raise ValueError("invalid group")
        self._cookie = cookie
        self._group_id = group_id
        self._csrf: str | None = None
        self._session = http
        self._shared = http is not None

    def __repr__(self) -> str:
        return "Roblox()"

    async def start(self) -> None:
        if self._session is not None and not self._session.closed:
            return
        if self._shared:
            raise RobloxError(0)
        self._session = session(timeout=20)

    async def close(self) -> None:
        if self._shared or self._session is None or self._session.closed:
            return
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

    async def account(self, user_id: int) -> tuple[str, bytes]:
        if user_id < 1:
            raise RobloxError(0)
        profile, thumbs = await asyncio.gather(
            self._request("GET", f"https://users.roblox.com/v1/users/{user_id}"),
            self._request(
                "GET",
                "https://thumbnails.roblox.com/v1/users/avatar-headshot",
                params={
                    "userIds": str(user_id),
                    "size": "150x150",
                    "format": "Png",
                    "isCircular": "false",
                },
            ),
        )
        name = _read(_RobloxName, profile).name
        if not _roblox_name(name):
            raise RobloxError(0)
        page = _read(_Headshots, thumbs)
        shot = page.data[0] if page.data else None
        if shot is None or shot.state != "Completed" or not shot.image_url:
            raise RobloxError(0)
        return name, await self._image(shot.image_url)

    async def _image(self, url: str) -> bytes:
        session = self._session
        if session is None or session.closed:
            raise RobloxError(0)
        current = url
        for _ in range(2):
            if not _image_allowed(current):
                raise RobloxError(0)
            try:
                async with session.get(current, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        await response.read()
                        if not location:
                            raise RobloxError(response.status)
                        current = urljoin(current, location)
                        continue
                    if response.status >= 300:
                        await response.read()
                        raise RobloxError(response.status)
                    return _image_bytes(await response.read())
            except RobloxError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                raise RobloxError(0) from exc
        raise RobloxError(0)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
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
                    params=params,
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
