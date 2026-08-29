"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
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

    The frontend uses ``BrowserRouter``-based URL routing (per-page lazy
    chunks), so refreshing a deep link such as ``/coder`` hits FastAPI
    directly. ``StaticFiles(html=True)`` only maps ``/`` to ``index.html``,
    so a catch-all returns ``index.html`` for any path that is not an
    existing file; the built-in router then renders the correct page. API
    routes and the WebSocket are registered inside ``create_api_app`` before
    this handler, so they still take precedence. Skipped when the static dir
    is missing (e.g. ``thumbelina-serve`` run locally without a build),
    leaving a pure API app.
    """
    static_dir = os.environ.get("THUMBELINA_STATIC_DIR", "static")
    static_path = Path(static_dir)
    index_file = static_path / "index.html"
    if not index_file.is_file():
        logger.warning("Static dir %s missing index.html — serving API only", static_path)
        return

    # 带哈希的构建产物(/assets/*)交给 StaticFiles,获得 Range/缓存处理
    assets_dir = static_path / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    base = static_path.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # 根目录下真实存在的文件(favicon.svg 等)按原样返回;
        # 其余路径回退到 index.html,交由前端 BrowserRouter 处理深路由。
        candidate = (static_path / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(base):
            return FileResponse(candidate)
        return FileResponse(index_file)

    logger.info("Serving frontend from %s", static_path)


def main() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
