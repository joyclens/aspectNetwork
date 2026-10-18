from __future__ import annotations

import logging
from typing import Any

from discord.gateway import DiscordWebSocket

logger = logging.getLogger("aspect")

# discord.py 2.7 uses unprefixed keys. Discord classifies VR from this trio:
# os=android + browser/device="Discord VR" (see Discord-VR / current gateway).
_PROPERTIES: dict[str, str] = {
    "os": "android",
    "browser": "Discord VR",
    "device": "Discord VR",
    "$os": "android",
    "$browser": "Discord VR",
    "$device": "oculus",
}


async def identify(self: DiscordWebSocket) -> None:
    payload: dict[str, Any] = {
        "op": self.IDENTIFY,
        "d": {
            "token": self.token,
            "properties": dict(_PROPERTIES),
            "compress": True,
            "large_threshold": 250,
        },
    }

    if self.shard_id is not None and self.shard_count is not None:
        payload["d"]["shard"] = [self.shard_id, self.shard_count]

    state = self._connection
    if state._activity is not None or state._status is not None:
        payload["d"]["presence"] = {
            "status": state._status,
            "game": state._activity,
            "since": 0,
            "afk": False,
        }

    if state._intents is not None:
        payload["d"]["intents"] = state._intents.value

    await self.call_hooks("before_identify", self.shard_id, initial=self._initial_identify)
    await self.send_as_json(payload)
    logger.info("Gateway identify sent as Discord VR")


def apply() -> None:
    DiscordWebSocket.identify = identify  # type: ignore[method-assign]


apply()
