"""Markdown 记忆文档解析与索引生成测试(设计文档 §5、§13 任务 14)。

覆盖:
  - ``parse_document``:标题/元数据行/概览/全文区间切分、缺标题/无分类/空文本。
  - ``build_index``:分组/链接/摘要/更新日期/中文分类标签/无条目分类省略。
  - ``read_entry_file``/``scan_entries``:非 UTF-8 降级、跳过 ``.tmp`` 与
    ``index.md``、白名单外分类目录被忽略。
"""

from __future__ import annotations

from pathlib import Path

from thumbelina.memory.models import MemoryEntry
from thumbelina.memory.parser import (
    build_index,
    parse_document,
    read_entry_file,
    scan_entries,
)

_CATEGORIES = ["user", "project", "decision", "topic"]


def _sample_doc(
    *,
    title: str = "用户:编程偏好",
    category: str = "user",
    updated: str = "2026-08-16",
    source: str = "对话 2026-08-10、2026-08-12",
    summary: str = "偏好 Python、类型注解、简洁命名。",
    overview: str = "用户偏好 Python 3.11+,重视类型注解。",
    full_text: str = "- 2026-08-10:偏好 Python。\n- 2026-08-12:不喜欢过度抽象。",
) -> str:
    meta_parts = [f"分类:{category}"]
    if updated:
        meta_parts.append(f"更新:{updated}")
    if source:
        meta_parts.append(f"来源:{source}")
    if summary:
        meta_parts.append(f"摘要:{summary}")
    return (
        f"# {title}\n\n"
        f"> {' · '.join(meta_parts)}\n\n"
        f"## 概览\n\n{overview}\n\n"
        f"## 全文\n\n{full_text}\n"
    )


class TestParseDocument:
    """``parse_document`` 字段解析与区间切分。"""

    def test_parses_title_and_metadata(self) -> None:
        text = _sample_doc()
        entry = parse_document(text)
        assert entry is not None
        assert entry.title == "用户:编程偏好"
        assert entry.category == "user"
        assert entry.updated == "2026-08-16"
        assert entry.source == "对话 2026-08-10、2026-08-12"
        assert entry.summary == "偏好 Python、类型注解、简洁命名。"

    def test_overview_and_full_split(self) -> None:
        text = _sample_doc()
        entry = parse_document(text)
        assert entry is not None
        assert "类型注解" in entry.overview
        assert "## 概览" not in entry.overview
        assert "## 全文" not in entry.overview
        assert "2026-08-10" in entry.full_text
        assert "2026-08-12" in entry.full_text
        assert "## 全文" not in entry.full_text

    def test_missing_title_returns_none(self) -> None:
        text = "> 分类:user · 更新:2026-08-16\n\n## 概览\n\nx\n"
        assert parse_document(text) is None

    def test_missing_category_returns_none(self) -> None:
        text = "# 标题\n\n> 更新:2026-08-16\n\n## 概览\n\nx\n"
        assert parse_document(text) is None

    def test_empty_text_returns_none(self) -> None:
        assert parse_document("") is None

    def test_missing_overview_section_empty_string(self) -> None:
        text = "# 标题\n\n> 分类:user · 更新:2026-08-16\n\n## 全文\n\n内容\n"
        entry = parse_document(text)
        assert entry is not None
        assert entry.overview == ""
        assert "内容" in entry.full_text

    def test_missing_full_section_empty_string(self) -> None:
        text = "# 标题\n\n> 分类:user · 更新:2026-08-16\n\n## 概览\n\n仅概览\n"
        entry = parse_document(text)
        assert entry is not None
        assert entry.overview == "仅概览"
        assert entry.full_text == ""

    def test_summary_optional(self) -> None:
        text = "# 标题\n\n> 分类:user · 更新:2026-08-16\n\n## 概览\n\nx\n"
        entry = parse_document(text)
        assert entry is not None
        assert entry.summary == ""


class TestBuildIndex:
    """``build_index`` 索引生成。"""

    def _make_entries(self) -> list[MemoryEntry]:
        return [
            MemoryEntry(
                title="用户:编程偏好",
                category="user",
                slug="programming-preference",
                summary="偏好 Python、类型注解。",
                updated="2026-08-16",
                overview="",
                full_text="",
            ),
            MemoryEntry(
                title="项目:部署环境",
                category="project",
                slug="deployment-env",
                summary="Windows 本机,start_dev.py 启动。",
                updated="2026-08-15",
                overview="",
                full_text="",
            ),
        ]

    def test_contains_groups_links_summaries(self) -> None:
        text = build_index(self._make_entries(), _CATEGORIES)
        assert "# 记忆索引" in text
        assert "## 用户" in text
        assert "## 项目" in text
        assert "[用户:编程偏好](user/programming-preference.md)" in text
        assert "偏好 Python、类型注解。" in text
        assert "## 决策" not in text
        assert "## 主题" not in text

    def test_empty_category_omitted(self) -> None:
        text = build_index(self._make_entries(), _CATEGORIES)
        # decision/topic 无条目应省略
        assert "## 决策" not in text
        assert "## 主题" not in text

    def test_chinese_category_labels(self) -> None:
        text = build_index(self._make_entries(), _CATEGORIES)
        # user→用户、project→项目
        assert "## 用户" in text
        assert "## 项目" in text

    def test_empty_entries_just_header(self) -> None:
        text = build_index([], _CATEGORIES)
        assert "# 记忆索引" in text
        assert "## " not in text  # 无分组节

    def test_updated_date_in_header(self) -> None:
        text = build_index(self._make_entries(), _CATEGORIES)
        assert "> 更新:" in text


class TestReadEntryFile:
    """``read_entry_file`` 文件级读取与降级。"""

    def test_reads_md_and_injects_slug(self, tmp_path: Path) -> None:
        path = tmp_path / "user" / "slug.md"
        path.parent.mkdir(parents=True)
        path.write_text(_sample_doc(), encoding="utf-8")
        entry = read_entry_file(path)
        assert entry is not None
        assert entry.slug == "slug"
        assert entry.title == "用户:编程偏好"

    def test_skips_tmp_file(self, tmp_path: Path) -> None:
        path = tmp_path / "user" / "slug.md.tmp"
        path.parent.mkdir(parents=True)
        path.write_text(_sample_doc(), encoding="utf-8")
        assert read_entry_file(path) is None

    def test_skips_index_md(self, tmp_path: Path) -> None:
        path = tmp_path / "index.md"
        path.write_text(_sample_doc(), encoding="utf-8")
        assert read_entry_file(path) is None

    def test_non_md_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "user" / "slug.txt"
        path.parent.mkdir(parents=True)
        path.write_text(_sample_doc(), encoding="utf-8")
        assert read_entry_file(path) is None

    def test_non_utf8_degrades_gracefully(self, tmp_path: Path) -> None:
        path = tmp_path / "user" / "bad.md"
        path.parent.mkdir(parents=True)
        # 写入非法 UTF-8 bytes
        path.write_bytes(b"# \xff\xfe title\n\n> \xc3\x28 bad\n")
        # errors="replace" 不抛;解析可能得到部分内容或 None,但绝不崩。
        entry = read_entry_file(path)
        # 只要不抛异常即可接受(可能返回带替换字符的 entry 或 None)。
        assert entry is None or isinstance(entry, MemoryEntry)


class TestScanEntries:
    """``scan_entries`` 目录扫描与白名单。"""

    def _setup_dir(self, base: Path) -> None:
        (base / "user").mkdir(parents=True)
        (base / "project").mkdir(parents=True)
        (base / "unknown").mkdir(parents=True)
        (base / "user" / "a.md").write_text(_sample_doc(title="A"), encoding="utf-8")
        (base / "user" / "b.md").write_text(
            _sample_doc(title="B", category="user", summary="B summary", updated="2026-08-17"),
            encoding="utf-8",
        )
        (base / "project" / "p.md").write_text(
            _sample_doc(title="P", category="project", summary="P summary"), encoding="utf-8"
        )
        # 白名单外分类
        (base / "unknown" / "x.md").write_text(
            _sample_doc(title="X", category="unknown"), encoding="utf-8"
        )
        # .tmp 文件
        (base / "user" / "c.md.tmp").write_text(_sample_doc(title="C"), encoding="utf-8")
        # index.md
        (base / "index.md").write_text("# 记忆索引\n", encoding="utf-8")

    def test_only_whitelist_categories(self, tmp_path: Path) -> None:
        self._setup_dir(tmp_path)
        entries = scan_entries(tmp_path, _CATEGORIES)
        cats = {e.category for e in entries}
        assert cats == {"user", "project"}
        assert all(e.category != "unknown" for e in entries)

    def test_skips_tmp_and_index(self, tmp_path: Path) -> None:
        self._setup_dir(tmp_path)
        entries = scan_entries(tmp_path, _CATEGORIES)
        slugs = {e.slug for e in entries}
        assert "c" not in slugs  # .tmp skipped
        assert "index" not in slugs

    def test_slug_injected_from_filename(self, tmp_path: Path) -> None:
        self._setup_dir(tmp_path)
        entries = scan_entries(tmp_path, _CATEGORIES)
        slugs = {e.slug for e in entries}
        assert "a" in slugs
        assert "b" in slugs
        assert "p" in slugs

    def test_ordering_by_category_then_updated_desc(self, tmp_path: Path) -> None:
        self._setup_dir(tmp_path)
        entries = scan_entries(tmp_path, _CATEGORIES)
        # user 在 project 前(白名单顺序);user 内 b(2026-08-17)在 a 前
        assert entries[0].category == "user"
        assert entries[0].slug == "b"
        assert entries[1].slug == "a"
        assert entries[2].category == "project"

    def test_nonexistent_base_returns_empty(self, tmp_path: Path) -> None:
        entries = scan_entries(tmp_path / "nope", _CATEGORIES)
        assert entries == []
