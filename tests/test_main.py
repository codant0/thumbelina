"""Tests for thumbelina.main module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig


def test_health_endpoint():
    from thumbelina.main import create_app

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
    )

    # Mock RepositoryManager and its repository
    mock_repository = MagicMock()
    mock_repository.conversation_repository = MagicMock()
    mock_repository.conversation_repository.ping = AsyncMock(return_value=True)
    mock_repository.close = MagicMock()

    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=MagicMock()),
    ):
        app = create_app(config)
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"


def test_create_app_returns_fastapi():
    from thumbelina.main import create_app

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
    )

    with (
        patch("thumbelina.api.app.RepositoryManager"),
        patch("thumbelina.api.app.create_provider"),
        patch("thumbelina.api.app.ThumbelinaAgent"),
    ):
        app = create_app(config)
        assert isinstance(app, FastAPI)


def _make_static_dir(root, index="<html>app</html>"):
    from pathlib import Path

    static = Path(root) / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(index, encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return static


def _mount_app(static_dir):
    from thumbelina.main import _mount_static_frontend

    app = FastAPI()
    with patch.dict(os.environ, {"THUMBELINA_STATIC_DIR": str(static_dir)}, clear=False):
        _mount_static_frontend(app)
    return TestClient(app)


def test_spa_fallback_serves_index_on_deep_route_refresh(tmp_path):
    """刷新 /coder 等深路由必须回退到 index.html,而不是 404。"""
    static = _make_static_dir(tmp_path)
    client = _mount_app(static)

    root = client.get("/")
    assert root.status_code == 200
    assert root.text == "<html>app</html>"

    deep = client.get("/coder")
    assert deep.status_code == 200
    assert deep.text == "<html>app</html>"


def test_existing_root_files_and_assets_served_directly(tmp_path):
    """真实存在的文件(favicon.svg、assets/*)按原样返回,不回退到 index.html。"""
    static = _make_static_dir(tmp_path)
    client = _mount_app(static)

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.text == "<svg/>"

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "console.log(1)"


def test_missing_asset_returns_404_not_html(tmp_path):
    """缺失的 JS/CSS 资源应保持 404,不能返回 HTML(浏览器会把它当 JS 执行)。"""
    static = _make_static_dir(tmp_path)
    client = _mount_app(static)

    response = client.get("/assets/nope.js")
    assert response.status_code == 404
    assert "html" not in response.headers.get("content-type", "")


def test_static_dir_without_index_html_is_not_mounted(tmp_path):
    """static 目录缺少 index.html 时跳过挂载,保持纯 API 行为。"""
    from pathlib import Path

    empty = Path(tmp_path) / "static"
    empty.mkdir()
    client = _mount_app(empty)

    assert client.get("/coder").status_code == 404
