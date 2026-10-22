from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import ValidationError

from bot.docksys.errors import (
    DockAuthError,
    DockConflictError,
    DockError,
    DockNotFoundError,
    DockRateLimitError,
    DockUnavailableError,
)
from bot.docksys.models import (
    BulkLookupResponse,
    DiscordLookup,
    SessionCreated,
    SessionState,
    V2ErrorEnvelope,
    V2SuccessEnvelope,
)

logger = logging.getLogger("aspect")

BASE_URL = "https://api.docksys.xyz"
HOST = "api.docksys.xyz"
MAX_RETRIES = 5
DEFAULT_WAIT = 25
BULK_LIMIT = 50
REQUEST_TIMEOUT = 40.0
LONG_POLL_TIMEOUT = 45.0


class DockClient:
    def __init__(
        self,
        api_key: str,
        pid: str,
        http: aiohttp.ClientSession,
    ) -> None:
        self._api_key = api_key
        self._pid = pid
        self._http = http

    def __repr__(self) -> str:
        return "DockClient()"

    async def linked_roblox(self, discord_id: int, guild_id: int) -> str | None:
        if discord_id < 1 or guild_id < 1:
            raise DockError(0, message="invalid discord or guild id")
        try:
            data = await self._data(
                "GET",
                "/v2/discord",
                params={
                    "discordId": str(discord_id),
                    "guildId": str(guild_id),
                },
            )
        except DockNotFoundError:
            return None
        try:
            lookup = DiscordLookup.model_validate(data)
        except ValidationError as exc:
            raise DockError(0, message="invalid discord lookup payload") from exc
        roblox_id = lookup.roblox_id
        if not roblox_id.isdigit() or int(roblox_id) < 1:
            return None
        return str(int(roblox_id))

    async def linked_roblox_bulk(
        self,
        discord_ids: list[int],
        guild_id: int,
    ) -> dict[int, str | None]:
        if guild_id < 1:
            raise DockError(0, message="invalid guild id")
        ordered = [discord_id for discord_id in discord_ids if discord_id > 0]
        out: dict[int, str | None] = {discord_id: None for discord_id in ordered}
        for start in range(0, len(ordered), BULK_LIMIT):
            chunk = ordered[start : start + BULK_LIMIT]
            data = await self._data(
                "POST",
                "/v2/discord/bulk",
                json_body={
                    "discordIds": [str(discord_id) for discord_id in chunk],
                    "guildId": str(guild_id),
                    "resolved": False,
                },
            )
            try:
                payload = BulkLookupResponse.model_validate(data)
            except ValidationError as exc:
                raise DockError(0, message="invalid bulk lookup payload") from exc
            for item in payload.results:
                raw = item.input.get("discordId") or item.input.get("discord_id")
                if not isinstance(raw, str) or not raw.isdigit():
                    continue
                discord_id = int(raw)
                if not item.found or item.data is None:
                    out[discord_id] = None
                    continue
                roblox = item.data.get("robloxId")
                if isinstance(roblox, int) and roblox > 0:
                    out[discord_id] = str(roblox)
                elif isinstance(roblox, str) and roblox.isdigit() and int(roblox) > 0:
                    out[discord_id] = str(int(roblox))
                else:
                    out[discord_id] = None
        return out

    async def create_session(
        self,
        client_id: str,
        guild_id: int,
        *,
        idempotency_key: str | None = None,
    ) -> SessionCreated:
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            if len(idempotency_key) > 256:
                raise DockError(0, message="idempotency key too long")
            headers["Idempotency-Key"] = idempotency_key
        data = await self._data(
            "POST",
            "/v2/sessions",
            json_body={
                "pid": self._pid,
                "clientId": client_id,
                "guildId": str(guild_id),
            },
            headers=headers,
            retry_idempotent=True,
        )
        try:
            return SessionCreated.model_validate(data)
        except ValidationError as exc:
            raise DockError(0, message="invalid session create payload") from exc

    async def session_state(self, session_id: str, wait: int = DEFAULT_WAIT) -> SessionState:
        if not session_id or any(char in session_id for char in " \r\n/"):
            raise DockError(0, message="invalid session id")
        wait = max(0, min(wait, DEFAULT_WAIT))
        data = await self._data(
            "GET",
            f"/v2/sessions/{session_id}",
            params={"wait": str(wait)},
            total=LONG_POLL_TIMEOUT if wait else REQUEST_TIMEOUT,
        )
        try:
            return SessionState.model_validate(data)
        except ValidationError as exc:
            raise DockError(0, message="invalid session status payload") from exc

    async def _data(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        total: float = REQUEST_TIMEOUT,
        retry_idempotent: bool = False,
    ) -> Any:
        envelope = await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            total=total,
            retry_idempotent=retry_idempotent,
        )
        return envelope.data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        total: float = REQUEST_TIMEOUT,
        retry_idempotent: bool = False,
    ) -> V2SuccessEnvelope:
        url = f"{BASE_URL}{path}"
        self._assert_url(url)
        if self._http.closed:
            raise DockError(0, message="http session closed")
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(headers),
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=total),
                ) as response:
                    if response.status == 304:
                        raise DockError(304, message="not modified")
                    body = await self._json(response)
                    if response.status < 400:
                        try:
                            return V2SuccessEnvelope.model_validate(body)
                        except ValidationError as exc:
                            raise DockError(
                                response.status,
                                message="invalid success envelope",
                            ) from exc
                    error = self._map_error(response, body)
            except DockError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt >= MAX_RETRIES:
                    raise DockUnavailableError(0, message="transport failure") from exc
                await asyncio.sleep(min(2**attempt, 8))
                continue
            if self._should_retry(error, attempt, retry_idempotent):
                delay = error.retry_after if error.retry_after is not None else 1.0
                await asyncio.sleep(max(delay, 0.0))
                continue
            raise error

    def _headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        request_headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        return request_headers

    def _should_retry(
        self,
        error: DockError,
        attempt: int,
        retry_idempotent: bool,
    ) -> bool:
        if attempt >= MAX_RETRIES:
            return False
        if isinstance(error, DockRateLimitError):
            return True
        if (
            retry_idempotent
            and isinstance(error, DockUnavailableError)
            and error.code == "IDEMPOTENCY_IN_PROGRESS"
        ):
            return True
        return False

    def _map_error(
        self,
        response: aiohttp.ClientResponse,
        body: dict[str, Any],
    ) -> DockError:
        code: str | None = None
        message: str | None = None
        request_id: str | None = None
        retry_after = self._retry_after(response, body)
        try:
            envelope = V2ErrorEnvelope.model_validate(body)
        except ValidationError:
            message = self._legacy_message(body)
        else:
            code = envelope.error.code
            message = envelope.error.message
            request_id = envelope.meta.request_id
            if retry_after is None and envelope.meta.rate_limit.retry_after is not None:
                retry_after = float(envelope.meta.rate_limit.retry_after)
        logger.warning(
            "Dock API error status=%s code=%s request_id=%s",
            response.status,
            code,
            request_id,
        )
        kwargs: dict[str, Any] = {
            "code": code,
            "message": message,
            "request_id": request_id,
            "retry_after": retry_after,
        }
        if response.status == 401:
            return DockAuthError(response.status, **kwargs)
        if response.status == 404:
            return DockNotFoundError(response.status, **kwargs)
        if response.status == 409:
            return DockConflictError(response.status, **kwargs)
        if response.status == 429:
            return DockRateLimitError(response.status, **kwargs)
        if response.status == 503:
            return DockUnavailableError(response.status, **kwargs)
        return DockError(response.status, **kwargs)

    @staticmethod
    def _retry_after(
        response: aiohttp.ClientResponse,
        body: dict[str, Any],
    ) -> float | None:
        header = response.headers.get("Retry-After")
        if header is not None:
            try:
                return float(header)
            except ValueError:
                pass
        meta = body.get("meta")
        if isinstance(meta, dict):
            rate = meta.get("rateLimit")
            if isinstance(rate, dict):
                value = rate.get("retryAfter")
                if isinstance(value, int | float):
                    return float(value)
        return None

    @staticmethod
    def _legacy_message(body: dict[str, Any]) -> str | None:
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return None

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload: Any = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError) as exc:
            raise DockError(response.status or 0, message="invalid json") from exc
        if isinstance(payload, dict):
            return payload
        raise DockError(response.status or 0, message="non-object json")

    @staticmethod
    def _assert_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != HOST:
            raise DockError(0, message="refusing non-dock host")
        if parsed.username or parsed.password:
            raise DockError(0, message="refusing credentialed url")
