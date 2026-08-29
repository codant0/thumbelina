"""get_all_tools 名称集合回归: 与重构前逐字一致(spec §7)。"""

from __future__ import annotations

from thumbelina.tools import get_all_tools

EXPECTED = {
    "read_file",
    "write_file",
    "list_directory",
    "search_files",
    "fetch_url",
    "run_shell",
    "parse_json",
    "parse_csv",
    "analyze_text",
    "search_text",
}


def test_names_stable():
    assert {t.name for t in get_all_tools()} == EXPECTED


def test_web_search_gated():
    class _Cfg:
        class web_search:  # noqa: N801
            enabled = True
            provider = "duckduckgo"
            api_key = ""

    names = {t.name for t in get_all_tools(_Cfg())}
    assert "web_search" in names


def test_categories_assigned():
    from thumbelina.tools.base import ToolCategory

    for t in get_all_tools():
        assert isinstance(t.category, ToolCategory)
