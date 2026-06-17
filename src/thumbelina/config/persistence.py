"""Configuration persistence — write AppConfig back to YAML."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from thumbelina.config.models import AppConfig

logger = logging.getLogger(__name__)

# Fields that contain secrets and must never be written to disk.
_SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "secret_key",
        "app_secret",
        "bot_token",
        "webhook_secret",
    }
)


def _build_dict(config: AppConfig) -> dict[str, Any]:
    """Convert AppConfig to a plain dict, excluding sensitive fields."""
    data = config.model_dump(exclude_none=True)

    # Walk nested dicts and remove sensitive keys
    _strip_secrets(data)
    return data


def _strip_secrets(obj: Any) -> None:
    """Recursively blank out sensitive keys in a nested dict in-place."""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if key in _SENSITIVE_FIELDS:
                obj[key] = ""
            else:
                _strip_secrets(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            _strip_secrets(item)


def save_config(config: AppConfig, config_path: str) -> None:
    """Serialize *config* to YAML and write it to *config_path*.

    Sensitive fields (api_key, app_secret, etc.) are written as empty
    strings so that environment-variable overrides remain the primary
    source at next startup.
    """
    data = _build_dict(config)

    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Configuration saved to %s", config_path)
