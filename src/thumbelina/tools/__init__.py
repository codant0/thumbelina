"""Built-in tools for the Thumbelina agent."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.tools.execution import RunShellTool, WriteFileTool
from thumbelina.tools.perception import (
    AnalyzeTextTool,
    FetchUrlTool,
    ListDirectoryTool,
    ParseCsvTool,
    ParseJsonTool,
    ReadFileTool,
    SearchFilesTool,
    SearchTextTool,
    make_web_search_tool,
)

# 感知工具已类化(Task 2);模块级实例保持旧符号可用,收口在 Task 7。
read_file = ReadFileTool()
list_directory = ListDirectoryTool()
search_files = SearchFilesTool()
fetch_url = FetchUrlTool()
parse_json = ParseJsonTool()
parse_csv = ParseCsvTool()
analyze_text = AnalyzeTextTool()
search_text = SearchTextTool()
# 执行工具已类化(Task 4);同样保留模块级实例垫片。
write_file = WriteFileTool()
run_shell = RunShellTool()

__all__ = [
    "analyze_text",
    "fetch_url",
    "get_all_tools",
    "list_directory",
    "make_web_search_tool",
    "parse_csv",
    "parse_json",
    "read_file",
    "run_shell",
    "search_files",
    "search_text",
    "write_file",
]


def get_all_tools(search_config: Any = None) -> list[BaseTool]:
    """Return all built-in tools.

    Parameters
    ----------
    search_config:
        Optional :class:`~thumbelina.config.models.ToolsConfig` (or an
        object exposing ``.web_search``). When provided and web search is
        enabled, the ``web_search`` tool is included, bound to the live
        config so runtime hot-swaps take effect.
    """
    tools: list[BaseTool] = [
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

    if search_config is not None:
        web_search_cfg = getattr(search_config, "web_search", None)
        if web_search_cfg is not None and getattr(web_search_cfg, "enabled", False):
            tools.append(make_web_search_tool(web_search_cfg))

    return tools
