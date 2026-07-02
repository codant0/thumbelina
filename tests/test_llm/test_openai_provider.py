"""Tests for OpenAIProvider endpoint management methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.llm.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_lists_models():
    provider = OpenAIProvider(api_key="test-key")
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        models = await provider.list_models(base_url="https://api.openai.com/v1")

    assert models == ["gpt-4o", "gpt-3.5-turbo"]
