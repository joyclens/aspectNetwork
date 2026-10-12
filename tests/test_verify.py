from __future__ import annotations

import logging

import pytest

from bot.events.verification import _emoji_id, _has_id
from bot.shared.errors import remember_error


def test_emoji_mention_id() -> None:
    assert _emoji_id("<:headshot_156:987654321>") == 987654321
    assert _emoji_id("<a:headshot_156:12>") == 12
    assert _emoji_id("headshot") is None


def test_panel_custom_id() -> None:
    class _Child:
        custom_id = "verifyButton"
        children = None

    class _Row:
        custom_id = None
        children = [_Child()]

    assert _has_id([_Row()], "verifyButton")
    assert not _has_id([_Row()], "other")


def test_remember_error_logs_traceback(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    store: dict[str, BaseException] = {}
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        code = remember_error(store, exc, where="Button verifyButton")
    assert code in store
    assert isinstance(store[code], RuntimeError)
    assert code in caplog.text
    assert "RuntimeError: boom" in caplog.text
    assert "Traceback" in caplog.text
