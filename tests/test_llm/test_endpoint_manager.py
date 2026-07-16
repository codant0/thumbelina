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
async def test_create_endpoint_with_models(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o", "gpt-4o-mini"],
    )
    assert endpoint.provider == "openai"
    assert endpoint.models == ["gpt-4o", "gpt-4o-mini"]
    assert endpoint.active_model is None
    assert endpoint.is_default is False


@pytest.mark.asyncio
async def test_list_endpoints(manager):
    await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o"],
    )
    endpoints = await manager.list_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].name == "OpenAI Default"
    assert endpoints[0].models == ["gpt-4o"]


@pytest.mark.asyncio
async def test_activate_model_is_globally_unique(manager):
    first = await manager.create_endpoint(
        provider="openai",
        name="First",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o", "gpt-4o-mini"],
        is_default=True,
    )
    # Creating with is_default activates the first model on that endpoint.
    assert first.is_default is True
    assert first.active_model == "gpt-4o"

    second = await manager.create_endpoint(
        provider="anthropic",
        name="Second",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        models=["claude-3", "claude-3-haiku"],
        is_default=True,
    )
    # Activating the second endpoint clears the first across providers.
    assert second.is_default is True
    assert second.active_model == "claude-3"
    refreshed_first = await manager.get_endpoint(first.id)
    assert refreshed_first.is_default is False
    assert refreshed_first.active_model is None

    # Explicit activation of a specific model also clears others.
    await manager.activate_model(first.id, "gpt-4o-mini")
    refreshed_second = await manager.get_endpoint(second.id)
    assert refreshed_second.is_default is False
    assert refreshed_second.active_model is None
    refreshed_first = await manager.get_endpoint(first.id)
    assert refreshed_first.is_default is True
    assert refreshed_first.active_model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_activate_model_rejects_unknown_model(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o"],
    )
    with pytest.raises(ValueError):
        await manager.activate_model(endpoint.id, "not-a-model")


@pytest.mark.asyncio
async def test_get_active_endpoint_model(manager):
    await manager.create_endpoint(
        provider="openai",
        name="Not default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o"],
    )
    default = await manager.create_endpoint(
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o", "gpt-4o-mini"],
        is_default=True,
    )
    active = await manager.get_active_endpoint_model()
    assert active is not None
    assert active[0].id == default.id
    assert active[1] == "gpt-4o"


@pytest.mark.asyncio
async def test_get_active_endpoint_model_none_when_unset(manager):
    await manager.create_endpoint(
        provider="openai",
        name="Not default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=["gpt-4o"],
    )
    assert await manager.get_active_endpoint_model() is None


@pytest.mark.asyncio
async def test_legacy_single_model_record_migrates_on_read(manager):
    # Persist a legacy record with the old single `model` field and no `models`.
    import json
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()
    raw = {
        "id": "legacy-1",
        "provider": "openai",
        "name": "Legacy",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-3.5-turbo",
        "api_key": "sk-test",
        "api_key_set": True,
        "is_default": False,
        "last_latency_ms": None,
        "last_total_ms": None,
        "is_reachable": None,
        "last_tested_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await manager._repo.set(manager._record_key("legacy-1"), json.dumps(raw), "llm_endpoints")
    index = await manager._load_index()
    index.append("legacy-1")
    await manager._save_index(index)

    loaded = await manager.get_endpoint("legacy-1")
    assert loaded is not None
    assert loaded.models == ["gpt-3.5-turbo"]
