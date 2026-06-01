"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from thumbelina.config import AppConfig, load_config


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

    app = FastAPI(title="thumbelina", debug=False)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app_name": "thumbelina"}

    return app


def main() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
