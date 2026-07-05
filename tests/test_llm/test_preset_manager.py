"""Tests for PresetManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.preset_manager import PresetManager
from thumbelina.llm.preset_models import LLMPresetCreate


@pytest.fixture
def config_repo(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    repo = ConfigRepository(db_url=db_url)
    return repo


@pytest.fixture
def preset_manager(config_repo):
    runtime_manager = MagicMock()
    runtime_manager.swap_llm_provider = AsyncMock()
    agent = MagicMock()
    return PresetManager(
        config_repo=config_repo,
        runtime_manager=runtime_manager,
        agent=agent,
    )


@pytest.mark.asyncio
async def test_create_and_list_presets(preset_manager):
    created = await preset_manager.create_preset(
        LLMPresetCreate(
            name="OpenAI Default",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )
    )
    assert created.name == "OpenAI Default"
    assert created.provider == "openai"
    assert created.api_key_set is True
    assert created.model == "gpt-4o"

    presets = await preset_manager.list_presets()
    assert len(presets) == 1
    assert presets[0].id == created.id


@pytest.mark.asyncio
async def test_get_preset_not_found(preset_manager):
    assert await preset_manager.get_preset("missing") is None


@pytest.mark.asyncio
async def test_update_preset(preset_manager):
    created = await preset_manager.create_preset(
        LLMPresetCreate(
            name="Original",
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
    )
    updated = await preset_manager.update_preset(
        created.id,
        LLMPresetCreate(name="Updated", provider="openai", base_url="https://api.openai.com/v1"),
    )
    assert updated is not None
    assert updated.name == "Updated"


@pytest.mark.asyncio
async def test_delete_preset(preset_manager):
    created = await preset_manager.create_preset(
        LLMPresetCreate(
            name="To Delete",
            provider="openai",
            base_url="https://api.openai.com/v1",
        )
    )
    deleted = await preset_manager.delete_preset(created.id)
    assert deleted is True
    assert await preset_manager.get_preset(created.id) is None


@pytest.mark.asyncio
async def test_activate_preset(preset_manager):
    created = await preset_manager.create_preset(
        LLMPresetCreate(
            name="DeepSeek",
            provider="openai",
            base_url="https://api.deepseek.com",
            api_key="sk-test",
            model="deepseek-chat",
        )
    )
    result = await preset_manager.activate_preset(created.id)
    assert result.status == "ok"
    assert result.preset_id == created.id
    assert result.provider == "openai"
    assert preset_manager._runtime_manager.swap_llm_provider.called


@pytest.mark.asyncio
async def test_activate_unknown_preset_raises(preset_manager):
    with pytest.raises(ValueError, match="Preset not found"):
        await preset_manager.activate_preset("missing")
