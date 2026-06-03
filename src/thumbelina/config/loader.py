"""Configuration loader with YAML file and environment variable support."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from thumbelina.config.defaults import DEFAULT_CONFIG
from thumbelina.config.models import AppConfig

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR} patterns in a string with environment variable values.

    If the environment variable is not set, the pattern is left as-is.
    """

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is None:
            logger.warning(
                "Environment variable %s is not set — leaving ${%s} as-is",
                var_name,
                var_name,
            )
            return match.group(0)
        return resolved

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _process_env_vars(obj: Any) -> Any:
    """Recursively substitute ${VAR} patterns in a nested dict/list structure."""
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _process_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_process_env_vars(item) for item in obj]
    return obj


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dicts, with override values taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_file(path: str) -> dict[str, Any]:
    """Load and parse a YAML configuration file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        return {}

    data = yaml.safe_load(content)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Configuration file must contain a YAML mapping, got {type(data).__name__}"
        )
    return data


def _env_overrides() -> dict[str, Any]:
    """Build a nested dict from THUMBELINA_* environment variables.

    Uses double-underscore (__) as the nested key separator.
    Example: THUMBELINA_LLM__PROVIDER -> {"llm": {"provider": ...}}
    """
    prefix = "THUMBELINA_"
    overrides: dict[str, Any] = {}

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        # Remove prefix and split on double-underscore
        rest = key[len(prefix) :].lower()
        parts = rest.split("__")

        # Build nested dict
        current = overrides
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    return overrides


def _resolve_api_key(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve API key from environment if not set in config."""
    llm = config.get("llm", {})
    api_key = llm.get("api_key", "")

    if not api_key:
        # Check standard environment variables
        provider = llm.get("provider", "openai")
        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            config.setdefault("llm", {})["api_key"] = api_key

    return config


def load_config(config_path: str | None = None) -> AppConfig:
    """Load configuration from file and environment variables.

    Priority order (highest to lowest):
    1. Environment variables (THUMBELINA_*)
    2. Configuration file (YAML)
    3. Default values

    Parameters
    ----------
    config_path:
        Path to a YAML configuration file. If None, only defaults and
        environment variables are used.

    Returns
    -------
    AppConfig
        The loaded and validated configuration.
    """
    # Start with defaults
    config = DEFAULT_CONFIG.copy()

    # Load and merge YAML file if provided
    if config_path is not None:
        file_config = _load_yaml_file(config_path)
        file_config = _process_env_vars(file_config)
        config = _deep_merge(config, file_config)

    # Apply environment variable overrides
    env_config = _env_overrides()
    if env_config:
        config = _deep_merge(config, env_config)

    # Resolve API keys from environment
    config = _resolve_api_key(config)

    return AppConfig.model_validate(config)
