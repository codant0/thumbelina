"""字符 2-gram 检索与 L0 注入选择(见设计文档 §7.2)。

检索打分用字符 2-gram 的 Jaccard/Dice 系数 + 精确 token 重叠加权;
中文按字符 2-gram(无空格分词,纯子串重叠会"短词命中长词"如"托管"
误命中"自托管"),英文按空格分词 + 小写化。零向量、确定性强。
``estimate_tokens`` 复用 ``rag/retrieval/context_formatter.py``
(CJK≈2/字符),用于判断 ``index_token_cap`` 内全量与否。
"""

from __future__ import annotations

import re
import unicodedata

from thumbelina.memory.models import MemoryEntry, MemoryHit
from thumbelina.rag.retrieval.context_formatter import estimate_tokens

_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK 统一表意文字
    (0x3400, 0x4DBF),  # CJK 扩展 A
    (0x3040, 0x30FF),  # 平假名 + 片假名
    (0xF900, 0xFAFF),  # CJK 兼容表意文字
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    """提取字符 n-gram(CJK 与非 CJK 混合,统一按字符滑窗)。"""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def _tokenize(text: str) -> set[str]:
    """英文按空格分词 + 小写化;CJK 字符按单字拆分作为 token。

    用于精确 token 重叠加权(区别于 2-gram 模糊匹配)。
    """
    tokens: set[str] = set()
    cur: list[str] = []
    for ch in text:
        if _is_cjk(ch) or unicodedata.east_asian_width(ch) in ("W", "F"):
            if cur:
                tokens.add("".join(cur).lower())
                cur = []
            tokens.add(ch.lower())
        elif ch.isspace():
            if cur:
                tokens.add("".join(cur).lower())
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.add("".join(cur).lower())
    tokens.discard("")
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return (2.0 * inter) / (len(a) + len(b))


def _score(query: str, candidate: str) -> float:
    """字符 2-gram Dice 与 Jaccard 取均值 + 精确 token 重叠加权。"""
    q_gram = _char_ngrams(query, 2)
    c_gram = _char_ngrams(candidate, 2)
    gram = (_dice(q_gram, c_gram) + _jaccard(q_gram, c_gram)) / 2.0
    q_tok = _tokenize(query)
    c_tok = _tokenize(candidate)
    # 精确 token 重叠加权:query 中有多少比例的 token 命中候选
    tok = (len(q_tok & c_tok) / len(q_tok)) if q_tok else 0.0
    # 加权:gram 为主(0.7),精确 token 为辅(0.3)
    return gram * 0.7 + tok * 0.3


def search_entries(
    entries: list[MemoryEntry],
    query: str,
    top_k: int = 8,
) -> list[MemoryHit]:
    """对索引摘要做 n-gram 检索,返回 top-K 命中(按分数降序,确定性)。

    候选文本为 ``title + " " + summary``(L0 triage 口径)。
    ``top_k <= 0`` 时返回空列表;零分条目不返回。
    """
    if top_k <= 0 or not query.strip() or not entries:
        return []
    hits: list[MemoryHit] = []
    for e in entries:
        candidate = f"{e.title} {e.summary}"
        s = _score(query, candidate)
        if s <= 0.0:
            continue
        hits.append(
            MemoryHit(
                title=e.title,
                category=e.category,
                slug=e.slug,
                summary=e.summary,
                score=s,
                entry=e,
            )
        )
    # 确定性排序:分数降序,同分按 (category, slug) 升序
    hits.sort(key=lambda h: (-h.score, h.category, h.slug))
    return hits[:top_k]


def select_for_injection(
    entries: list[MemoryEntry],
    query: str,
    index_token_cap: int = 3000,
    top_k: int = 8,
) -> list[MemoryEntry]:
    """L0 注入选择:``estimate_tokens(全量索引) <= cap`` 时全量,否则 top-K。

    全量注入时按分类白名单顺序返回(scan_entries 已排好序的 entries);
    top-K 时按 :func:`search_entries` 的相关性排序返回。
    """
    if not entries:
        return []
    full_index = _format_index_text(entries)
    if estimate_tokens(full_index) <= index_token_cap:
        return list(entries)
    hits = search_entries(entries, query, top_k=top_k)
    return [h.entry for h in hits if h.entry is not None]


def _format_index_text(entries: list[MemoryEntry]) -> str:
    """把 entries 拼成索引摘要文本(用于 token 估算)。"""
    lines = [f"- [{e.title}]({e.relpath}) — {e.summary}" for e in entries]
    return "\n".join(lines)
