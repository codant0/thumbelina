"""API 端到端 + 降级 + 鉴权限流测试(设计文档 §9.6、§13 任务 14)。

构造带 memory service 的测试 app:复用 ``tests/test_api/conftest.py`` 的
mock 范式(patch RepositoryManager/create_provider/ThumbelinaAgent),用
``MemoryConfig(enabled=False)`` 避免 lifespan 创建真实 MEMORY 目录,
TestClient 进入后手动注入 ``app.state.memory_service`` 为 tmp_path 下的
真 :class:`MemoryService`。

端点用例:
  - GET /api/v1/memory/status(enabled/entries)。
  - GET /index、/entries、/{category}/{slug}?depth=overview|full。
  - depth 非法→422;非法 category/slug→400;不存在条目→404。
  - GET /search?q=。
  - service 不可用→503(/status 除外 200)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import (
    AppConfig,
    LLMConfig,
    MemoryConfig,
    RepositoryConfig,
)
from thumbelina.memory.models import MemoryEntry
from thumbelina.memory.service import MemoryService


def _entry(
    *,
    title: str = "用户:编程偏好",
    category: str = "user",
    slug: str = "programming-preference",
    summary: str = "偏好 Python、类型注解。",
    overview: str = "偏好 Python 3.11+。",
    full_text: str = "- 2026-08-10:偏好 Python。",
) -> MemoryEntry:
    return MemoryEntry(
        title=title,
        category=category,
        slug=slug,
        summary=summary,
        updated="2026-08-16",
        overview=overview,
        full_text=full_text,
    )


def _mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")

    async def _stream(*args, **kwargs):
        yield {"type": "content", "text": "Agent response"}

    agent.stream = _stream
    agent.current_conversation_id = None
    agent.repository_manager = None
    agent.clone.return_value = agent
    return agent


def _mock_repository() -> MagicMock:
    conv = {
        "id": "test-conv-id",
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
        "summary": None,
    }
    repository = MagicMock()
    repository.create_conversation = AsyncMock(return_value="test-conv-id")
    repository.get_conversations = AsyncMock(return_value=[conv])
    repository.get_messages = AsyncMock(return_value=[])
    repository.delete_conversation = AsyncMock(return_value=True)
    repository.clear_messages = AsyncMock(return_value=True)
    repository.add_message = AsyncMock()
    repository.close = MagicMock()
    repository.conversation_repository = MagicMock()
    repository.conversation_repository.ping = AsyncMock(return_value=True)
    return repository


@pytest.fixture
async def memory_app(tmp_path: Path):
    """构造带真实 memory service(注入 app.state)的测试 app。

    用 ``MemoryConfig(enabled=False)`` 避免 lifespan 创建 MEMORY 目录;
    TestClient 进入后手动注入 tmp_path 下的真 service。
    """
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        memory=MemoryConfig(enabled=False),
    )
    mock_agent = _mock_agent()
    mock_repo = _mock_repository()

    # 预创建 memory service(tmp_path 下)
    mem_svc = MemoryService(tmp_path / "MEMORY")
    await mem_svc.init()

    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repo),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as client:
            # 注入真实 memory service(lifespan 设为 None,此处覆盖)
            app.state.memory_service = mem_svc
            yield client, app


@pytest.fixture
async def memory_app_no_service(tmp_path: Path):
    """构造无 memory service 的测试 app(模拟降级)。"""
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        memory=MemoryConfig(enabled=False),
    )
    mock_agent = _mock_agent()
    mock_repo = _mock_repository()

    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repo),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as client:
            # 确保无 service
            app.state.memory_service = None
            yield client, app


class TestStatus:
    """GET /api/v1/memory/status。"""

    async def test_status_enabled_with_entries(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get("/api/v1/memory/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["entries"] == 1

    async def test_status_enabled_no_entries(self, memory_app) -> None:
        client, _ = memory_app
        resp = client.get("/api/v1/memory/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["entries"] == 0

    async def test_status_disabled_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.get("/api/v1/memory/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["entries"] == 0


class TestIndexAndEntries:
    """GET /index、/entries。"""

    async def test_get_index(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get("/api/v1/memory/index")
        assert resp.status_code == 200
        data = resp.json()
        assert "# 记忆索引" in data["index"]
        assert "programming-preference.md" in data["index"]

    async def test_get_entries(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        await svc.update_memory(_entry(slug="another", title="项目:另一条", category="project"))
        resp = client.get("/api/v1/memory/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        slugs = {e["slug"] for e in data}
        assert "programming-preference" in slugs
        assert "another" in slugs

    async def test_index_503_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.get("/api/v1/memory/index")
        assert resp.status_code == 503

    async def test_entries_503_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.get("/api/v1/memory/entries")
        assert resp.status_code == 503


class TestReadEntry:
    """GET /{category}/{slug}?depth=。"""

    async def test_read_overview(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get(
            "/api/v1/memory/user/programming-preference", params={"depth": "overview"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "用户:编程偏好"
        assert "偏好 Python 3.11+" in data["overview"]
        assert data["full_text"] == ""

    async def test_read_full(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get("/api/v1/memory/user/programming-preference", params={"depth": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert "2026-08-10" in data["full_text"]
        assert data["overview"] != ""

    async def test_depth_default_overview(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get("/api/v1/memory/user/programming-preference")
        assert resp.status_code == 200
        assert resp.json()["full_text"] == ""

    async def test_illegal_depth_returns_422(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get(
            "/api/v1/memory/user/programming-preference", params={"depth": "bogus"}
        )
        assert resp.status_code == 422

    async def test_illegal_category_returns_400(self, memory_app) -> None:
        client, _ = memory_app
        # 大写 category 被 _resolve 正则拒绝
        resp = client.get("/api/v1/memory/User/evil")
        assert resp.status_code == 400

    async def test_illegal_slug_returns_400(self, memory_app) -> None:
        client, _ = memory_app
        # slug 含点号被 _resolve 正则拒绝;用单段 URL 避免 HTTP 路径归一化。
        resp = client.get("/api/v1/memory/user/slug.dot")
        assert resp.status_code == 400

    async def test_nonexistent_entry_returns_404(self, memory_app) -> None:
        client, _ = memory_app
        resp = client.get("/api/v1/memory/user/nope")
        assert resp.status_code == 404

    async def test_read_503_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.get("/api/v1/memory/user/anything")
        assert resp.status_code == 503


class TestSearch:
    """GET /search?q=。"""

    async def test_search_hits(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry(summary="偏好 Python 编程"))
        await svc.update_memory(
            _entry(slug="db", title="项目:数据库", category="project", summary="数据库选型")
        )
        resp = client.get("/api/v1/memory/search", params={"q": "Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert any(h["slug"] == "programming-preference" for h in data)

    async def test_search_no_hits(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.get("/api/v1/memory/search", params={"q": "zzzzznomatch"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_503_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.get("/api/v1/memory/search", params={"q": "x"})
        assert resp.status_code == 503


class TestRefresh:
    """POST /refresh。"""

    async def test_refresh(self, memory_app) -> None:
        client, app = memory_app
        svc: MemoryService = app.state.memory_service
        await svc.update_memory(_entry())
        resp = client.post("/api/v1/memory/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == 1
        assert "# 记忆索引" in data["index"]

    async def test_refresh_503_when_no_service(self, memory_app_no_service) -> None:
        client, _ = memory_app_no_service
        resp = client.post("/api/v1/memory/refresh")
        assert resp.status_code == 503
