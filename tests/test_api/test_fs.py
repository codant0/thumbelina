"""Tests for the filesystem browsing API (/api/v1/fs/dirs)."""

from __future__ import annotations

import os
import re

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
