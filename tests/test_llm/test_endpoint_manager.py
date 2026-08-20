from __future__ import annotations

import pytest

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.endpoint_manager import (
    EndpointManager,
    LLMEndpoint,
    LLMEndpointUpdate,
    LLMModelConfig,
)


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
        models=[LLMModelConfig(name="gpt-4o"), LLMModelConfig(name="gpt-4o-mini")],
    )
    assert endpoint.provider == "openai"
    assert endpoint.models == [LLMModelConfig(name="gpt-4o"), LLMModelConfig(name="gpt-4o-mini")]
    assert endpoint.active_model is None
    assert endpoint.is_default is False


@pytest.mark.asyncio
async def test_list_endpoints(manager):
    await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=[LLMModelConfig(name="gpt-4o")],
    )
    endpoints = await manager.list_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].name == "OpenAI Default"
    assert endpoints[0].models == [LLMModelConfig(name="gpt-4o")]


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
    assert loaded.models == [LLMModelConfig(name="gpt-3.5-turbo")]


@pytest.mark.asyncio
async def test_create_endpoint_with_per_model_context_window(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=[LLMModelConfig(name="gpt-4o", context_window="128K")],
    )
    assert endpoint.models == [LLMModelConfig(name="gpt-4o", context_window="128K")]
    assert endpoint.models[0].context_window == "128K"
    assert endpoint.models[0].context_window_tokens == 128_000

    # 经 JSON blob 持久化往返。
    loaded = await manager.get_endpoint(endpoint.id)
    assert loaded is not None
    assert loaded.models[0].context_window == "128K"
    assert loaded.models[0].context_window_tokens == 128_000


@pytest.mark.asyncio
async def test_create_endpoint_model_context_window_defaults_to_none(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=[LLMModelConfig(name="gpt-4o")],
    )
    assert endpoint.models[0].context_window is None
    assert endpoint.models[0].context_window_tokens is None


@pytest.mark.asyncio
async def test_create_endpoint_rejects_invalid_context_window(manager):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await manager.create_endpoint(
            provider="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            models=[LLMModelConfig(name="gpt-4o", context_window="12X")],
        )


@pytest.mark.asyncio
async def test_update_endpoint_models_set_and_clear_context_window(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=[LLMModelConfig(name="gpt-4o", context_window="128K")],
    )

    # 未提供 models 字段时保留已存储的模型（及各自窗口）。
    updated = await manager.update_endpoint(endpoint.id, LLMEndpointUpdate(name="Renamed"))
    assert updated is not None
    assert updated.models[0].context_window == "128K"

    # 显式覆盖 models（小写也接受）。
    updated = await manager.update_endpoint(
        endpoint.id,
        LLMEndpointUpdate(models=[LLMModelConfig(name="gpt-4o", context_window="1m")]),
    )
    assert updated is not None
    assert updated.models[0].context_window == "1m"

    # 未提供窗口的模型覆盖后 context_window 为 None。
    updated = await manager.update_endpoint(
        endpoint.id,
        LLMEndpointUpdate(models=[LLMModelConfig(name="gpt-4o")]),
    )
    assert updated is not None
    assert updated.models[0].context_window is None


@pytest.mark.asyncio
async def test_update_endpoint_rejects_invalid_context_window(manager):
    from pydantic import ValidationError

    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        models=[LLMModelConfig(name="gpt-4o")],
    )
    with pytest.raises(ValidationError):
        LLMEndpointUpdate(models=[LLMModelConfig(name="gpt-4o", context_window="bogus!")])
    # 已存储的记录保持不动。
    loaded = await manager.get_endpoint(endpoint.id)
    assert loaded is not None
    assert loaded.models[0].context_window is None


@pytest.mark.asyncio
async def test_legacy_record_without_context_window_loads(manager):
    import json
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()
    raw = {
        "id": "old-1",
        "provider": "openai",
        "name": "Old",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o"],
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
    await manager._repo.set(manager._record_key("old-1"), json.dumps(raw), "llm_endpoints")
    index = await manager._load_index()
    index.append("old-1")
    await manager._save_index(index)

    loaded = await manager.get_endpoint("old-1")
    assert loaded is not None
    assert loaded.models == [LLMModelConfig(name="gpt-4o")]
    assert loaded.models[0].context_window is None


@pytest.mark.asyncio
async def test_legacy_record_with_endpoint_context_window_migrates(manager):
    import json
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()
    raw = {
        "id": "legacy-2",
        "provider": "openai",
        "name": "Legacy",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "context_window": "64K",
        "active_model": "gpt-4o",
        "api_key": "sk-test",
        "api_key_set": True,
        "is_default": True,
        "last_latency_ms": None,
        "last_total_ms": None,
        "is_reachable": None,
        "last_tested_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await manager._repo.set(manager._record_key("legacy-2"), json.dumps(raw), "llm_endpoints")
    index = await manager._load_index()
    index.append("legacy-2")
    await manager._save_index(index)

    loaded = await manager.get_endpoint("legacy-2")
    assert loaded is not None
    assert loaded.models == [
        LLMModelConfig(name="gpt-4o", context_window="64K"),
        LLMModelConfig(name="gpt-4o-mini", context_window="64K"),
    ]
    assert loaded.models[0].context_window_tokens == 64_000
    # 顶层 context_window 字段在迁移后被移除。
    assert "context_window" not in loaded.model_dump()


def test_model_config_multimodal_defaults_false():
    model = LLMModelConfig(name="gpt-4o")
    assert model.multimodal is False
    assert model.context_window is None


def test_has_model_and_get_model():
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        models=[
            LLMModelConfig(name="gpt-4o", context_window="128K"),
            LLMModelConfig(name="gpt-4o-mini", multimodal=True),
        ],
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    assert endpoint.has_model("gpt-4o") is True
    assert endpoint.has_model("claude-3") is False
    mini = endpoint.get_model("gpt-4o-mini")
    assert mini is not None
    assert mini.multimodal is True
    assert endpoint.get_model("missing") is None


def test_resolve_context_window_fallbacks():
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        models=[
            LLMModelConfig(name="gpt-4o", context_window="128K"),
            LLMModelConfig(name="gpt-4o-mini", context_window="32K"),
        ],
        active_model="gpt-4o-mini",
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    assert endpoint.resolve_context_window("gpt-4o") == 128_000
    # 空模型名回落到 active_model。
    assert endpoint.resolve_context_window(None) == 32_000
    # active_model 不在列表时回落到 models[0]。
    endpoint.active_model = "missing"
    assert endpoint.resolve_context_window(None) == 128_000
    # 模型未配置窗口时返回 None（由调用方回落全局默认）。
    endpoint.models = [LLMModelConfig(name="gpt-4o")]
    assert endpoint.resolve_context_window("gpt-4o") is None
    # 空端点返回 None。
    endpoint.models = []
    assert endpoint.resolve_context_window(None) is None
