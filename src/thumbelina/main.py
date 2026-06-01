"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from thumbelina.config import AppConfig


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    config:
        Optional application configuration.  When *None* the configuration
        is loaded from environment variables.
    """
    if config is None:
        config = AppConfig.from_env()

    app = FastAPI(title=config.app_name, debug=config.debug)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app_name": config.app_name}

    return app


def main() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    config = AppConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
