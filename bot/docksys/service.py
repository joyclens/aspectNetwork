from __future__ import annotations

import uuid

import aiohttp

from bot.docksys.client import DockClient
from bot.docksys.models import SessionCreated, SessionState
from bot.shared.http import session

SESSION_WAIT = 25


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
        self._client: DockClient | None = None

    def __repr__(self) -> str:
        return "Dock()"

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            if self._shared:
                raise RuntimeError("shared dock http session is closed")
            self._session = session(timeout=45)
        self._client = DockClient(self._api_key, self._pid, self._session)

    async def close(self) -> None:
        self._client = None
        if self._shared or self._session is None or self._session.closed:
            return
        await self._session.close()

    @property
    def client(self) -> DockClient:
        if self._client is None:
            raise RuntimeError("dock client is not started")
        return self._client

    async def linked_roblox(self, discord_id: int, guild_id: int) -> str | None:
        return await self.client.linked_roblox(discord_id, guild_id)

    async def linked_roblox_bulk(
        self,
        discord_ids: list[int],
        guild_id: int,
    ) -> dict[int, str | None]:
        return await self.client.linked_roblox_bulk(discord_ids, guild_id)

    async def create_session(self, client_id: str, guild_id: int) -> SessionCreated:
        return await self.client.create_session(
            client_id,
            guild_id,
            idempotency_key=str(uuid.uuid4()),
        )

    async def session_state(self, sid: str, wait: int = SESSION_WAIT) -> SessionState:
        return await self.client.session_state(sid, wait=wait)
