"""CLI entry point for Thumbelina using Click."""

from __future__ import annotations

import click


@click.group()
def cli() -> None:
    """Thumbelina - Your personal AI assistant."""
    pass


@cli.command()
@click.option("--provider", default="openai", help="LLM provider to use")
@click.option("--model", default=None, help="Model to use")
def chat(provider: str, model: str) -> None:
    """Start an interactive chat session."""
    from thumbelina.cli.chat import run_chat

    run_chat(provider=provider, model=model)
