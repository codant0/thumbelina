"""Built-in tools for the Thumbelina agent."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from thumbelina.tools.data_tools import analyze_text, parse_csv, parse_json, search_text
from thumbelina.tools.file_ops import list_directory, read_file, search_files, write_file
from thumbelina.tools.shell import run_shell
from thumbelina.tools.web_tools import fetch_url

__all__ = [
    "analyze_text",
    "fetch_url",
    "get_all_tools",
    "list_directory",
    "parse_csv",
    "parse_json",
    "read_file",
    "run_shell",
    "search_files",
    "search_text",
    "write_file",
]


def get_all_tools() -> list[BaseTool]:
    """Return all built-in tools."""
    return [
        read_file,
        write_file,
        list_directory,
        search_files,
        fetch_url,
        run_shell,
        parse_json,
        parse_csv,
        analyze_text,
        search_text,
    ]
