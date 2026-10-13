from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, ValidationError


class CookieError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"cookie status {status}")


class TranscriptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool = False
    url: str = ""


def transcript_url(payload: Any) -> str:
    try:
        parsed = TranscriptResult.model_validate(payload)
    except ValidationError as exc:
        raise CookieError(0) from exc
    if not parsed.success or not parsed.url.startswith("https://"):
        raise CookieError(0)
    host = (urlparse(parsed.url).hostname or "").lower()
    if host != "www.cookie-api.com" and not host.endswith(".cookie-api.com"):
        raise CookieError(0)
    return parsed.url


class Cookie:
    def __init__(
        self,
        api_key: str,
        http: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key
        self._session = http
        self._shared = http is not None

    async def close(self) -> None:
        if self._shared or self._session is None or self._session.closed:
            return
        await self._session.close()

    async def transcript(
        self,
        channel_id: int,
        bot_token: str,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        if channel_id < 1 or not bot_token.strip():
            raise CookieError(0)
        body: dict[str, str] = {"bot_token": bot_token}
        if title:
            body["title"] = title[:256]
        if description:
            body["description"] = description[:1024]
        session = self._session
        if session is None or session.closed:
            raise CookieError(0)
        try:
            async with session.post(
                "https://api.cookie-api.com/api/transcript",
                params={"channel_id": str(channel_id)},
                headers={
                    "Authorization": self._api_key,
                    "Content-Type": "application/json",
                },
                json=body,
                allow_redirects=False,
            ) as response:
                if response.status >= 300:
                    await response.read()
                    raise CookieError(response.status)
                try:
                    payload: Any = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
                    raise CookieError(response.status) from exc
                return transcript_url(payload)
        except CookieError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CookieError(0) from exc
