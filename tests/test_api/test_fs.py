"""Tests for the filesystem browsing API (/api/v1/fs/dirs)."""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

from thumbelina.api.routes.fs import _MAX_LIST_ENTRIES

_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:\\$")


def _names(data: dict) -> list[str]:
    return [c["name"] for c in data["children"]]


def test_root_listing_without_path(client) -> None:
    response = client.get("/api/v1/fs/dirs")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"path", "parent", "children", "truncated"}
    assert data["parent"] is None
    assert data["truncated"] is False
    if os.name == "nt":
        assert data["path"] is None
        assert len(data["children"]) > 0
        assert all(c["name"] == c["path"] for c in data["children"])
        assert all(_DRIVE_PATTERN.match(c["name"]) for c in data["children"])
    else:
        assert data["path"] == "/"
        assert all(c["path"].startswith("/") for c in data["children"])
        assert _names(data) == sorted(_names(data), key=str.casefold)


def test_list_subdirs_excludes_files(client, tmp_path) -> None:
    (tmp_path / "sub_b").mkdir()
    (tmp_path / "sub_a").mkdir()
    (tmp_path / "doc.txt").write_text("x")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    response = client.get("/api/v1/fs/dirs", params={"path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(tmp_path.resolve())
    assert data["parent"] == str(tmp_path.parent.resolve())
    assert data["truncated"] is False
    assert _names(data) == ["sub_a", "sub_b"]
    for child in data["children"]:
        assert os.path.isabs(child["path"])
        assert child["path"] == str(tmp_path / child["name"])


def test_children_sorted_casefold(client, tmp_path) -> None:
    for name in ("z_lower", "M_upper", "a_mixed"):
        (tmp_path / name).mkdir()
    response = client.get("/api/v1/fs/dirs", params={"path": str(tmp_path)})
    assert _names(response.json()) == ["a_mixed", "M_upper", "z_lower"]


def test_relative_path_rejected(client) -> None:
    response = client.get("/api/v1/fs/dirs", params={"path": "some/relative/path"})
    assert response.status_code == 422
    assert "绝对路径" in response.json()["detail"]


def test_file_path_rejected(client, tmp_path) -> None:
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    response = client.get("/api/v1/fs/dirs", params={"path": str(f)})
    assert response.status_code == 422
    assert "不是有效目录" in response.json()["detail"]


def test_nonexistent_path_rejected(client, tmp_path) -> None:
    response = client.get("/api/v1/fs/dirs", params={"path": str(tmp_path / "missing")})
    assert response.status_code == 422
    assert "不是有效目录" in response.json()["detail"]


@pytest.mark.skipif(
    os.name == "nt", reason="chmod-based permission checks are unreliable on Windows"
)
def test_unreadable_dir_rejected(client, tmp_path) -> None:
    if os.geteuid() == 0:  # root ignores permission bits
        pytest.skip("running as root")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        response = client.get("/api/v1/fs/dirs", params={"path": str(locked)})
        assert response.status_code == 422
        assert "不可读" in response.json()["detail"]
    finally:
        locked.chmod(0o755)


def test_symlink_dir_excluded(client, tmp_path) -> None:
    real = tmp_path / "real_dir"
    real.mkdir()
    target = tmp_path / "target_dir"
    target.mkdir()
    link = tmp_path / "link_dir"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    response = client.get("/api/v1/fs/dirs", params={"path": str(tmp_path)})
    assert _names(response.json()) == ["real_dir", "target_dir"]
    assert "link_dir" not in _names(response.json())


def test_list_truncated(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("thumbelina.api.routes.fs._MAX_LIST_ENTRIES", 5)
    for i in range(8):
        (tmp_path / f"dir_{i}").mkdir()
    response = client.get("/api/v1/fs/dirs", params={"path": str(tmp_path)})
    data = response.json()
    assert len(data["children"]) == 5
    assert data["truncated"] is True
    assert _names(data) == sorted(_names(data), key=str.casefold)


def test_root_parent_is_none(client) -> None:
    if os.name == "nt":
        roots = client.get("/api/v1/fs/dirs").json()["children"]
        if not roots:
            pytest.skip("no drives listed")
        response = client.get("/api/v1/fs/dirs", params={"path": roots[0]["path"]})
        assert response.status_code == 200
        assert response.json()["parent"] is None
    else:
        response = client.get("/api/v1/fs/dirs", params={"path": "/"})
        assert response.status_code == 200
        assert response.json()["parent"] is None


def test_limit_constant_positive() -> None:
    assert _MAX_LIST_ENTRIES > 0


def _init_repo(tmp_path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=repo, check=True,
    )
    return repo


class TestGitInfoEndpoints:
    """git 探测端点测试;git 缺失时仅跳过本类,不影响目录浏览测试。"""

    pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

    def test_git_info_in_repo(self, client, tmp_path) -> None:
        repo = _init_repo(tmp_path)
        resp = client.get("/api/v1/fs/git", params={"path": str(repo)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git"] is True
        assert isinstance(data["branch"], str) and data["branch"]

    def test_git_info_non_repo(self, client, tmp_path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        resp = client.get("/api/v1/fs/git", params={"path": str(plain)})
        assert resp.status_code == 200
        assert resp.json() == {"is_git": False, "branch": None}

    def test_git_info_invalid_path(self, client, tmp_path) -> None:
        resp = client.get("/api/v1/fs/git", params={"path": str(tmp_path / "missing")})
        assert resp.status_code == 422

    def test_git_info_empty_repo(self, client, tmp_path) -> None:
        """无提交的空仓也是 git 仓库,应显示 is_git 与 unborn 分支名。"""
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        resp = client.get("/api/v1/fs/git", params={"path": str(repo)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git"] is True
        assert isinstance(data["branch"], str) and data["branch"]

    def test_git_info_relative_path_rejected(self, client, tmp_path) -> None:
        resp = client.get("/api/v1/fs/git", params={"path": "some/relative"})
        assert resp.status_code == 422


class TestGitBranchesEndpoints:
    pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

    def test_git_branches(self, client, tmp_path) -> None:
        repo = _init_repo(tmp_path)
        subprocess.run(["git", "checkout", "-q", "-b", "feature-a"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
        subprocess.run(["git", "branch", "-q", "feature-b"], cwd=repo, check=True)
        resp = client.get("/api/v1/fs/git/branches", params={"path": str(repo)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git"] is True
        assert data["current"] == "main"
        assert data["branches"] == ["feature-a", "feature-b", "main"]

    def test_git_branches_non_repo(self, client, tmp_path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        resp = client.get("/api/v1/fs/git/branches", params={"path": str(plain)})
        assert resp.status_code == 200
        assert resp.json() == {"is_git": False, "current": None, "branches": []}


class TestGitCheckoutEndpoints:
    pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

    def test_checkout_success(self, client, tmp_path) -> None:
        repo = _init_repo(tmp_path)
        subprocess.run(["git", "branch", "-q", "feature-a"], cwd=repo, check=True)
        resp = client.post(
            "/api/v1/fs/git/checkout",
            json={"path": str(repo), "branch": "feature-a"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"is_git": True, "branch": "feature-a"}
        probe = client.get("/api/v1/fs/git", params={"path": str(repo)})
        assert probe.json()["branch"] == "feature-a"

    def test_checkout_unknown_branch(self, client, tmp_path) -> None:
        repo = _init_repo(tmp_path)
        resp = client.post(
            "/api/v1/fs/git/checkout",
            json={"path": str(repo), "branch": "does-not-exist"},
        )
        assert resp.status_code == 422
        assert "分支不存在" in resp.json()["detail"]

    def test_checkout_non_repo(self, client, tmp_path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        resp = client.post(
            "/api/v1/fs/git/checkout",
            json={"path": str(plain), "branch": "main"},
        )
        assert resp.status_code == 422

    def test_checkout_conflict_returns_409(self, client, tmp_path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "file.txt").write_text("A", encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "a"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "-q", "-b", "feature-a"], cwd=repo, check=True)
        (repo / "file.txt").write_text("B", encoding="utf-8")
        subprocess.run(["git", "commit", "-q", "-am", "b"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
        (repo / "file.txt").write_text("uncommitted", encoding="utf-8")
        resp = client.post(
            "/api/v1/fs/git/checkout",
            json={"path": str(repo), "branch": "feature-a"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]

    def test_checkout_broadcasts(self, client, tmp_path, monkeypatch) -> None:
        from unittest.mock import AsyncMock

        broadcast = AsyncMock()
        monkeypatch.setattr(
            "thumbelina.api.websocket.broadcast_chat_message", broadcast
        )
        repo = _init_repo(tmp_path)
        subprocess.run(["git", "branch", "-q", "feature-a"], cwd=repo, check=True)
        resp = client.post(
            "/api/v1/fs/git/checkout",
            json={"path": str(repo), "branch": "feature-a"},
        )
        assert resp.status_code == 200
        broadcast.assert_awaited_once()
        message = broadcast.await_args.args[0]
        assert message["git_branch"]["branch"] == "feature-a"
        assert message["git_branch"]["workspace"] == str(repo.resolve())
