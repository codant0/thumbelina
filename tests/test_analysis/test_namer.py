"""Tests for thumbelina.analysis.namer module."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from thumbelina.analysis.namer import ConversationNamer


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self.chat = AsyncMock(return_value=reply)


@pytest.mark.asyncio
async def test_suggest_name_returns_cleaned_title():
    namer = ConversationNamer(_FakeProvider("“Python 调试技巧”。"))
    name = await namer.suggest_name([{"role": "user", "content": "怎么在 Python 里调试？"}])
    assert name == "Python 调试技巧"


@pytest.mark.asyncio
async def test_suggest_name_truncates_long_titles():
    namer = ConversationNamer(_FakeProvider("x" * 200))
    name = await namer.suggest_name([{"role": "user", "content": "hi"}])
    assert len(name) <= 50


@pytest.mark.asyncio
async def test_suggest_name_empty_without_user_messages():
    namer = ConversationNamer(_FakeProvider("should not be called"))
    assert await namer.suggest_name([{"role": "assistant", "content": "hi"}]) == ""


@pytest.mark.asyncio
async def test_suggest_name_returns_empty_on_provider_failure():
    provider = _FakeProvider("ok")
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))
    namer = ConversationNamer(provider)
    assert await namer.suggest_name([{"role": "user", "content": "hi"}]) == ""
