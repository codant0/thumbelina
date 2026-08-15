"""Tests for the TODO REST API routes (/api/v1/todo)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig, TodoConfig

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


@contextmanager
def _build_client(
    tmp_path: Path,
    mock_agent: MagicMock,
    mock_repository: MagicMock,
    todo_config: TodoConfig,
) -> Iterator[TestClient]:
    """Create a TestClient with the same patches as conftest's ``client`` fixture."""
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="k"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        todo=todo_config,
    )
    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def todo_client(tmp_path: Path, mock_agent: MagicMock, mock_repository: MagicMock):
    """Test client with the TODO module enabled and rooted at tmp_path."""
    with _build_client(
        tmp_path,
        mock_agent,
        mock_repository,
        TodoConfig(directory=str(tmp_path / "TODO")),
    ) as test_client:
        yield test_client


@pytest.fixture
def disabled_client(tmp_path: Path, mock_agent: MagicMock, mock_repository: MagicMock):
    """Test client with the TODO module disabled."""
    with _build_client(tmp_path, mock_agent, mock_repository, TodoConfig(enabled=False)) as (
        test_client
    ):
        yield test_client


def test_status_enabled(todo_client: TestClient) -> None:
    response = todo_client.get("/api/v1/todo/status")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_items_crud(todo_client: TestClient) -> None:
    # Initial list is empty.
    response = todo_client.get("/api/v1/todo/items")
    assert response.status_code == 200
    assert response.json() == {"items": []}

    # Add an item; the full list is returned.
    response = todo_client.post("/api/v1/todo/items", json={"text": "买牛奶"})
    assert response.status_code == 200
    assert response.json() == {"items": [{"index": 0, "text": "买牛奶", "done": False}]}

    # Toggle done.
    response = todo_client.patch("/api/v1/todo/items/0", json={"done": True})
    assert response.status_code == 200
    assert response.json() == {"items": [{"index": 0, "text": "买牛奶", "done": True}]}

    # Change the text (done state is preserved).
    response = todo_client.patch("/api/v1/todo/items/0", json={"text": "买脱脂牛奶"})
    assert response.status_code == 200
    assert response.json() == {"items": [{"index": 0, "text": "买脱脂牛奶", "done": True}]}

    # Delete; list is empty again.
    response = todo_client.delete("/api/v1/todo/items/0")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_post_item_rejects_empty(todo_client: TestClient) -> None:
    response = todo_client.post("/api/v1/todo/items", json={"text": "   "})
    assert response.status_code == 422


def test_patch_invalid_index_404(todo_client: TestClient) -> None:
    response = todo_client.patch("/api/v1/todo/items/99", json={"done": True})
    assert response.status_code == 404


def test_patch_negative_index_404(todo_client: TestClient) -> None:
    response = todo_client.patch("/api/v1/todo/items/-1", json={"done": True})
    assert response.status_code == 404


def test_delete_invalid_index_404(todo_client: TestClient) -> None:
    response = todo_client.delete("/api/v1/todo/items/99")
    assert response.status_code == 404


def test_notes_crud(todo_client: TestClient) -> None:
    # Add two notes; each response carries the full list.
    response = todo_client.post("/api/v1/todo/notes", json={"content": "第一条笔记"})
    assert response.status_code == 200
    assert len(response.json()["notes"]) == 1

    response = todo_client.post("/api/v1/todo/notes", json={"content": "第二条笔记"})
    assert response.status_code == 200

    # Newest note is at index 0 and timestamps are well-formed.
    response = todo_client.get("/api/v1/todo/notes")
    assert response.status_code == 200
    notes = response.json()["notes"]
    assert len(notes) == 2
    assert notes[0]["index"] == 0
    assert notes[0]["content"] == "第二条笔记"
    assert notes[1]["index"] == 1
    assert notes[1]["content"] == "第一条笔记"
    assert TIMESTAMP_RE.match(notes[0]["timestamp"])
    assert TIMESTAMP_RE.match(notes[1]["timestamp"])
    original_timestamp = notes[0]["timestamp"]

    # Update content; timestamp stays unchanged.
    response = todo_client.put("/api/v1/todo/notes/0", json={"content": "改过的内容"})
    assert response.status_code == 200
    notes = response.json()["notes"]
    assert notes[0]["content"] == "改过的内容"
    assert notes[0]["timestamp"] == original_timestamp

    # Delete the newest; the older one remains at index 0.
    response = todo_client.delete("/api/v1/todo/notes/0")
    assert response.status_code == 200
    notes = response.json()["notes"]
    assert len(notes) == 1
    assert notes[0]["index"] == 0
    assert notes[0]["content"] == "第一条笔记"


def test_post_note_rejects_empty(todo_client: TestClient) -> None:
    response = todo_client.post("/api/v1/todo/notes", json={"content": "   "})
    assert response.status_code == 422


def test_put_note_invalid_index_404(todo_client: TestClient) -> None:
    response = todo_client.put("/api/v1/todo/notes/99", json={"content": "内容"})
    assert response.status_code == 404


def test_503_when_disabled(disabled_client: TestClient) -> None:
    # Data endpoints are unavailable.
    assert disabled_client.get("/api/v1/todo/items").status_code == 503
    assert disabled_client.post("/api/v1/todo/items", json={"text": "买牛奶"}).status_code == 503
    assert disabled_client.get("/api/v1/todo/notes").status_code == 503

    # Status endpoint still works and reports disabled.
    response = disabled_client.get("/api/v1/todo/status")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
