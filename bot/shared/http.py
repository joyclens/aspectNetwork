from __future__ import annotations

import socket

import aiohttp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def session(*, timeout: float) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        headers={"User-Agent": USER_AGENT},
        connector=aiohttp.TCPConnector(family=socket.AF_INET),
        cookie_jar=aiohttp.DummyCookieJar(),
    )
