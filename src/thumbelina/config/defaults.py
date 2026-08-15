"""Default configuration values for Thumbelina."""

from __future__ import annotations

from thumbelina.config.models import AppConfig

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "repository": {
        "database_url": "sqlite:///thumbelina.db",
    },
    "logging": {
        "level": "INFO",
    },
}


def get_default_config() -> AppConfig:
    """Return an AppConfig instance with default values."""
    return AppConfig.model_validate(DEFAULT_CONFIG)
