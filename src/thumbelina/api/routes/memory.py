"""REST routes for the Markdown分层记忆子系统(见设计文档 §7/§9)。

所有数据端点在 service 不可用时返回 503;``GET /status`` 始终 200。
``search``/``read`` 端点套用从 ``app.state`` 取得的全局 ``RateLimiter``
(与 ``_RateLimitMiddleware`` 同一实例,按客户端 IP 计数)。
``category``/``slug`` 路径参数经 :func:`paths._resolve` 预校验,非法
返回 400;条目不存在返回 404。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from thumbelina.api.deps import get_memory_service
from thumbelina.memory.exceptions import MemoryEntryNotFoundError, MemoryServiceError
from thumbelina.memory.paths import _resolve
from thumbelina.memory.service import MemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])

# 路由层角色门槛:与现有受保护路由一致,鉴权关闭时(user_roles 为空)
# 视为放行(由全局 ``_AuthMiddleware`` 控制)。
_MEMORY_ROLES: list[str] = ["admin", "user"]


def _check_roles(request: Request) -> None:
    """检查当前请求用户是否具备访问记忆路由的角色之一。

    未配置鉴权(user_roles 为空列表)时放行;否则要求至少命中
    ``_MEMORY_ROLES`` 中的一个。不满足返回 403。
    """
    user_roles: list[str] = getattr(request.state, "user_roles", [])
    if not user_roles:
        # 鉴权未启用(无 middleware)或匿名白名单路径放行
        return
    if not any(role in _MEMORY_ROLES for role in user_roles):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _enforce_rate_limit(request: Request) -> None:
    """对单个请求套用全局 RateLimiter(按客户端 IP);超限返回 429。

    复用 ``app.state.rate_limiter``(若存在);未配置则跳过,与全局
    rate_limit.enabled=False 行为一致。
    """
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


def _require_service(service: MemoryService | None) -> MemoryService:
    """服务不可用时抛 503;调用方依赖 :func:`get_memory_service`。"""
    if service is None:
        raise HTTPException(status_code=503, detail="Memory module is not available")
    return service


def _entry_to_dict(entry: Any) -> dict[str, str]:
    """把 :class:`MemoryEntry` 序列化为 API 响应 dict。"""
    return {
        "title": entry.title,
        "category": entry.category,
        "slug": entry.slug,
        "summary": entry.summary,
        "updated": entry.updated,
        "source": entry.source,
        "relpath": entry.relpath,
    }


@router.get("/status")
async def memory_status(request: Request) -> dict[str, Any]:
    """报告记忆模块可用性(始终 200,不抛 503)。"""
    _check_roles(request)
    service: MemoryService | None = getattr(request.app.state, "memory_service", None)
    if service is None:
        return {"enabled": False, "directory": None, "entries": 0}
    try:
        entries = await service.list_entries()
    except Exception:
        logger.warning("Memory status list_entries failed", exc_info=True)
        return {"enabled": True, "directory": str(service._base), "entries": 0}  # noqa: SLF001
    return {
        "enabled": True,
        "directory": str(service._base),  # noqa: SLF001
        "entries": len(entries),
    }


@router.get("/index")
async def get_index(
    request: Request,
    service: MemoryService | None = Depends(get_memory_service),
) -> dict[str, str]:
    """返回 L0 索引摘要全文(``index.md``)。"""
    _check_roles(request)
    _enforce_rate_limit(request)
    svc = _require_service(service)
    try:
        text = await svc.load_index_text()
    except Exception as exc:
        logger.warning("Memory index read failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"index": text}


@router.get("/entries")
async def list_entries(
    request: Request,
    service: MemoryService | None = Depends(get_memory_service),
) -> list[dict[str, str]]:
    """列出全部记忆条目(L0 摘要级,不含概览/全文)。"""
    _check_roles(request)
    svc = _require_service(service)
    try:
        entries = await svc.list_entries()
    except Exception as exc:
        logger.warning("Memory entries list failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [_entry_to_dict(e) for e in entries]


@router.get("/search")
async def search_memory(
    request: Request,
    q: str = Query(..., min_length=1, description="检索关键词或问题"),
    top_k: int = Query(8, ge=1, le=50, description="返回前 K 条命中"),
    service: MemoryService | None = Depends(get_memory_service),
) -> list[dict[str, Any]]:
    """分层全文检索:对 L0 标题/摘要 + L1 概览 + L2 正文分块打分。

    返回命中条目的标题/摘要/分数/命中字段/命中片段/更新时间/来源。
    """
    _check_roles(request)
    _enforce_rate_limit(request)
    svc = _require_service(service)
    try:
        hits = await svc.search_content(q, top_k=top_k)
    except Exception as exc:
        logger.warning("Memory search failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [
        {
            "title": h.title,
            "category": h.category,
            "slug": h.slug,
            "summary": h.summary,
            "score": round(h.score, 4),
            "matched_field": h.matched_field,
            "snippet": h.snippet,
            "updated": h.updated,
            "source": h.source,
        }
        for h in hits
    ]


@router.get("/{category}/{slug}")
async def read_entry(
    category: str,
    slug: str,
    request: Request,
    depth: str = Query("overview", pattern="^(overview|full)$"),
    service: MemoryService | None = Depends(get_memory_service),
) -> dict[str, Any]:
    """分层读取一条记忆(``depth=overview|full``)。"""
    _check_roles(request)
    _enforce_rate_limit(request)
    svc = _require_service(service)
    # 路径预校验(§8.3):非法 category/slug 直接 400,避免走到文件系统。
    try:
        _resolve(svc._base, category, slug)  # noqa: SLF001
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Illegal category/slug") from exc
    try:
        if depth == "overview":
            entry = await svc.read_overview(category, slug)
            return {
                **_entry_to_dict(entry),
                "overview": entry.overview,
                "full_text": "",
            }
        entry = await svc.read_full(category, slug)
        return {
            **_entry_to_dict(entry),
            "overview": entry.overview,
            "full_text": entry.full_text,
        }
    except MemoryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MemoryServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/refresh")
async def refresh_index(
    request: Request,
    service: MemoryService | None = Depends(get_memory_service),
) -> dict[str, Any]:
    """重建索引(扫描磁盘条目并重写 ``index.md``)。

    实现上调用 ``list_entries`` 触发一次扫描;``index.md`` 在任何写
    操作后由 service 自动重建,此处提供一个显式重建入口(对齐设计
    文档 §13 任务 10)。
    """
    _check_roles(request)
    svc = _require_service(service)
    try:
        # list_entries 走锁内扫描;再显式导出索引文本以触发 build_index。
        entries = await svc.list_entries()
        index_text = await svc.load_index_text()
    except Exception as exc:
        logger.warning("Memory refresh failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"entries": len(entries), "index": index_text}
