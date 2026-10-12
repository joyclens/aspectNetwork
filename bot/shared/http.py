from __future__ import annotations

import socket

import aiohttp

USER_AGENT = (
    "Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; en-us) "
    "AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8A293 Safari/6531.22.7"
)


def session(*, timeout: float) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        headers={"User-Agent": USER_AGENT},
        connector=aiohttp.TCPConnector(family=socket.AF_INET),
    )
