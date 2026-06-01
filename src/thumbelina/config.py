"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_port(raw: str) -> int:
    """Parse port string with fallback to default 8000."""
    try:
        port = int(raw)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    return 8000


@dataclass
class AppConfig:
    """Central application configuration.

    Values can be supplied directly or loaded from environment variables
    via the ``from_env`` class method.
    """

    app_name: str = "thumbelina"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    db_url: str = "sqlite:///thumbelina.db"
    chroma_dir: str = field(default="chroma_db")
    qdrant_url: str = field(default="http://localhost:6333")

    # LLM
    openai_api_key: str = field(default="")
    anthropic_api_key: str = field(default="")

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build an AppConfig from ``THUMBELINA_*`` environment variables."""
        debug_raw = os.environ.get("THUMBELINA_DEBUG", "false").lower()
        return cls(
            app_name=os.environ.get("THUMBELINA_APP_NAME", "thumbelina"),
            debug=debug_raw in ("true", "1", "yes"),
            host=os.environ.get("THUMBELINA_HOST", "127.0.0.1"),
            port=_parse_port(os.environ.get("THUMBELINA_PORT", "8000")),
            db_url=os.environ.get("THUMBELINA_DB_URL", "sqlite:///thumbelina.db"),
            chroma_dir=os.environ.get("THUMBELINA_CHROMA_DIR", "chroma_db"),
            qdrant_url=os.environ.get("THUMBELINA_QDRANT_URL", "http://localhost:6333"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
