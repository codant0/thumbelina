"""Integration tests for the logging system.

These tests verify the end-to-end behaviour of the backend logging pipeline
(loguru + InterceptHandler) and the frontend log writer (RotatingLogWriter).
All tests operate in a temporary directory so they never touch real logs.
"""

from __future__ import annotations

import gzip
import logging
import re
import threading
from pathlib import Path

import pytest
import yaml
from loguru import logger
from start_dev import RotatingLogWriter

from thumbelina.logging_config import setup_logging

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_loguru():
    """Save and restore loguru state so tests don't leak handlers."""
    handlers = logger._core.handlers.copy()  # type: ignore[attr-defined]
    yield
    logger._core.handlers = handlers  # type: ignore[attr-defined]


@pytest.fixture()
def tmp_cwd(monkeypatch, tmp_path):
    """Change working directory to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Backend integration tests (loguru + stdlib bridge)
# ---------------------------------------------------------------------------


class TestBackendLogIntegration:
    """Verify that loguru writes messages to the log file and that
    standard logging messages are forwarded correctly."""

    def test_log_file_created_on_first_message(self, tmp_cwd):
        """setup_logging with default config should create logs/backend.log
        on the first loguru message."""
        setup_logging()
        logger.info("first message")
        log_file = tmp_cwd / "logs" / "backend.log"
        assert log_file.exists(), "backend.log should be created after first log message"

    def test_log_file_contains_message(self, tmp_cwd):
        """Messages written via loguru should appear in backend.log."""
        setup_logging()
        logger.info("integration test message")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "integration test message" in content

    def test_log_format_matches_design(self, tmp_cwd):
        """File log lines should match the format defined in the design:
        ``YYYY-MM-DD HH:mm:ss.SSS | LEVEL    | name:function:line - message``"""
        setup_logging()
        logger.warning("format check")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        line = content.strip().splitlines()[0]
        pattern = (
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| "
            r"WARNING\s+ \| "
            r".+:.+:\d+ - format check"
        )
        assert re.search(pattern, line), f"Log line does not match expected format: {line}"

    def test_stdlib_logging_forwarded_to_file(self, tmp_cwd):
        """Standard ``logging.getLogger()`` messages should appear in
        backend.log after setup_logging intercepts them."""
        setup_logging()
        std_logger = logging.getLogger("myapp.module")
        std_logger.info("stdlib hello")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "stdlib hello" in content

    def test_all_log_levels_captured(self, tmp_cwd):
        """DEBUG, INFO, WARNING, ERROR, CRITICAL messages should all
        appear in the file (file sink level is DEBUG)."""
        setup_logging()
        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warning msg")
        logger.error("error msg")
        logger.critical("critical msg")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        for level_msg in ["debug msg", "info msg", "warning msg", "error msg", "critical msg"]:
            assert level_msg in content, f"Missing '{level_msg}' in log file"

    def test_multiple_messages_preserved(self, tmp_cwd):
        """All messages should be present, not just the last one."""
        setup_logging()
        for i in range(50):
            logger.info("message {}", i)
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "message 0" in content
        assert "message 49" in content

    def test_custom_yaml_config_loaded(self, tmp_cwd):
        """When a logging.yaml exists, setup_logging should use it."""
        config = {
            "loguru": {
                "handlers": [
                    {
                        "sink": "logs/custom_backend.log",
                        "level": "INFO",
                        "format": "{level} | {message}",
                    }
                ]
            },
            "intercept": {"loggers": ["*"], "ignore": []},
        }
        cfg_path = tmp_cwd / "logging.yaml"
        cfg_path.write_text(yaml.dump(config), encoding="utf-8")

        setup_logging(config_path=str(cfg_path))
        logger.info("custom config works")

        log_file = tmp_cwd / "logs" / "custom_backend.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "custom config works" in content

    def test_utf8_content_in_log(self, tmp_cwd):
        """Non-ASCII characters (e.g. Chinese) should survive the round-trip."""
        setup_logging()
        logger.info("日志系统集成测试：中文内容")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "日志系统集成测试" in content

    def test_exception_traceback_logged(self, tmp_cwd):
        """Exception tracebacks should appear in the log file."""
        setup_logging()
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("caught an error")
        content = (tmp_cwd / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "caught an error" in content
        assert "ValueError" in content
        assert "boom" in content


# ---------------------------------------------------------------------------
# Frontend integration tests (RotatingLogWriter)
# ---------------------------------------------------------------------------


class TestRotatingLogWriterIntegration:
    """Verify that RotatingLogWriter creates, writes, rotates and
    compresses log files correctly."""

    def _make_writer(self, tmp_path: Path, max_size: int = 1024) -> tuple[RotatingLogWriter, Path]:
        """Helper: create a RotatingLogWriter with a small max_size."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "frontend.log"
        writer = RotatingLogWriter(log_path, max_size=max_size, backup_count=5)
        return writer, log_path

    def test_creates_log_file(self, tmp_path):
        """Writing should create the log file."""
        writer, log_path = self._make_writer(tmp_path)
        writer.write("hello\n")
        writer.close()
        assert log_path.exists()

    def test_writes_content(self, tmp_path):
        """Content written via write() should be readable from the file."""
        writer, log_path = self._make_writer(tmp_path)
        writer.write("frontend log line\n")
        writer.close()
        content = log_path.read_text(encoding="utf-8")
        assert "frontend log line" in content

    def test_rotation_creates_compressed_backup(self, tmp_path):
        """When the file exceeds max_size, a .1.log.gz backup should be
        created and the original file should be truncated."""
        writer, log_path = self._make_writer(tmp_path, max_size=100)
        # Write enough data to trigger rotation
        writer.write("A" * 120)
        writer.close()

        backup = log_path.with_suffix(".1.log.gz")
        assert backup.exists(), "Compressed backup .1.log.gz should exist after rotation"

    def test_compressed_backup_contains_original_content(self, tmp_path):
        """The .gz backup should contain the data that was in the file
        before rotation."""
        writer, log_path = self._make_writer(tmp_path, max_size=100)
        original_text = "ORIGINAL_DATA_MARKER"
        writer.write(original_text + "\n")
        # Write more to exceed max_size
        writer.write("B" * 120)
        writer.close()

        backup = log_path.with_suffix(".1.log.gz")
        with gzip.open(backup, "rt", encoding="utf-8") as f:
            decompressed = f.read()
        assert original_text in decompressed

    def test_file_empty_after_rotation(self, tmp_path):
        """After rotation the main log file should be empty (or near-empty)."""
        writer, log_path = self._make_writer(tmp_path, max_size=50)
        writer.write("X" * 80)
        writer.close()
        # After rotation, the file is reopened in "w" mode → empty
        content = log_path.read_text(encoding="utf-8")
        assert len(content) == 0

    def test_multiple_rotations(self, tmp_path):
        """Multiple rotations should produce .1, .2, … .gz files."""
        writer, log_path = self._make_writer(tmp_path, max_size=50)
        for _ in range(5):
            writer.write("C" * 80)
        writer.close()

        # At least .1.log.gz should exist (possibly more depending on timing)
        assert log_path.with_suffix(".1.log.gz").exists()

    def test_backup_count_respected(self, tmp_path):
        """Older backups beyond backup_count should be deleted."""
        writer, log_path = self._make_writer(tmp_path, max_size=30)
        # Trigger many rotations to exceed backup_count=5
        for _ in range(10):
            writer.write("D" * 50)
        writer.close()

        # .6.log.gz and beyond should NOT exist (backup_count=5)
        assert not log_path.with_suffix(".6.log.gz").exists()

    def test_close_prevents_further_writes(self, tmp_path):
        """After close(), write() should be a no-op (not raise)."""
        writer, log_path = self._make_writer(tmp_path)
        writer.write("before close\n")
        writer.close()
        # Should not raise
        writer.write("after close\n")

    def test_concurrent_writes(self, tmp_path):
        """Multiple threads writing concurrently should not crash."""
        writer, log_path = self._make_writer(tmp_path, max_size=10000)

        def _write(n: int):
            for i in range(50):
                writer.write(f"thread-{n}-line-{i}\n")

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        writer.close()

        content = log_path.read_text(encoding="utf-8")
        assert "thread-0-line-0" in content
        assert "thread-3-line-49" in content

    def test_utf8_in_frontend_log(self, tmp_path):
        """Non-ASCII content should survive in the frontend log."""
        writer, log_path = self._make_writer(tmp_path)
        writer.write("前端日志：Vite 启动成功\n")
        writer.close()
        content = log_path.read_text(encoding="utf-8")
        assert "Vite 启动成功" in content

    def test_rotation_preserves_utf8_in_gzip(self, tmp_path):
        """UTF-8 content should survive gzip compression after rotation."""
        writer, log_path = self._make_writer(tmp_path, max_size=50)
        writer.write("中文日志内容标记\n")
        writer.write("E" * 80)
        writer.close()

        backup = log_path.with_suffix(".1.log.gz")
        with gzip.open(backup, "rt", encoding="utf-8") as f:
            decompressed = f.read()
        assert "中文日志内容标记" in decompressed
