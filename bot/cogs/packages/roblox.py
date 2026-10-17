from __future__ import annotations

import asyncio
import io
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, ValidationError

from bot.shared.http import session


class GamePassError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None) -> None:
        self.status = status
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


class CreatedPass(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    game_pass_id: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CreatedPass:
        for key in ("gamePassId", "gamePassID", "id"):
            value = payload.get(key)
            if isinstance(value, int) and value > 0:
                return cls(game_pass_id=value)
            if isinstance(value, str) and value.isdigit() and int(value) > 0:
                return cls(game_pass_id=int(value))
        data = payload.get("data")
        if isinstance(data, dict):
            return cls.from_payload(data)
        raise GamePassError(0, "Roblox did not return a game pass id.")


def square_png(data: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as opened:
        rgba = opened.convert("RGBA")
        width, height = rgba.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        cropped = rgba.crop((left, top, left + side, top + side))
        output = io.BytesIO()
        cropped.save(output, format="PNG")
        return output.getvalue()


def reviewer_message(error: GamePassError) -> str:
    if error.status == 400:
        return "Roblox rejected the game pass (validation or moderation)."
    if error.status == 401:
        return "Roblox denied the API key. Check Open Cloud credentials."
    if error.status == 403:
        return "Roblox denied access. Check the Open Cloud API key scopes."
    if error.status == 409:
        return "Roblox reported a conflict creating or updating this game pass."
    if error.status == 415:
        return "Roblox rejected the request body (unsupported media type)."
    if error.status == 429:
        wait = f" Retry after {error.retry_after:.0f}s." if error.retry_after else ""
        return f"Roblox rate-limited the request.{wait}"
    return error.message or f"Roblox request failed ({error.status})."


class GamePassClient:
    def __init__(
        self,
        api_key: str,
        universe_id: int,
        http: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key
        self._universe_id = universe_id
        self._session = http
        self._shared = http is not None

    async def start(self) -> None:
        if self._session is not None and not self._session.closed:
            return
        if self._shared:
            raise GamePassError(0, "Shared HTTP session is closed.")
        self._session = session(timeout=40)

    async def close(self) -> None:
        if self._shared or self._session is None or self._session.closed:
            return
        await self._session.close()

    async def create_pass(self, *, name: str, description: str, price: int) -> int:
        form = aiohttp.FormData(default_to_multipart=True)
        form.add_field("name", name[:50])
        form.add_field("description", description[:1000])
        form.add_field("price", str(price))
        form.add_field("isForSale", "true")
        payload = await self._request(
            "POST",
            f"https://apis.roblox.com/game-passes/v1/universes/{self._universe_id}/game-passes",
            data=form,
        )
        try:
            return CreatedPass.from_payload(payload).game_pass_id
        except (ValidationError, GamePassError) as exc:
            if isinstance(exc, GamePassError):
                raise
            raise GamePassError(0, "Invalid create-pass response.") from exc

    async def upload_icon(
        self,
        game_pass_id: int,
        image: bytes,
        filename: str = "icon.png",
    ) -> None:
        png = await asyncio.to_thread(square_png, image)
        form = aiohttp.FormData()
        form.add_field(
            "request",
            png,
            filename=filename if filename.lower().endswith(".png") else "icon.png",
            content_type="image/png",
        )
        try:
            await self._request(
                "POST",
                "https://apis.roblox.com/legacy-game-internationalization/v1/"
                f"game-passes/{game_pass_id}/icons/language-codes/en-us",
                data=form,
                empty_ok=True,
            )
            return
        except GamePassError as exc:
            if exc.status not in {0, 400, 46}:
                raise
        fallback = aiohttp.FormData()
        fallback.add_field("imageFile", png, filename="icon.png", content_type="image/png")
        await self._request(
            "PATCH",
            f"https://apis.roblox.com/game-passes/v1/universes/{self._universe_id}"
            f"/game-passes/{game_pass_id}",
            data=fallback,
            empty_ok=True,
        )

    async def close_sale(self, game_pass_id: int) -> None:
        form = aiohttp.FormData(default_to_multipart=True)
        form.add_field("isForSale", "false")
        await self._request(
            "PATCH",
            f"https://apis.roblox.com/game-passes/v1/universes/{self._universe_id}"
            f"/game-passes/{game_pass_id}",
            data=form,
            empty_ok=True,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: aiohttp.FormData | None = None,
        params: dict[str, str] | None = None,
        empty_ok: bool = False,
        attempt: int = 0,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host.endswith("roblox.com"):
            raise GamePassError(0, "Blocked non-Roblox URL.")
        if parsed.username or parsed.password:
            raise GamePassError(0, "Blocked credentialed URL.")
        client = self._session
        if client is None or client.closed:
            raise GamePassError(0, "HTTP session is not ready.")
        try:
            async with client.request(
                method,
                url,
                data=data,
                params=params,
                headers={"x-api-key": self._api_key},
                allow_redirects=False,
            ) as response:
                if response.status == 429 and attempt < 3:
                    retry = response.headers.get("Retry-After")
                    delay = (
                        float(retry)
                        if retry and retry.replace(".", "", 1).isdigit()
                        else float(2**attempt)
                    )
                    await asyncio.sleep(delay)
                    return await self._request(
                        method,
                        url,
                        data=data,
                        params=params,
                        empty_ok=empty_ok,
                        attempt=attempt + 1,
                    )
                if response.status == 204 or (empty_ok and response.status < 300):
                    if response.status >= 400:
                        raise GamePassError(response.status, f"status {response.status}")
                    return {}
                body = await _json_or_empty(response)
                if response.status == 429:
                    retry = body.get("retryAfter") or response.headers.get("Retry-After")
                    retry_after: float | None = None
                    if isinstance(retry, int | float):
                        retry_after = float(retry)
                    elif isinstance(retry, str) and retry.replace(".", "", 1).isdigit():
                        retry_after = float(retry)
                    raise GamePassError(429, "Rate limited.", retry_after)
                if response.status >= 400:
                    raise GamePassError(
                        response.status,
                        _error_message(body) or f"status {response.status}",
                    )
                return body
        except TimeoutError as exc:
            if attempt < 2:
                await asyncio.sleep(2**attempt)
                return await self._request(
                    method,
                    url,
                    data=data,
                    params=params,
                    empty_ok=empty_ok,
                    attempt=attempt + 1,
                )
            raise GamePassError(0, "Roblox request timed out.") from exc
        except aiohttp.ClientError as exc:
            raise GamePassError(0, "Roblox request failed.") from exc


async def _json_or_empty(response: aiohttp.ClientResponse) -> dict[str, Any]:
    if response.content_length == 0:
        return {}
    try:
        payload: Any = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_message(body: dict[str, Any]) -> str | None:
    for key in ("message", "error", "title"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, str):
                return message
            if first.get("code") == 46:
                return "Icon upload missing file part (error 46)."
    return None
