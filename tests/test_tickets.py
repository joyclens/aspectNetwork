from __future__ import annotations

import pytest
from discord.ext import commands

from bot.cogs.tickets import channel_slug, ticket_channel_name
from bot.services.cookie import CookieError, transcript_url
from bot.shared.converters import Duration
from bot.shared.errors import DatabaseUnavailable


def test_channel_slug() -> None:
    assert channel_slug("Hello World!") == "hello-world"
    assert channel_slug("$$$") == "ticket"
    assert len(channel_slug("a" * 200)) == 90


def test_ticket_channel_name() -> None:
    assert ticket_channel_name("alice", claimed=False) == "🔴・alice"
    assert ticket_channel_name("alice", claimed=True) == "🟢・alice"
    assert len(ticket_channel_name("a" * 200, claimed=False)) == 100


def test_transcript_url() -> None:
    assert (
        transcript_url(
            {
                "success": True,
                "url": "https://www.cookie-api.com/transcripts/example/test.html",
            }
        )
        == "https://1j7NzkuG6P.joyclen.codes/transcripts/example/test.html"
    )
    with pytest.raises(CookieError):
        transcript_url({"success": False, "url": "https://www.cookie-api.com/x"})
    with pytest.raises(CookieError):
        transcript_url({"success": True, "url": "https://evil.example/x"})


@pytest.mark.asyncio
async def test_duration_converter() -> None:
    converter = Duration()
    assert await converter.convert(None, "12h") == 12 * 60 * 60  # type: ignore[arg-type]
    assert await converter.convert(None, "1d30m") == 24 * 60 * 60 + 30 * 60  # type: ignore[arg-type]
    with pytest.raises(commands.BadArgument):
        await converter.convert(None, "nope")  # type: ignore[arg-type]


def test_database_unavailable() -> None:
    assert isinstance(DatabaseUnavailable(), Exception)
