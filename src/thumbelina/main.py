"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from thumbelina.api.app import create_app as create_api_app
from thumbelina.config import AppConfig, load_config

logger = logging.getLogger(__name__)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    config:
        Optional application configuration.  When *None* the configuration
        is loaded from environment variables.
    """
    if config is None:
        config = load_config()

    app = create_api_app(config)
    _mount_static_frontend(app)
    return app


def _mount_static_frontend(app: FastAPI) -> None:
    """Serve the built React frontend from the same process (no nginx).

    The frontend uses relative API/WebSocket paths and never changes the URL,
    so ``StaticFiles(html=True)`` at ``/`` is enough — no SPA fallback needed.
    API routes and the WebSocket are registered inside ``create_api_app``
    before this mount, so they still take precedence over the catch-all static
    handler. Skipped when the static dir is missing (e.g. ``thumbelina-serve``
    run locally without a build), leaving a pure API app.
    """
    static_dir = os.environ.get("THUMBELINA_STATIC_DIR", "static")
    static_path = Path(static_dir)
    if not static_path.is_dir():
        logger.warning("Static dir %s not found — serving API only", static_path)
        return

    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
    logger.info("Serving frontend from %s", static_path)


def main() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
