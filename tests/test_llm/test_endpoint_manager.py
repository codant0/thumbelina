from __future__ import annotations

import pytest

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.endpoint_manager import EndpointManager


@pytest.fixture
def config_repo():
    repo = ConfigRepository("sqlite:///:memory:")
    yield repo
    repo.close()


@pytest.fixture
def manager(config_repo):
    return EndpointManager(config_repo=config_repo)


@pytest.mark.asyncio
async def test_create_endpoint(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    assert endpoint.provider == "openai"
    assert endpoint.name == "OpenAI Default"
    assert endpoint.base_url == "https://api.openai.com/v1"
    assert endpoint.api_key_set is True
    assert endpoint.is_default is False


@pytest.mark.asyncio
async def test_list_endpoints(manager):
    await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    endpoints = await manager.list_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].name == "OpenAI Default"


@pytest.mark.asyncio
async def test_default_endpoint_uniqueness(manager):
    first = await manager.create_endpoint(
        provider="openai",
        name="First",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        is_default=True,
    )
    second = await manager.create_endpoint(
        provider="openai",
        name="Second",
        base_url="https://api.other.com/v1",
        api_key="sk-test",
        is_default=True,
    )
    assert first.is_default is True
    updated_first = await manager.get_endpoint(first.id)
    assert updated_first.is_default is False
    assert second.is_default is True
