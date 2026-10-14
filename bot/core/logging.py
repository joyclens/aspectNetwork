from __future__ import annotations

import logging
from collections.abc import Sequence
from urllib.parse import unquote, urlparse

from bot.core.config import Settings

_MIN_SECRET = 8


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: Sequence[str]) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._secrets = [secret for secret in secrets if len(secret) >= _MIN_SECRET]

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for secret in self._secrets:
            rendered = rendered.replace(secret, "[redacted]")
        return rendered


def secret_values(settings: Settings) -> list[str]:
    values = [
        settings.discord_token.get_secret_value(),
        settings.roblox_cookie.get_secret_value(),
        settings.postgres_dsn.get_secret_value(),
    ]
    if settings.dock_api_key is not None:
        values.append(settings.dock_api_key.get_secret_value())
    if settings.cookie_api_key is not None:
        values.append(settings.cookie_api_key.get_secret_value())
    if settings.roblox_api_key is not None:
        values.append(settings.roblox_api_key.get_secret_value())
    password = unquote(urlparse(settings.postgres_dsn.get_secret_value()).password or "")
    if password:
        values.append(password)
    return values


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(secret_values(settings)))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
