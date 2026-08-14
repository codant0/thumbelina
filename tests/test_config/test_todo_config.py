"""Tests for the TodoConfig section of AppConfig."""

from __future__ import annotations


class TestTodoConfig:
    """Tests for TodoConfig defaults and overrides via AppConfig."""

    def test_todo_config_defaults(self):
        from thumbelina.config.models import AppConfig

        cfg = AppConfig()
        assert cfg.todo.enabled is True
        assert cfg.todo.directory == "TODO"

    def test_todo_config_override(self):
        from thumbelina.config.models import AppConfig

        cfg = AppConfig(todo={"enabled": False, "directory": "X"})
        assert cfg.todo.enabled is False
        assert cfg.todo.directory == "X"
