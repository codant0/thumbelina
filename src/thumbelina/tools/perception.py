"""感知工具:只读获取/加工信息,不改外部状态。

从 ``file_ops``/``web_tools``/``data_tools``/``web_search_tools`` 迁入,
函数体逐字保持,对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 的
security_review → _execute → self_verify 生命周期。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory
from thumbelina.tools.workspace_context import resolve_workspace_path

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
_MAX_CONTENT_SIZE = 50 * 1024  # 50KB
_SEARCH_TRUNCATE_LIMIT = 4000  # web_search 结果字符截断上限，防结果过大撑爆上下文
_SEARCH_MAX_HITS = 50
_SEARCH_MAX_LINE = 500
_SEARCH_MAX_FILE = 1 * 1024 * 1024
_MAX_RESULTS = 5

# search_files 遍历时按目录名剪枝：依赖/构建产物/缓存/版本库内部目录体量
# 巨大（单个 node_modules 即数万文件）且几乎不含有效检索目标，逐文件读取
# 只会拖慢搜索并污染 OS 文件缓存。
_SEARCH_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".eggs",
        ".next",
        ".nuxt",
        ".gradle",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "dist",
        "build",
        "target",
        "vendor",
    }
)


def _truncate(text: str) -> str:
    """web_search 结果截断助手:超过 ``_SEARCH_TRUNCATE_LIMIT`` 字符时截断。"""
    if len(text) > _SEARCH_TRUNCATE_LIMIT:
        return text[:_SEARCH_TRUNCATE_LIMIT] + "\n... (truncated)"
    return text


def _resolve_target(path: str) -> Path:
    """解析路径；有工作区时按工作区根解析并强制边界，无则保持原行为。"""
    resolved = resolve_workspace_path(path)
    if resolved is None:
        return Path(path).resolve()
    return resolved


class PerceptionTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.PERCEPTION


# ---------------------------------------------------------------------------
# args_schema(参数名与旧 @tool 完全一致)
# ---------------------------------------------------------------------------


class _ReadFileArgs(BaseModel):
    path: str = Field(..., description="Path of the file to read.")


class _ListDirectoryArgs(BaseModel):
    path: str = Field(default=".", description="Directory path to list.")


class _SearchFilesArgs(BaseModel):
    pattern: str = Field(..., description="Regex pattern to search for.")
    path: str = Field(default=".", description="Root directory to search under.")


class _FetchUrlArgs(BaseModel):
    url: str = Field(..., description="URL to fetch.")


class _ParseJsonArgs(BaseModel):
    text: str = Field(..., description="JSON text to parse.")


class _ParseCsvArgs(BaseModel):
    text: str = Field(..., description="CSV text to parse.")


class _AnalyzeTextArgs(BaseModel):
    text: str = Field(..., description="Text to analyze.")


class _SearchTextArgs(BaseModel):
    text: str = Field(..., description="Text to search in.")
    pattern: str = Field(..., description="Regex pattern to search for.")


class _WebSearchArgs(BaseModel):
    query: str = Field(..., description="Search query.")


# ---------------------------------------------------------------------------
# 文件类(原 file_ops.py)
# ---------------------------------------------------------------------------


class ReadFileTool(PerceptionTool):
    name: str = "read_file"
    description: str = "Read the contents of a file. Returns up to 1MB of text."
    args_schema: type[BaseModel] = _ReadFileArgs

    async def _execute(self, path: str) -> str:
        try:
            p = _resolve_target(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Not a file: {path}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_SIZE:
                return content[:_MAX_FILE_SIZE] + "\n... (truncated at 1MB)"
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except OSError as exc:
            return f"Error reading file: {exc}"


class ListDirectoryTool(PerceptionTool):
    name: str = "list_directory"
    description: str = "List files and directories in the given path."
    args_schema: type[BaseModel] = _ListDirectoryArgs

    async def _execute(self, path: str = ".") -> str:
        try:
            p = _resolve_target(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not p.exists():
            return f"Error: Directory not found: {path}"
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        try:
            entries = sorted(p.iterdir())
            lines = []
            for entry in entries:
                kind = "d" if entry.is_dir() else "f"
                lines.append(f"[{kind}] {entry.name}")
            if not lines:
                return "(empty directory)"
            return "\n".join(lines)
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except OSError as exc:
            return f"Error listing directory: {exc}"


class SearchFilesTool(PerceptionTool):
    name: str = "search_files"
    description: str = (
        "Search for a regex pattern in files under the given path.\n\n"
        "Returns up to 50 matches as 'path:line: content' lines. Binary files\n"
        "and files larger than 1MB are skipped. Dependency/build directories\n"
        "(node_modules, .venv, .git, ...) are excluded from the walk."
    )
    args_schema: type[BaseModel] = _SearchFilesArgs

    async def _execute(self, pattern: str, path: str = ".") -> str:
        try:
            root = _resolve_target(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not root.exists():
            return f"Error: Directory not found: {path}"
        if not root.is_dir():
            return f"Error: Not a directory: {path}"
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: Invalid pattern: {exc}"

        def _search_sync() -> list[str]:
            hits: list[str] = []
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # 目录级剪枝:被排除目录整个子树不再进入(含其下所有文件)。
                dirnames[:] = [d for d in dirnames if d not in _SEARCH_EXCLUDED_DIRS]
                for name in filenames:
                    if len(hits) >= _SEARCH_MAX_HITS:
                        break
                    entry = Path(dirpath) / name
                    try:
                        # Symlinks are untrusted: they can point outside the
                        # workspace, leaking external content. Skip them.
                        if entry.is_symlink() or not entry.is_file():
                            continue
                        if entry.stat().st_size > _SEARCH_MAX_FILE:
                            continue
                        text = entry.read_text(encoding="utf-8", errors="ignore")
                    except (PermissionError, OSError):
                        continue
                    for lineno, line in enumerate(text.splitlines(), start=1):
                        if regex.search(line):
                            hits.append(f"{entry}:{lineno}: {line[:_SEARCH_MAX_LINE]}")
                        if len(hits) >= _SEARCH_MAX_HITS:
                            break
                if len(hits) >= _SEARCH_MAX_HITS:
                    break
            return hits

        # 全盘遍历 + 逐文件读取是纯同步阻塞 IO,必须整体放入工作线程执行;
        # 在事件循环上直接跑会冻结整个进程(WS 心跳/流式推送/通道轮询全部停摆)。
        hits = await asyncio.to_thread(_search_sync)
        if not hits:
            return f"No matches for {pattern!r} under {path}"
        return "\n".join(hits)


# ---------------------------------------------------------------------------
# 网络类(原 web_tools.py / web_search_tools.py)
# ---------------------------------------------------------------------------


class FetchUrlTool(PerceptionTool):
    name: str = "fetch_url"
    description: str = "Fetch the content of a URL and return the text. Limited to 50KB."
    args_schema: type[BaseModel] = _FetchUrlArgs

    async def _execute(self, url: str) -> str:
        try:
            import httpx
        except ImportError:
            return "Error: httpx is not installed. Run: pip install httpx"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                text = response.text
                if len(text) > _MAX_CONTENT_SIZE:
                    return text[:_MAX_CONTENT_SIZE] + "\n... (truncated at 50KB)"
                return text
        except httpx.TimeoutException:
            return f"Error: Request timed out after 10 seconds: {url}"
        except httpx.HTTPStatusError as exc:
            return f"Error: HTTP {exc.response.status_code} from {url}"
        except httpx.RequestError as exc:
            return f"Error fetching URL: {exc}"


def _summaries(payload: dict[str, Any]) -> list[str]:
    """Return Tavily answer snippets (raw + llm) as a small list."""
    parts: list[str] = []
    for key in ("answer", "llm_response"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return parts


def _search_tavily(query: str, api_key: str) -> str:
    import httpx

    response = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": _MAX_RESULTS},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()

    sections: list[str] = _summaries(payload)
    results: list[str] = []
    for item in payload.get("results", [])[:_MAX_RESULTS]:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        bullet = f"- {title}\n  {url}\n  {content}"
        results.append(bullet)
    if results:
        sections.append("Results:\n" + "\n".join(results))
    text = "\n\n".join(s for s in sections if s)
    return _truncate(text) if text else "No results found."


def _search_duckduckgo(query: str) -> str:
    try:
        from ddgs import DDGS  # type: ignore[import-not-found]
    except ImportError:
        return "Error: 'ddgs' is not installed. Run: pip install ddgs"

    try:
        hits = list(DDGS().text(query, max_results=_MAX_RESULTS))
    except Exception as exc:  # 网络错误 / 反爬限流等
        return f"Error searching DuckDuckGo: {exc}"

    if not hits:
        return "No results found."

    results: list[str] = []
    for item in hits:
        title = (item.get("title") or "").strip()
        url = (item.get("href") or item.get("url") or "").strip()
        body = (item.get("body") or "").strip()
        results.append(f"- {title}\n  {url}\n  {body}")
    return _truncate("\n".join(results))


class WebSearchTool(PerceptionTool):
    name: str = "web_search"
    description: str = (
        "Search the web for a query and return ranked results and summaries.\n\n"
        "Useful when you need up-to-date or external information beyond what\n"
        "you already know. Returns a concise list of titles, URLs and snippets."
    )
    args_schema: type[BaseModel] = _WebSearchArgs

    config: Any = None

    async def _execute(self, query: str) -> str:
        cfg = self.config
        if cfg is None or not cfg.enabled:
            return "Web search is currently disabled."
        provider = cfg.provider
        if provider == "tavily":
            if not cfg.api_key:
                return (
                    "Error: Tavily search requires an API key. Configure it in "
                    "Settings → Tools → Web Search."
                )
            try:
                return await asyncio.to_thread(_search_tavily, query, cfg.api_key)
            except Exception as exc:
                return f"Error searching Tavily: {exc}"
        # duckduckgo — no API key required
        try:
            return await asyncio.to_thread(_search_duckduckgo, query)
        except Exception as exc:
            return f"Error searching DuckDuckGo: {exc}"


def make_web_search_tool(search_config_provider: Any) -> WebSearchTool:
    """兼容工厂:保持 ``make_web_search_tool(cfg)`` 调用点(含旧测试)不破坏。

    ``search_config_provider`` 为暴露 ``.enabled``/``.provider``/``.api_key``
    的活动配置对象(通常为 ``WebSearchConfig``);调用时才读取属性,
    运行时热更新即时生效。
    """
    return WebSearchTool(config=search_config_provider)


# ---------------------------------------------------------------------------
# 数据处理类(原 data_tools.py)
# ---------------------------------------------------------------------------


class ParseJsonTool(PerceptionTool):
    name: str = "parse_json"
    description: str = "Parse JSON text and return a formatted summary (keys, types, structure)."
    args_schema: type[BaseModel] = _ParseJsonArgs

    async def _execute(self, text: str) -> str:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return f"Error: Invalid JSON - {exc}"

        def _summarize(obj: object, indent: int = 0) -> str:
            prefix = "  " * indent
            if isinstance(obj, dict):
                if not obj:
                    return f"{prefix}(empty object)"
                lines: list[str] = []
                for key, value in obj.items():
                    type_name = type(value).__name__
                    if isinstance(value, dict):
                        lines.append(f"{prefix}{key}: object ({len(value)} keys)")
                        lines.append(_summarize(value, indent + 1))
                    elif isinstance(value, list):
                        lines.append(f"{prefix}{key}: array ({len(value)} items)")
                        if value:
                            lines.append(_summarize(value[0], indent + 1))
                    else:
                        lines.append(f"{prefix}{key}: {type_name} = {value!r}")
                return "\n".join(lines)
            if isinstance(obj, list):
                if not obj:
                    return f"{prefix}(empty array)"
                return _summarize(obj[0], indent)
            return f"{prefix}{type(obj).__name__} = {obj!r}"

        summary = _summarize(data)
        return f"Type: {type(data).__name__}\n{summary}"


class ParseCsvTool(PerceptionTool):
    name: str = "parse_csv"
    description: str = "Parse CSV text and return column names, row count, and first few rows."
    args_schema: type[BaseModel] = _ParseCsvArgs

    async def _execute(self, text: str) -> str:
        try:
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
        except csv.Error as exc:
            return f"Error: Invalid CSV - {exc}"

        if not rows:
            return "Empty CSV - no data"

        headers = rows[0]
        data_rows = rows[1:]
        preview_count = min(5, len(data_rows))

        lines = [
            f"Columns ({len(headers)}): {', '.join(headers)}",
            f"Rows: {len(data_rows)}",
            "",
            f"First {preview_count} rows:",
        ]
        for i, row in enumerate(data_rows[:preview_count]):
            lines.append(f"  [{i}] {', '.join(row)}")

        return "\n".join(lines)


class AnalyzeTextTool(PerceptionTool):
    name: str = "analyze_text"
    description: str = (
        "Analyze text: word count, line count, character count, top 10 frequent words."
    )
    args_schema: type[BaseModel] = _AnalyzeTextArgs

    async def _execute(self, text: str) -> str:
        if not text:
            return "Empty text"

        lines = text.splitlines()
        # Split on whitespace for word count
        words = re.findall(r"[a-zA-Z0-9一-鿿]+", text.lower())
        word_freq = Counter(words).most_common(10)

        result_lines = [
            f"Characters: {len(text)}",
            f"Words: {len(words)}",
            f"Lines: {len(lines)}",
            "",
            "Top 10 words:",
        ]
        for word, count in word_freq:
            result_lines.append(f"  {word}: {count}")

        return "\n".join(result_lines)


class SearchTextTool(PerceptionTool):
    name: str = "search_text"
    description: str = (
        "Search for a regex pattern in text and return all matches with line numbers."
    )
    args_schema: type[BaseModel] = _SearchTextArgs

    async def _execute(self, text: str, pattern: str) -> str:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return f"Error: Invalid regex pattern - {exc}"

        lines = text.splitlines()
        matches: list[str] = []
        for line_num, line in enumerate(lines, start=1):
            for match in compiled.finditer(line):
                matches.append(f"  Line {line_num}, Col {match.start() + 1}: {match.group()}")

        if not matches:
            return f"No matches found for pattern: {pattern}"

        header = f"Found {len(matches)} match(es) for pattern: {pattern}"
        return header + "\n" + "\n".join(matches)


# ---------------------------------------------------------------------------
# 组装函数
# ---------------------------------------------------------------------------


def perception_tools(search_config: Any = None) -> list[BaseTool]:
    """返回全部内置感知工具;``web_search`` 受 config 门控,默认不含。"""
    tools: list[BaseTool] = [
        ReadFileTool(),
        ListDirectoryTool(),
        SearchFilesTool(),
        FetchUrlTool(),
        ParseJsonTool(),
        ParseCsvTool(),
        AnalyzeTextTool(),
        SearchTextTool(),
    ]
    if search_config is not None:
        ws = getattr(search_config, "web_search", None)
        if ws is not None and getattr(ws, "enabled", False):
            tools.append(make_web_search_tool(ws))
    return tools
