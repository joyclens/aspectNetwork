from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import unquote, urljoin, urlparse

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


class Sale(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int
    created: datetime
    pending: bool
    agent_id: int
    agent_name: str
    agent_type: str
    item_id: int | None
    item_name: str
    item_type: str
    place_id: int | None = None
    amount: int
    currency: str
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


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


class _Money(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amount: int
    type: str


class _Place(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    place_id: int = Field(alias="placeId")


class _SaleItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int | None = None
    name: str | None = None
    type: str | None = None
    place: _Place | None = None
    currency: _Money | None = None


class _Party(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    type: str
    name: str


class _Txn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: int
    created: datetime
    is_pending: bool = Field(default=False, alias="isPending")
    agent: _Party
    details: _SaleItem | None = None
    currency: _Money | None = None


class _SalesPage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    next_page_cursor: str | None = Field(default=None, alias="nextPageCursor")
    data: list[Any] = Field(default_factory=list)


_MAX_ID = 2**63 - 1


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


def _positive(value: int | None) -> int | None:
    if value is None or not 1 <= value <= _MAX_ID:
        return None
    return value


def normalize_cookie(cookie: str) -> str:
    raw = cookie.strip().strip('"').strip("'")
    if "%" in raw:
        raw = unquote(raw)
    raw = raw.strip()
    if not raw:
        return ""
    if raw.upper().startswith("ROBLOSECURITY="):
        raw = raw.split("=", 1)[1].strip()
    if raw.startswith(".ROBLOSECURITY="):
        return raw
    return f".ROBLOSECURITY={raw}"


def _stable_sale_id(api_id: int, row: dict[str, Any]) -> int | None:
    if 1 <= api_id <= _MAX_ID:
        return api_id
    for key in ("idHash", "purchaseToken"):
        raw = row.get(key)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        digest = hashlib.blake2b(text.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big") % _MAX_ID
        return value or 1
    return None


def _sale(row: Any) -> Sale | None:
    if not isinstance(row, dict):
        return None
    try:
        parsed = _Txn.model_validate(row)
    except ValidationError:
        return None
    sale_id = _stable_sale_id(parsed.id, row)
    if sale_id is None or not 1 <= parsed.agent.id <= _MAX_ID:
        return None
    details = parsed.details
    money = parsed.currency or (details.currency if details else None)
    name = parsed.agent.name.strip()
    if money is None or not name or abs(money.amount) > _MAX_ID:
        return None
    created = parsed.created
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    item_name = (details.name if details and details.name else "Item").strip() or "Item"
    return Sale(
        id=sale_id,
        created=created,
        pending=parsed.is_pending,
        agent_id=parsed.agent.id,
        agent_name=name,
        agent_type=parsed.agent.type,
        item_id=_positive(details.id if details else None),
        item_name=item_name,
        item_type=(details.type if details and details.type else "").strip(),
        place_id=_positive(details.place.place_id if details and details.place else None),
        amount=money.amount,
        currency=money.type,
        raw=row,
    )


def parse_sales(payload: Any) -> tuple[list[Sale], str | None]:
    page = _read(_SalesPage, payload)
    sales = [sale for row in page.data if (sale := _sale(row)) is not None]
    if page.data and not sales:
        raise RobloxError(0)
    cursor = page.next_page_cursor
    return sales, cursor or None


def sale_from_raw(payload: Any) -> Sale | None:
    return _sale(payload)


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
        normalized = normalize_cookie(cookie)
        if len(normalized) < 20 or any(char in normalized for char in "\r\n"):
            raise ValueError("invalid cookie")
        self._cookie = normalized
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
        await self._ensure_csrf()
        payload = await self._request("GET", "https://users.roblox.com/v1/users/authenticated")
        return _read(AuthenticatedUser, payload)

    async def _ensure_csrf(self) -> None:
        if self._csrf is not None:
            return
        session = self._session
        if session is None or session.closed:
            raise RobloxError(0)
        headers = self._auth_headers()
        try:
            async with session.post(
                "https://auth.roblox.com/v2/logout",
                headers=headers,
                allow_redirects=False,
            ) as response:
                token = response.headers.get("x-csrf-token")
                await response.read()
                if response.status == 401:
                    raise RobloxError(401)
                if token:
                    self._csrf = token
        except RobloxError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RobloxError(0) from exc

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Cookie": self._cookie,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if self._csrf is not None:
            headers["X-CSRF-TOKEN"] = self._csrf
        return headers

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

    async def sales(self, *, cursor: str | None = None) -> tuple[list[Sale], str | None]:
        params = {"transactionType": "Sale", "limit": "100", "sortOrder": "Desc"}
        if cursor:
            params["cursor"] = cursor
        payload = await self._request(
            "GET",
            f"https://economy.roblox.com/v2/groups/{self._group_id}/transactions",
            params=params,
        )
        return parse_sales(payload)

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
        if self._csrf is None:
            await self._ensure_csrf()
        headers = self._auth_headers()
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
                        headers = self._auth_headers()
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
