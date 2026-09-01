"""Configuration loader with YAML file and environment variable support."""

from __future__ import annotations

import json
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

        # 兼容旧名：存储模块由 memory 更名为 repository。改名前的 memory 配置
        # 只有 database_url 一个字段，故仅该键重定向；其余 THUMBELINA_MEMORY__*
        # 归属新的 Markdown 分层记忆子系统（MemoryConfig.directory 等）。
        if parts[0] == "memory" and len(parts) == 2 and parts[1] == "database_url":
            logger.warning(
                "Legacy env var %s detected — mapping THUMBELINA_MEMORY__DATABASE_URL "
                "to repository",
                key,
            )
            parts[0] = "repository"

        # Build nested dict
        current = overrides
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    return overrides


def _rewrite_yaml_top_level_key(path: str, old_key: str, new_key: str) -> None:
    """原地重命名 YAML 顶层键，保留格式与注释。

    只匹配列首（第 0 列）的键，因此同名的嵌套键不会被误改。
    """
    content = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(old_key)}(?=\s*:)", re.MULTILINE)
    updated, count = pattern.subn(new_key, content, count=1)
    if count:
        Path(path).write_text(updated, encoding="utf-8")


def _migrate_memory_config(config: dict[str, Any], config_path: str | None) -> dict[str, Any]:
    """把旧版顶层 ``memory`` 配置迁移为 ``repository``。

    顶层 ``memory`` 键是历史遗留：存储模块更名前的数据库配置只有
    ``database_url`` 一个字段。之后引入的 Markdown 分层记忆子系统也复用了
    顶层 ``memory`` 键（含 ``directory``/``categories`` 等字段），故只有
    ``memory`` 块携带 ``database_url`` 时才认定为遗留配置并迁移，其余保留。
    """
    if "memory" not in config:
        return config

    memory_block = config["memory"]
    if not isinstance(memory_block, dict) or "database_url" not in memory_block:
        return config

    if "repository" in config:
        logger.warning(
            "Config contains both 'memory' (legacy) and 'repository'; "
            "ignoring the legacy 'memory' block"
        )
        return config

    config["repository"] = config.pop("memory")
    logger.warning("Migrated legacy 'memory' config block to 'repository'")
    if config_path is not None:
        try:
            _rewrite_yaml_top_level_key(config_path, "memory", "repository")
        except OSError as exc:
            logger.warning(
                "Migrated 'memory' in memory but failed to rewrite %s: %s",
                config_path,
                exc,
            )
    return config


def _resolve_api_key(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve API key from environment if not set in config."""
    llm = config.get("llm", {})
    api_key = llm.get("api_key", "")

    if not api_key:
        # Check standard environment variables
        provider = llm.get("provider", "openai")
        if provider in ("openai", "openai-responses"):
            api_key = os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            config.setdefault("llm", {})["api_key"] = api_key

    return config


def _discover_config_file() -> str | None:
    """Auto-discover thumbelina.yaml in the current working directory."""
    candidate = Path("thumbelina.yaml")
    return str(candidate) if candidate.exists() else None


def resolve_config_path(config_path: str | None = None) -> str | None:
    """Return the resolved config file path.

    If *config_path* is ``None``, attempts auto-discovery of
    ``thumbelina.yaml`` in the current working directory.
    """
    if config_path is None:
        return _discover_config_file()
    return config_path


def load_config(config_path: str | None = None) -> AppConfig:
    """Load configuration from file and environment variables.

    Priority order (highest to lowest):
    1. Environment variables (THUMBELINA_*)
    2. Configuration file (YAML)
    3. Default values

    Parameters
    config_path:
        Path to a YAML configuration file. If None, auto-discovers
        ``thumbelina.yaml`` in the current working directory.

    Returns
    -------
    AppConfig
        The loaded and validated configuration.
    """
    # Auto-discover config file if not explicitly provided
    if config_path is None:
        config_path = _discover_config_file()

    # Start with defaults
    config = DEFAULT_CONFIG.copy()

    # Load and merge YAML file if provided
    if config_path is not None:
        file_config = _load_yaml_file(config_path)
        file_config = _process_env_vars(file_config)
        # 迁移旧名 memory 配置（yaml 文件）到 repository，并写回文件
        file_config = _migrate_memory_config(file_config, config_path)
        config = _deep_merge(config, file_config)

    # Apply environment variable overrides
    env_config = _env_overrides()
    if env_config:
        config = _deep_merge(config, env_config)

    # Resolve API keys from environment
    config = _resolve_api_key(config)

    return AppConfig.model_validate(config)


def load_config_from_db(db_url: str, base_config: AppConfig | None = None) -> AppConfig:
    """Load configuration with database overrides.

    This is a synchronous version for CLI usage. It loads the base config
    from YAML/env, then applies overrides from the database.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL.
    base_config:
        Optional base config to apply overrides to. If None, loads from
        YAML/env as usual.

    Returns
    -------
    AppConfig
        Configuration with database overrides applied.
    """
    if base_config is None:
        base_config = load_config()

    try:
        from thumbelina.config.config_repo import ConfigRepository

        repo = ConfigRepository(db_url)
        db_config = _load_db_config_sync(repo)
        repo.close()

        if not db_config:
            return base_config

        # Apply overrides to base config
        config_dict = base_config.model_dump()
        config_dict = _deep_merge(config_dict, db_config)

        return AppConfig.model_validate(config_dict)
    except Exception:
        logger.warning("Failed to load config from database", exc_info=True)
        return base_config


def _load_db_config_sync(repo: Any) -> dict[str, Any]:
    """Synchronously load config from database and convert to nested dict."""
    from thumbelina.repository.models import SystemConfig

    with repo.SessionLocal() as session:
        from sqlalchemy import select

        stmt = select(SystemConfig)
        records = session.execute(stmt).scalars().all()

        if not records:
            return {}

        # Convert flat key-value pairs to nested dict
        result: dict[str, Any] = {}
        for record in records:
            parts = record.key.split(".")
            current = result
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            try:
                current[parts[-1]] = json.loads(record.value)
            except (json.JSONDecodeError, TypeError):
                current[parts[-1]] = record.value

        return result


def import_yaml_to_db(config_path: str | None, db_url: str) -> int:
    """Import configuration from YAML file to database.

    This is used for first-time setup to populate the database with
    initial configuration values.

    Parameters
    ----------
    config_path:
        Path to YAML config file. If None, auto-discovers thumbelina.yaml.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    int
        Number of config keys imported.
    """
    from thumbelina.config.config_repo import ConfigRepository

    config_path = resolve_config_path(config_path)
    if config_path is None:
        logger.debug("No YAML config file found — skipping import")
        return 0

    # Load YAML config
    try:
        file_config = _load_yaml_file(config_path)
    except FileNotFoundError:
        logger.debug("Config file not found: %s — skipping import", config_path)
        return 0
    file_config = _process_env_vars(file_config)

    # Import to database
    repo = ConfigRepository(db_url)
    try:
        count = 0
        for category, category_data in file_config.items():
            if isinstance(category_data, dict):
                count += _import_dict_to_db(repo, category_data, category, category)
            else:
                # Top-level scalar value (shouldn't happen in normal configs)
                pass

        logger.info("Imported %d config keys from %s to database", count, config_path)
        return count
    finally:
        repo.close()


def _import_dict_to_db(repo: Any, data: dict[str, Any], category: str, prefix: str = "") -> int:
    """Recursively import a config dict to the database."""
    from thumbelina.config.config_repo import _is_sensitive

    count = 0
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            count += _import_dict_to_db(repo, value, category, full_key)
        else:
            if not _is_sensitive(full_key):
                repo._set_sync(full_key, json.dumps(value), category)
                count += 1

    return count
