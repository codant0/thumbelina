"""Tests for thumbelina.cli.main module."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from thumbelina.cli.main import cli


def test_cli_group_exists():
    """The top-level CLI group should exist and show help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Thumbelina" in result.output


def test_cli_chat_command_registered():
    """The 'chat' subcommand should be registered on the CLI group."""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "interactive chat session" in result.output.lower()


def test_cli_chat_provider_option():
    """The 'chat' command should accept a --provider option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output


def test_cli_chat_model_option():
    """The 'chat' command should accept a --model option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.output


@patch("thumbelina.cli.chat.run_chat")
def test_cli_chat_invokes_run_chat(mock_run_chat):
    """Invoking 'chat' should call run_chat with provider and model."""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--provider", "openai", "--model", "gpt-4"])
    assert result.exit_code == 0
    mock_run_chat.assert_called_once()
    call_kwargs = mock_run_chat.call_args
    assert call_kwargs.kwargs["provider"] == "openai"
    assert call_kwargs.kwargs["model"] == "gpt-4"
