"""Skill API routes."""

from __future__ import annotations

import re
from collections import defaultdict

from fastapi import APIRouter, Depends

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent

router = APIRouter(tags=["skills"])

# Category extraction patterns: keyword -> category label
_CATEGORY_PATTERNS: list[tuple[str, str]] = [
    (r"代码|编程|code|program|debug|开发", "编程开发"),
    (r"文档|写作|翻译|write|document|translate", "文档写作"),
    (r"分析|数据|analysis|data|统计", "数据分析"),
    (r"搜索|查询|search|query|查找", "搜索查询"),
    (r"文件|file|路径|path|目录", "文件操作"),
    (r"网络|web|http|api|请求", "网络请求"),
    (r"安全|security|auth|加密|认证", "安全认证"),
    (r"调度|schedule|定时|cron|timer", "任务调度"),
    (r"聊天|对话|chat|conversation|沟通", "对话交互"),
    (r"学习|learn|train|模型|model", "学习训练"),
]


def _categorize_skill(name: str, description: str) -> str:
    """Extract a category label from the skill name and description."""
    text = f"{name} {description}".lower()
    for pattern, category in _CATEGORY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return "通用技能"


@router.get("/skills")
async def list_skills(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> list[dict]:
    """List all saved skills.

    Returns an empty list when the skill engine is not initialized.
    """
    if agent.skill_engine and agent.skill_engine.repository:
        skills = await agent.skill_engine.repository.list_all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "trigger_conditions": s.trigger_conditions,
                "steps": s.steps,
                "version": s.version,
                "success_rate": s.success_rate,
            }
            for s in skills
        ]
    return []


@router.get("/skills/stats")
async def skill_stats(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> dict:
    """Return skill usage statistics for dream visualization.

    Returns an empty structure when the skill engine is not initialized.
    """
    if not (agent.skill_engine and agent.skill_engine.repository):
        return {
            "total": 0,
            "timeline": [],
            "top_skills": [],
            "categories": [],
        }

    skills = await agent.skill_engine.repository.list_all()
    total = len(skills)

    # --- Timeline: group by creation date (YYYY-MM-DD) ---
    date_buckets: dict[str, list[dict]] = defaultdict(list)
    for s in skills:
        date_key = s.created_at.strftime("%Y-%m-%d") if s.created_at else "unknown"
        date_buckets[date_key].append({
            "id": s.id,
            "name": s.name,
            "success_rate": round(s.success_rate, 2),
        })
    timeline = [
        {"date": date, "skills": skill_list}
        for date, skill_list in sorted(date_buckets.items())
    ]

    # --- Top skills by version (proxy for maturity / usage iterations) ---
    sorted_skills = sorted(skills, key=lambda s: (s.version, s.success_rate), reverse=True)
    top_skills = [
        {
            "id": s.id,
            "name": s.name,
            "version": s.version,
            "success_rate": round(s.success_rate, 2),
        }
        for s in sorted_skills[:10]
    ]

    # --- Categories ---
    cat_counts: dict[str, int] = defaultdict(int)
    for s in skills:
        cat = _categorize_skill(s.name, s.description)
        cat_counts[cat] += 1
    categories = [
        {"name": cat, "count": count}
        for cat, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "total": total,
        "timeline": timeline,
        "top_skills": top_skills,
        "categories": categories,
    }


@router.get("/compositions")
async def list_compositions(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> list[dict]:
    """List all skill compositions.

    Returns an empty list when the composition engine is not initialized.
    """
    if agent.composition_engine:
        compositions = await agent.composition_engine.composition_repo.list_all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "skill_ids": c.skill_ids,
                "trigger_patterns": c.trigger_patterns,
                "usage_count": c.usage_count,
                "created_at": c.created_at.isoformat(),
            }
            for c in compositions
        ]
    return []
