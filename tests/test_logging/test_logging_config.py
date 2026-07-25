"""Tests for the logging configuration module."""

from __future__ import annotations

import logging
from io import StringIO

import pytest
import yaml
from loguru import logger

from thumbelina.logging_config import InterceptHandler, get_default_config, setup_logging


@pytest.fixture(autouse=True)
def _restore_loguru():
    """Save and restore loguru state so tests don't leak handlers."""
    handlers = logger._core.handlers.copy()  # type: ignore[attr-defined]
    yield
    logger._core.handlers = handlers  # type: ignore[attr-defined]


@pytest.fixture
def tmp_cwd(monkeypatch, tmp_path):
    """Change working directory to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestInterceptHandler:
    """Tests for the InterceptHandler class."""

    def test_class_exists(self):
        """InterceptHandler should be importable."""
        assert InterceptHandler is not None

    def test_inherits_logging_handler(self):
        """InterceptHandler should be a subclass of logging.Handler."""
        assert issubclass(InterceptHandler, logging.Handler)

    def test_can_create_instance(self):
        """Should be able to create an InterceptHandler instance."""
        handler = InterceptHandler()
        assert handler is not None

    def test_emit_forwards_to_loguru(self, capsys):
        """Emit should forward a standard logging record to loguru."""
        logger.remove()
        sink = StringIO()
        logger.add(sink, format="{level} | {message}", level="DEBUG")

        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="hello from stdlib",
            args=None,
            exc_info=None,
        )
        handler.emit(record)

        output = sink.getvalue()
        assert "hello from stdlib" in output
        assert "INFO" in output

    def test_emit_handles_unknown_level(self):
        """Emit should handle log levels that loguru doesn't recognize."""
        logger.remove()
        sink = StringIO()
        logger.add(sink, format="{message}", level=0)

        handler = InterceptHandler()
        # Use a numeric level not mapped in loguru's level registry
        record = logging.LogRecord(
            name="test",
            level=25,  # Between INFO(20) and WARNING(30)
            pathname="test.py",
            lineno=1,
            msg="custom level",
            args=None,
            exc_info=None,
        )
        # Should not raise
        handler.emit(record)

    def test_emit_forwards_exception(self):
        """Emit should forward exception info to loguru."""
        logger.remove()
        sink = StringIO()
        logger.add(sink, format="{message}", level="DEBUG")

        handler = InterceptHandler()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=None,
            exc_info=exc_info,
        )
        handler.emit(record)

        output = sink.getvalue()
        assert "error occurred" in output
        assert "ValueError" in output

    def test_emit_uses_record_levelname(self):
        """Emit should translate the logging level name for loguru."""
        logger.remove()
        sink = StringIO()
        logger.add(sink, format="{level} | {message}", level="DEBUG")

        handler = InterceptHandler()

        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="a warning",
            args=None,
            exc_info=None,
        )
        handler.emit(record)

        output = sink.getvalue()
        assert "a warning" in output
        assert "WARNING" in output


class TestGetDefaultConfig:
    """Tests for the get_default_config function."""

    def test_returns_dict(self):
        """Should return a dictionary."""
        config = get_default_config()
        assert isinstance(config, dict)

    def test_has_loguru_key(self):
        """Config should have a 'loguru' key."""
        config = get_default_config()
        assert "loguru" in config

    def test_has_intercept_key(self):
        """Config should have an 'intercept' key."""
        config = get_default_config()
        assert "intercept" in config

    def test_loguru_handlers_is_list(self):
        """loguru.handlers should be a list."""
        config = get_default_config()
        assert isinstance(config["loguru"]["handlers"], list)

    def test_has_two_handlers(self):
        """Should have exactly two handlers (stderr + file)."""
        config = get_default_config()
        assert len(config["loguru"]["handlers"]) == 2

    def test_stderr_handler(self):
        """First handler should write to stderr."""
        config = get_default_config()
        handler = config["loguru"]["handlers"][0]
        assert handler["sink"] == "stderr"
        assert handler["level"] == "INFO"
        assert handler["colorize"] is True

    def test_file_handler(self):
        """Second handler should write to a log file with rotation."""
        config = get_default_config()
        handler = config["loguru"]["handlers"][1]
        assert handler["sink"] == "logs/backend.log"
        assert handler["level"] == "DEBUG"
        assert handler["rotation"] == "50 MB"
        assert handler["retention"] == "30 days"
        assert handler["compression"] == "gz"
        assert handler["encoding"] == "utf-8"

    def test_intercept_ignore_uvicorn_access(self):
        """Should ignore uvicorn.access logger by default."""
        config = get_default_config()
        assert "uvicorn.access" in config["intercept"]["ignore"]

    def test_intercept_all_loggers(self):
        """Should intercept all loggers by wildcard."""
        config = get_default_config()
        assert "*" in config["intercept"]["loggers"]


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def test_creates_logs_directory(self, tmp_cwd):
        """setup_logging should create a logs/ directory."""
        assert not (tmp_cwd / "logs").exists()
        setup_logging()
        assert (tmp_cwd / "logs").exists()

    def test_logs_directory_no_error_if_exists(self, tmp_cwd):
        """setup_logging should not fail if logs/ already exists."""
        (tmp_cwd / "logs").mkdir()
        setup_logging()
        assert (tmp_cwd / "logs").exists()

    def test_removes_default_loguru_handler(self, tmp_cwd):
        """setup_logging should clear loguru's default handler."""
        # Capture the handler count before
        setup_logging()
        # After setup, loguru should have handlers from config, not the default
        # We verify indirectly: loguru should have exactly 2 handlers (stderr + file)
        # from the default config
        assert len(logger._core.handlers) == 2  # type: ignore[attr-defined]

    def test_uses_default_config_when_no_file(self, tmp_cwd):
        """Should use default config when logging.yaml doesn't exist."""
        setup_logging()
        # After setup with default config, writing to a logger should work
        # and the log file should be created on first write
        logger.info("test message from default config")
        assert (tmp_cwd / "logs" / "backend.log").exists()

    def test_loads_config_from_file(self, tmp_cwd):
        """Should load config from a YAML file when it exists."""
        config = {
            "loguru": {
                "handlers": [
                    {
                        "sink": "stderr",
                        "level": "DEBUG",
                        "format": "{message}",
                        "colorize": False,
                    }
                ]
            },
            "intercept": {"loggers": ["*"], "ignore": []},
        }
        config_file = tmp_cwd / "logging.yaml"
        config_file.write_text(yaml.dump(config), encoding="utf-8")

        setup_logging(config_path=str(config_file))

        # Should have exactly 1 handler from config
        assert len(logger._core.handlers) == 1  # type: ignore[attr-defined]

    def test_loads_config_with_file_sink(self, tmp_cwd):
        """Should correctly handle file sink from config."""
        config = {
            "loguru": {
                "handlers": [
                    {
                        "sink": "logs/custom.log",
                        "level": "INFO",
                        "format": "{message}",
                        "rotation": "10 MB",
                        "retention": "7 days",
                    }
                ]
            },
            "intercept": {"loggers": ["*"], "ignore": []},
        }
        config_file = tmp_cwd / "logging.yaml"
        config_file.write_text(yaml.dump(config), encoding="utf-8")

        setup_logging(config_path=str(config_file))
        logger.info("test to custom log")

        assert (tmp_cwd / "logs" / "custom.log").exists()

    def test_sets_up_intercept_handler(self, tmp_cwd):
        """Should configure root logger with InterceptHandler."""
        setup_logging()
        root_handlers = logging.getLogger().handlers
        assert any(isinstance(h, InterceptHandler) for h in root_handlers)

    def test_intercepts_existing_loggers(self, tmp_cwd):
        """Should replace handlers on loggers that exist before setup."""
        # Create a logger before setup
        pre_logger = logging.getLogger("pre_existing_module")
        pre_logger.setLevel(logging.DEBUG)

        setup_logging()

        # The pre-existing logger should now have InterceptHandler
        target_logger = logging.getLogger("pre_existing_module")
        assert any(isinstance(h, InterceptHandler) for h in target_logger.handlers)
        assert target_logger.propagate is False

    def test_ignores_configured_loggers(self, tmp_cwd):
        """Should not replace handlers on loggers listed in ignore."""
        config = {
            "loguru": {"handlers": [{"sink": "stderr", "level": "INFO", "format": "{message}"}]},
            "intercept": {
                "loggers": ["*"],
                "ignore": ["my_special_logger"],
            },
        }
        config_file = tmp_cwd / "logging.yaml"
        config_file.write_text(yaml.dump(config), encoding="utf-8")

        # Create a logger that should be ignored
        special = logging.getLogger("my_special_logger")

        setup_logging(config_path=str(config_file))

        # The ignored logger should not have InterceptHandler
        assert not any(isinstance(h, InterceptHandler) for h in special.handlers)

    def test_stdlib_logging_forwarded_to_loguru(self, tmp_cwd):
        """Standard logging messages should be captured by loguru after setup."""
        logger.remove()
        sink = StringIO()
        logger.add(sink, format="{level} | {message}", level="DEBUG")

        # Don't call full setup_logging since it clears handlers; just do the
        # basicConfig part to test the forwarding mechanism.
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

        test_logger = logging.getLogger("stdlib_test")
        test_logger.info("forwarded message")

        output = sink.getvalue()
        assert "forwarded message" in output
