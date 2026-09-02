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
    assert response.json() == {
        "items": [{"index": 0, "text": "买牛奶", "done": False, "remark": ""}]
    }

    # Toggle done.
    response = todo_client.patch("/api/v1/todo/items/0", json={"done": True})
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"index": 0, "text": "买牛奶", "done": True, "remark": ""}]
    }

    # Change the text (done state is preserved).
    response = todo_client.patch("/api/v1/todo/items/0", json={"text": "买脱脂牛奶"})
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"index": 0, "text": "买脱脂牛奶", "done": True, "remark": ""}]
    }

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


def test_patch_item_remark(todo_client: TestClient) -> None:
    todo_client.post("/api/v1/todo/items", json={"text": "买牛奶"})

    # Set a Markdown remark; it is returned in the full list.
    response = todo_client.patch("/api/v1/todo/items/0", json={"remark": "记得买**脱脂**的"})
    assert response.status_code == 200
    assert response.json()["items"][0]["remark"] == "记得买**脱脂**的"
    assert response.json()["items"][0]["done"] is False

    # The remark persists across reads.
    response = todo_client.get("/api/v1/todo/items")
    assert response.json()["items"][0]["remark"] == "记得买**脱脂**的"

    # A remark can be cleared (whitespace collapses to empty-ish string).
    response = todo_client.patch("/api/v1/todo/items/0", json={"remark": " "})
    assert response.status_code == 200
    assert response.json()["items"][0]["remark"] == ""

    # An invalid index still 404s.
    response = todo_client.patch("/api/v1/todo/items/99", json={"remark": "x"})
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


def _write_todo_file(tmp_path: Path, name: str, content: str) -> None:
    (tmp_path / "TODO" / name).write_text(content, encoding="utf-8")


def test_items_report_group(todo_client: TestClient, tmp_path: Path) -> None:
    """Items under a '# heading' are tagged with that group in the response."""
    _write_todo_file(
        tmp_path,
        "todolist.md",
        "# 工作\n- [ ] 写周报\n- [x] 开会\n\n# 学习\n- [ ] 读论文\n",
    )

    response = todo_client.get("/api/v1/todo/items")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"index": 0, "text": "写周报", "done": False, "remark": "", "group": "工作"},
        {"index": 1, "text": "开会", "done": True, "remark": "", "group": "工作"},
        {"index": 2, "text": "读论文", "done": False, "remark": "", "group": "学习"},
    ]


def test_items_omit_group_key_when_ungrouped(todo_client: TestClient, tmp_path: Path) -> None:
    """Ungrouped items expose no 'group' key (exclude_none)."""
    _write_todo_file(tmp_path, "todolist.md", "- [ ] 无分组条目\n")

    response = todo_client.get("/api/v1/todo/items")

    assert "group" not in response.json()["items"][0]


def test_notes_report_group(todo_client: TestClient, tmp_path: Path) -> None:
    """Notes under a '# heading' are tagged with that group; grouped keys appear."""
    _write_todo_file(
        tmp_path,
        "notes.md",
        "# 项目A\n## 2026-08-14 21:30\n内容1\n\n# 生活\n## 2026-08-10 09:00\n内容2\n",
    )

    response = todo_client.get("/api/v1/todo/notes")

    assert response.status_code == 200
    notes = response.json()["notes"]
    assert [note["group"] for note in notes] == ["项目A", "生活"]
    assert notes[0]["content"] == "内容1"
    assert notes[1]["content"] == "内容2"


def test_notes_omit_group_key_when_ungrouped(todo_client: TestClient, tmp_path: Path) -> None:
    """Ungrouped notes expose no 'group' key (exclude_none)."""
    _write_todo_file(tmp_path, "notes.md", "## 2026-08-14 21:30\n内容\n")

    response = todo_client.get("/api/v1/todo/notes")

    assert "group" not in response.json()["notes"][0]


def test_patch_item_group_creates_marker(todo_client: TestClient, tmp_path: Path) -> None:
    """PATCH with group creates the # heading marker if missing."""
    response = todo_client.post("/api/v1/todo/items", json={"text": "条目 A"})
    assert response.status_code == 200

    response = todo_client.patch("/api/v1/todo/items/0", json={"group": "工作"})

    assert response.status_code == 200
    assert response.json()["items"][0]["group"] == "工作"
    assert "# 工作" in (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")


def test_patch_item_group_empty_string_clears(todo_client: TestClient, tmp_path: Path) -> None:
    """PATCH with group='' moves the item out of its group."""
    _write_todo_file(tmp_path, "todolist.md", "# 工作\n- [ ] 条目 A\n")

    response = todo_client.patch("/api/v1/todo/items/0", json={"group": ""})

    assert response.status_code == 200
    assert "group" not in response.json()["items"][0]


def test_put_note_group_only(todo_client: TestClient) -> None:
    """PUT /notes/{i} with only ``group`` reassigns without touching content."""
    todo_client.post("/api/v1/todo/notes", json={"content": "原始内容"})

    response = todo_client.put(
        "/api/v1/todo/notes/0",
        json={"content": "原始内容", "group": "工作"},
    )

    assert response.status_code == 200
    note = response.json()["notes"][0]
    assert note["content"] == "原始内容"
    assert note["group"] == "工作"


def test_create_item_group_appends_marker(todo_client: TestClient, tmp_path: Path) -> None:
    """POST /items/groups writes a ``# name`` marker."""
    response = todo_client.post("/api/v1/todo/items/groups", json={"name": "工作"})

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert "# 工作" in (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")


def test_create_group_rejects_blank(todo_client: TestClient) -> None:
    response = todo_client.post("/api/v1/todo/items/groups", json={"name": "   "})
    assert response.status_code == 422


def test_rename_item_group(todo_client: TestClient, tmp_path: Path) -> None:
    """PATCH /items/groups/{old} renames marker and reassigns items."""
    _write_todo_file(tmp_path, "todolist.md", "# 工作\n- [ ] 条目 A\n")

    response = todo_client.patch("/api/v1/todo/items/groups/工作", json={"name": "Projects"})

    assert response.status_code == 200
    assert response.json()["items"][0]["group"] == "Projects"
    text = (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")
    assert "# Projects" in text
    assert "# 工作" not in text


def test_rename_item_group_conflict_409(todo_client: TestClient, tmp_path: Path) -> None:
    """Renaming onto an existing group returns 409."""
    _write_todo_file(tmp_path, "todolist.md", "# 工作\n- [ ] a\n# 学习\n- [ ] b\n")

    response = todo_client.patch("/api/v1/todo/items/groups/工作", json={"name": "学习"})
    assert response.status_code == 409


def test_rename_item_group_unknown_404(todo_client: TestClient) -> None:
    response = todo_client.patch("/api/v1/todo/items/groups/不存在", json={"name": "Projects"})
    assert response.status_code == 404


def test_delete_item_group_moves_members_ungrouped(todo_client: TestClient, tmp_path: Path) -> None:
    """DELETE removes the marker and detaches every member."""
    _write_todo_file(tmp_path, "todolist.md", "# 工作\n- [ ] a\n# 学习\n- [ ] b\n")

    response = todo_client.delete("/api/v1/todo/items/groups/工作")

    assert response.status_code == 200
    items = response.json()["items"]
    # exclude_none drops the ``group`` key entirely for ungrouped items.
    assert [item.get("group") for item in items] == [None, "学习"]
    text = (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")
    assert "# 工作" not in text
    assert "# 学习" in text


def test_drag_item_across_groups_round_trips(todo_client: TestClient, tmp_path: Path) -> None:
    """Physically moving an item between groups stays stable on re-read.

    The UI drags by the index it currently renders; after the server moves
    the line the ordering may shift, but a fresh read must agree with the
    response the move returned.
    """
    _write_todo_file(
        tmp_path,
        "todolist.md",
        "# 工作\n- [ ] 写周报\n# 学习\n- [ ] 读论文\n",
    )

    # Drag '读论文' (currently index 1) into 工作.
    response = todo_client.patch("/api/v1/todo/items/1", json={"group": "工作"})
    assert response.status_code == 200
    moved = response.json()["items"]
    assert [item["text"] for item in moved] == ["写周报", "读论文"]
    assert [item["group"] for item in moved] == ["工作", "工作"]

    # A fresh read agrees with the move response.
    response = todo_client.get("/api/v1/todo/items")
    assert response.json()["items"] == moved

    # Drag '写周报' out of its group back to ungrouped.
    response = todo_client.patch("/api/v1/todo/items/0", json={"group": ""})
    assert response.status_code == 200
    assert [item.get("group") for item in response.json()["items"]] == [None, "工作"]


def test_delete_item_group_unknown_404(todo_client: TestClient) -> None:
    response = todo_client.delete("/api/v1/todo/items/groups/不存在")
    assert response.status_code == 404


def test_note_group_crud_via_api(todo_client: TestClient, tmp_path: Path) -> None:
    """notes.md supports the same create / rename / delete endpoints."""
    response = todo_client.post("/api/v1/todo/notes/groups", json={"name": "工作"})
    assert response.status_code == 200

    response = todo_client.post("/api/v1/todo/notes", json={"content": "笔记 A"})
    assert response.status_code == 200
    note_index = response.json()["notes"][0]["index"]

    response = todo_client.put(
        f"/api/v1/todo/notes/{note_index}",
        json={"content": "笔记 A", "group": "工作"},
    )
    assert response.status_code == 200
    assert response.json()["notes"][0]["group"] == "工作"

    response = todo_client.patch("/api/v1/todo/notes/groups/工作", json={"name": "Projects"})
    assert response.status_code == 200
    assert response.json()["notes"][0]["group"] == "Projects"

    response = todo_client.delete("/api/v1/todo/notes/groups/Projects")
    assert response.status_code == 200
    assert "group" not in response.json()["notes"][0]
