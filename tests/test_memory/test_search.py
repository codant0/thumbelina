"""字符 2-gram 检索与 L0 注入选择测试(设计文档 §7.2、§13 任务 14)。

覆盖:
  - 中文 2-gram:``托管``命中``自托管``(score>0)、``数据库``精确匹配。
  - 英文:``database``匹配、``DB``相对低分。
  - 命中排序 top-K、零分不返回、``top_k<=0`` 空。
  - ``select_for_injection``:全量 vs top-K(token cap 阈值)。
"""

from __future__ import annotations

from thumbelina.memory.models import MemoryEntry
from thumbelina.memory.search import search_entries, select_for_injection


def _e(
    title: str,
    category: str,
    slug: str,
    summary: str,
    *,
    updated: str = "2026-08-16",
) -> MemoryEntry:
    return MemoryEntry(
        title=title,
        category=category,
        slug=slug,
        summary=summary,
        updated=updated,
        overview="",
        full_text="",
    )


class TestChineseNgram:
    """中文 2-gram 打分场景。"""

    def test_tuoguan_hits_zituoguan_positive(self) -> None:
        entries = [
            _e("主题:自托管", "topic", "self-hosting", "关注自托管服务与数据主权。"),
            _e("用户:编程偏好", "user", "prog", "偏好 Python。"),
        ]
        hits = search_entries(entries, "托管", top_k=8)
        assert hits
        # 自托管条目应命中且得分 > 0
        assert any(h.slug == "self-hosting" for h in hits)
        assert all(h.score > 0.0 for h in hits)

    def test_shujuku_exact_match(self) -> None:
        entries = [
            _e("项目:数据库选型", "project", "db", "已选 SQLite 作为数据库。"),
            _e("主题:自托管", "topic", "self-hosting", "关注自托管服务。"),
        ]
        hits = search_entries(entries, "数据库", top_k=8)
        assert hits
        # 数据库条目命中
        db_hits = [h for h in hits if h.slug == "db"]
        assert db_hits
        # 自托管条目不应因"库"字误伤为高分(但允许低分出现;关键是 db 排前)
        assert hits[0].slug == "db"


class TestEnglish:
    """英文分词与匹配。"""

    def test_database_match(self) -> None:
        entries = [
            _e("Project: DB choice", "project", "db", "Chose SQLite as the database."),
            _e("Topic: hosting", "topic", "host", "Self-hosting interest."),
        ]
        hits = search_entries(entries, "database", top_k=8)
        assert hits
        assert hits[0].slug == "db"

    def test_db_short_relatively_lower(self) -> None:
        entries = [
            _e("Project: DB choice", "project", "db", "Chose SQLite as the database."),
            _e("Project: database config", "project", "dbcfg", "database configuration details."),
        ]
        hits = search_entries(entries, "database", top_k=8)
        assert hits
        # 两个都含 database,但 dbcfg 的 summary 含 database 更直接
        # 断言两个都命中且 dbcfg 排序不低于 db(更精确匹配)
        slugs = [h.slug for h in hits]
        assert "dbcfg" in slugs
        assert "db" in slugs
        # dbcfg 的分数应 >= db(因为 dbcfg summary 中 database 是独立 token)
        dbcfg_score = next(h.score for h in hits if h.slug == "dbcfg")
        db_score = next(h.score for h in hits if h.slug == "db")
        assert dbcfg_score >= db_score


class TestSortingAndEdge:
    """命中排序与边界。"""

    def test_topk_respected(self) -> None:
        entries = [
            _e("A", "user", "a", "偏好 Python 编程"),
            _e("B", "user", "b", "偏好 Python 类型"),
            _e("C", "user", "c", "偏好 Python 简洁"),
        ]
        hits = search_entries(entries, "Python", top_k=2)
        assert len(hits) == 2

    def test_topk_zero_returns_empty(self) -> None:
        entries = [_e("A", "user", "a", "偏好 Python")]
        assert search_entries(entries, "Python", top_k=0) == []

    def test_zero_score_not_returned(self) -> None:
        entries = [
            _e("A", "user", "a", "偏好 Python"),
            _e("B", "user", "b", "完全无关的内容 xyz"),
        ]
        hits = search_entries(entries, "Python", top_k=8)
        slugs = [h.slug for h in hits]
        assert "a" in slugs
        # "完全无关的内容 xyz" 与 Python 零分,不应返回
        assert "b" not in slugs

    def test_empty_query_returns_empty(self) -> None:
        entries = [_e("A", "user", "a", "偏好 Python")]
        assert search_entries(entries, "", top_k=8) == []
        assert search_entries(entries, "   ", top_k=8) == []

    def test_empty_entries_returns_empty(self) -> None:
        assert search_entries([], "Python", top_k=8) == []

    def test_descending_score_order(self) -> None:
        entries = [
            _e("Low", "user", "low", "数据库管理"),
            _e("High", "user", "high", "数据库设计数据库"),
        ]
        hits = search_entries(entries, "数据库", top_k=8)
        assert len(hits) >= 2
        assert hits[0].score >= hits[1].score


class TestSelectForInjection:
    """``select_for_injection``:全量 vs top-K。"""

    def test_full_injection_when_under_cap(self) -> None:
        entries = [
            _e("A", "user", "a", "短摘要"),
            _e("B", "user", "b", "短摘要二"),
        ]
        # 大 cap,全量返回
        selected = select_for_injection(entries, "query", index_token_cap=10000, top_k=8)
        assert len(selected) == 2
        assert {e.slug for e in selected} == {"a", "b"}

    def test_topk_when_over_cap(self) -> None:
        # 构造大索引超过 cap
        entries = [
            _e(f"条目{i}", "user", f"slug-{i}", f"偏好 Python 编程类型注解简洁命名第{i}条")
            for i in range(20)
        ]
        selected = select_for_injection(entries, "Python", index_token_cap=50, top_k=3)
        # 超 cap 时按 search top-K 返回
        assert len(selected) <= 3
        assert len(selected) > 0

    def test_empty_entries_returns_empty(self) -> None:
        assert select_for_injection([], "q", index_token_cap=600, top_k=8) == []
