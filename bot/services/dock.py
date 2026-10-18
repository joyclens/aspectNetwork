from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bot.shared.http import session

_SID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class DockError(Exception):
    def __init__(
        self,
        status: int,
        retry_after: float | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        self.status = status
        self.retry_after = retry_after
        self.detail = detail
        suffix = f" {detail}" if detail else ""
        super().__init__(f"dock status {status}{suffix}")


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    sid: str
    verify_url: str = Field(alias="verifyUrl")
    expires_at: datetime = Field(alias="expiresAt")


class SessionResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    discord_id: str | None = Field(default=None, alias="discordId")
    roblox_id: str | None = Field(default=None, alias="robloxId")


class SessionState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str | None = None
    result: SessionResult | None = None


def linked_roblox_id(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    roblox_id = data.get("robloxId")
    if isinstance(roblox_id, bool):
        return None
    if isinstance(roblox_id, int) and roblox_id > 0:
        return str(roblox_id)
    if isinstance(roblox_id, str) and roblox_id.isdigit() and int(roblox_id) > 0:
        return str(int(roblox_id))
    return None


class Dock:
    def __init__(
        self,
        api_key: str,
        pid: str,
        http: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key
        self._pid = pid
        self._session = http
        self._shared = http is not None

    def __repr__(self) -> str:
        return "Dock()"

    async def start(self) -> None:
        if self._session is not None and not self._session.closed:
            return
        if self._shared:
            raise DockError(0)
        self._session = session(timeout=40)

    async def close(self) -> None:
        if self._shared or self._session is None or self._session.closed:
            return
        await self._session.close()

    async def create_session(self, client_id: str, guild_id: int) -> SessionCreated:
        payload = await self._request(
            "POST",
            "https://api.docksys.xyz/api/v1/verify/session",
            json_body={"pid": self._pid, "clientId": client_id, "guildId": str(guild_id)},
        )
        data = payload.get("data")
        try:
            return SessionCreated.model_validate(data)
        except ValidationError as exc:
            raise DockError(0) from exc

    async def linked_roblox(self, discord_id: int, guild_id: int) -> str | None:
        if discord_id < 1 or guild_id < 1:
            raise DockError(0)
        try:
            payload = await self._request(
                "GET",
                "https://api.docksys.xyz/api/v1/public/discord-to-roblox",
                params={"discordId": str(discord_id), "guildId": str(guild_id)},
            )
        except DockError as exc:
            if exc.status == 404:
                return None
            raise
        return linked_roblox_id(payload)

    async def session_state(self, sid: str, wait: int = 25) -> SessionState:
        if not sid or any(char not in _SID_CHARS for char in sid):
            raise DockError(0)
        payload = await self._request(
            "GET",
            f"https://api.docksys.xyz/api/v1/verify/session/{sid}",
            params={"wait": str(wait)},
        )
        data = payload.get("data")
        try:
            return SessionState.model_validate(data)
        except ValidationError as exc:
            raise DockError(0) from exc

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "api.docksys.xyz":
            raise DockError(0)
        if parsed.username or parsed.password:
            raise DockError(0)
        session = self._session
        if session is None or session.closed:
            raise DockError(0)
        try:
            async with session.request(
                method,
                url,
                json=json_body,
                params=params,
                headers={"Authorization": f"Bearer {self._api_key}"},
                allow_redirects=False,
            ) as response:
                body = await _json_or_empty(response)
                if response.status == 429:
                    retry = body.get("retryAfter")
                    delay = float(retry) if isinstance(retry, int | float) else None
                    raise DockError(429, delay, detail=_error_detail(body))
                if response.status >= 400:
                    raise DockError(response.status, detail=_error_detail(body))
                return body
        except aiohttp.ClientError as exc:
            raise DockError(0) from exc
        except TimeoutError as exc:
            raise DockError(0) from exc


def _error_detail(body: dict[str, Any]) -> str | None:
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        parts = [str(part) for part in (code, message) if isinstance(part, str) and part.strip()]
        if parts:
            return ": ".join(parts)
    message = body.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


async def _json_or_empty(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        payload: Any = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError) as exc:
        raise DockError(response.status or 0) from exc
    if isinstance(payload, dict):
        return payload
    raise DockError(response.status or 0)
