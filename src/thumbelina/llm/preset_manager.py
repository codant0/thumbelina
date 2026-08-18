"""Manager for LLM provider presets."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.factory import create_provider
from thumbelina.llm.preset_models import (
    LLMPreset,
    LLMPresetActivateResponse,
    LLMPresetCreate,
    LLMPresetResponse,
    LLMPresetUpdate,
)

if TYPE_CHECKING:
    from thumbelina.agent.graph import ThumbelinaAgent
    from thumbelina.config.runtime_manager import RuntimeConfigManager

logger = logging.getLogger(__name__)

_INDEX_KEY = "llm_presets.index"
_ACTIVE_KEY = "llm_presets.active_id"


def _to_response(preset: LLMPreset) -> LLMPresetResponse:
    return LLMPresetResponse(
        id=preset.id,
        name=preset.name,
        provider=preset.provider,
        base_url=preset.base_url,
        api_key_set=preset.api_key_set,
        model=preset.model,
        extra_params=preset.extra_params,
        is_active=preset.is_active,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


class PresetManager:
    """CRUD + activation manager for LLM provider presets.

    Presets are persisted as JSON in the configured ``ConfigRepository``.
    """

    def __init__(
        self,
        config_repo: ConfigRepository,
        runtime_manager: RuntimeConfigManager | None = None,
        agent: ThumbelinaAgent | None = None,
        *,
        skill_engine: Any | None = None,
        composition_engine: Any | None = None,
        subagent_manager: Any | None = None,
        memory_extractor: Any | None = None,
    ) -> None:
        self._repo = config_repo
        self._runtime_manager = runtime_manager
        self._agent = agent
        self._skill_engine = skill_engine
        self._composition_engine = composition_engine
        self._subagent_manager = subagent_manager
        self._memory_extractor = memory_extractor

    async def _load_index(self) -> list[str]:
        raw = await self._repo.get(_INDEX_KEY)
        if raw is None:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    async def _save_index(self, index: list[str]) -> None:
        await self._repo.set(_INDEX_KEY, json.dumps(index), "llm_presets")

    def _record_key(self, preset_id: str) -> str:
        return f"llm_presets.{preset_id}"

    async def _get_raw(self, preset_id: str) -> LLMPreset | None:
        raw = await self._repo.get(self._record_key(preset_id))
        if raw is None:
            return None
        return LLMPreset.model_validate_json(raw)

    async def _persist(self, preset: LLMPreset) -> None:
        await self._repo.set(
            self._record_key(preset.id),
            preset.model_dump_json(),
            "llm_presets",
        )

    async def list_presets(self) -> list[LLMPresetResponse]:
        """Return all presets."""
        presets: list[LLMPreset] = []
        for preset_id in await self._load_index():
            preset = await self._get_raw(preset_id)
            if preset is not None:
                presets.append(preset)
        return [_to_response(p) for p in presets]

    async def get_preset(self, preset_id: str) -> LLMPresetResponse | None:
        """Return a single preset by id."""
        preset = await self._get_raw(preset_id)
        return _to_response(preset) if preset else None

    async def create_preset(self, data: LLMPresetCreate) -> LLMPresetResponse:
        """Create a new preset."""
        now = datetime.now(UTC)
        preset = LLMPreset(
            id=str(uuid.uuid4()),
            name=data.name,
            provider=data.provider,
            base_url=data.base_url.rstrip("/"),
            api_key=data.api_key,
            api_key_set=bool(data.api_key),
            model=data.model,
            extra_params=data.extra_params,
            is_active=False,
            created_at=now,
            updated_at=now,
        )

        await self._persist(preset)
        index = await self._load_index()
        index.append(preset.id)
        await self._save_index(index)

        if data.is_active:
            await self.activate_preset(preset.id)

        return _to_response(preset)

    async def update_preset(
        self,
        preset_id: str,
        data: LLMPresetUpdate,
    ) -> LLMPresetResponse | None:
        """Update an existing preset."""
        preset = await self._get_raw(preset_id)
        if preset is None:
            return None

        if data.name is not None:
            preset.name = data.name
        if data.provider is not None:
            preset.provider = data.provider
        if data.base_url is not None:
            preset.base_url = data.base_url.rstrip("/")
        if data.api_key is not None:
            if data.api_key != "":
                preset.api_key = data.api_key
                preset.api_key_set = True
            # An empty string means "keep the existing key" when updating.
        if data.model is not None:
            preset.model = data.model
        if data.extra_params is not None:
            preset.extra_params = data.extra_params
        if data.is_active is True:
            await self.activate_preset(preset.id)
        elif data.is_active is False:
            preset.is_active = False

        preset.updated_at = datetime.now(UTC)
        await self._persist(preset)

        # If this was the active preset, re-apply it so changes take effect.
        if preset.is_active and self._runtime_manager is not None and self._agent is not None:
            await self.activate_preset(preset.id)

        return _to_response(preset)

    async def delete_preset(self, preset_id: str) -> bool:
        """Delete a preset."""
        preset = await self._get_raw(preset_id)
        if preset is None:
            return False

        await self._repo.delete(self._record_key(preset_id))
        index = await self._load_index()
        if preset_id in index:
            index.remove(preset_id)
            await self._save_index(index)

        if preset.is_active:
            await self._repo.delete(_ACTIVE_KEY)

        return True

    async def activate_preset(self, preset_id: str) -> LLMPresetActivateResponse:
        """Activate a preset and hot-swap the running LLM provider."""
        preset = await self._get_raw(preset_id)
        if preset is None:
            raise ValueError(f"Preset not found: {preset_id}")

        if self._runtime_manager is None or self._agent is None:
            raise RuntimeError("Runtime manager / agent not available")

        # Build provider to validate configuration before switching.
        kwargs: dict[str, Any] = {
            "api_key": preset.api_key,
            "model": preset.model,
        }
        if preset.base_url:
            kwargs["base_url"] = preset.base_url
        kwargs.update(preset.extra_params)
        create_provider(preset.provider, **kwargs)

        await self._runtime_manager.swap_llm_provider(
            new_provider=preset.provider,
            new_model=preset.model,
            new_api_key=preset.api_key,
            new_base_url=preset.base_url or None,
            agent=self._agent,
            skill_engine=self._skill_engine,
            composition_engine=self._composition_engine,
            subagent_manager=self._subagent_manager,
            memory_extractor=self._memory_extractor,
        )

        await self._clear_active_flag()
        preset.is_active = True
        preset.updated_at = datetime.now(UTC)
        await self._persist(preset)
        await self._repo.set(_ACTIVE_KEY, json.dumps(preset.id), "llm_presets")

        return LLMPresetActivateResponse(
            status="ok",
            preset_id=preset.id,
            preset_name=preset.name,
            provider=preset.provider,
            model=preset.model,
        )

    async def get_active_preset(self) -> LLMPresetResponse | None:
        """Return the currently active preset, if any."""
        raw = await self._repo.get(_ACTIVE_KEY)
        if raw is None:
            return None
        try:
            preset_id = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return await self.get_preset(preset_id)

    async def _clear_active_flag(self) -> None:
        """Mark all presets as inactive."""
        for preset_id in await self._load_index():
            preset = await self._get_raw(preset_id)
            if preset is not None and preset.is_active:
                preset.is_active = False
                preset.updated_at = datetime.now(UTC)
                await self._persist(preset)

    async def restore_active_preset(self) -> LLMPresetResponse | None:
        """Re-activate the last active preset on startup."""
        active = await self.get_active_preset()
        if active is None:
            return None
        try:
            await self.activate_preset(active.id)
        except Exception:
            logger.warning("Failed to restore active preset %s", active.id, exc_info=True)
            return None
        return active
