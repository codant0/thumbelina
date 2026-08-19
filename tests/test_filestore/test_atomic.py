"""Tests for the public atomic file operations in ``thumbelina.filestore``."""

from __future__ import annotations

from pathlib import Path

from thumbelina.filestore.atomic import (
    cleanup_tmp,
    ensure_dir,
    read_text,
    safe_unlink,
    write_text_atomic,
)


class TestEnsuredir:
    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"
        ensure_dir(target)
        assert target.is_dir()

    def test_is_idempotent(self, tmp_path: Path) -> None:
        ensure_dir(tmp_path)
        ensure_dir(tmp_path)  # no error


class TestWriteAtomic:
    def test_writes_content_and_creates_parents(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "file.md"
        write_text_atomic(path, "hello\n")
        assert path.read_text(encoding="utf-8") == "hello\n"

    def test_no_tmp_leftover_on_success(self, tmp_path: Path) -> None:
        path = tmp_path / "file.md"
        write_text_atomic(path, "data")
        leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        path = tmp_path / "file.md"
        write_text_atomic(path, "first")
        write_text_atomic(path, "second")
        assert path.read_text(encoding="utf-8") == "second"

    def test_leaves_old_content_when_write_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "file.md"
        write_text_atomic(path, "original")
        # A non-serializable object should make handle.write raise so the
        # temp file is cleaned up and the target is untouched.
        with open(path.with_name(path.name + ".tmp"), "w", encoding="utf-8") as handle:
            handle.write("stale")  # simulate a leftover before we call below
        try:
            write_text_atomic(path, object())  # type: ignore[arg-type]
        except (TypeError, AttributeError):
            pass
        else:  # pragma: no cover - defensive
            assert False, "write_text_atomic should have raised"
        assert path.read_text(encoding="utf-8") == "original"
        assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


class TestReadText:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_text(tmp_path / "nope.md") == ""

    def test_reads_content(self, tmp_path: Path) -> None:
        path = tmp_path / "file.md"
        path.write_text("abc", encoding="utf-8")
        assert read_text(path) == "abc"


class TestSafeUnlink:
    def test_deletes_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "file.md"
        path.write_text("x", encoding="utf-8")
        safe_unlink(path)
        assert not path.exists()

    def test_missing_is_idempotent(self, tmp_path: Path) -> None:
        safe_unlink(tmp_path / "nope.md")  # no error


class TestCleanupTmp:
    def test_removes_tmp_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        keep = tmp_path / "a" / "real.md"
        keep.write_text("keep", encoding="utf-8")
        (tmp_path / "leftover.md.tmp").write_text("junk", encoding="utf-8")
        (tmp_path / "a" / "nested.tmp").write_text("junk", encoding="utf-8")

        cleanup_tmp(tmp_path)

        assert keep.read_text(encoding="utf-8") == "keep"
        assert not (tmp_path / "leftover.md.tmp").exists()
        assert not (tmp_path / "a" / "nested.tmp").exists()

    def test_missing_base_is_noop(self, tmp_path: Path) -> None:
        cleanup_tmp(tmp_path / "nonexistent")
