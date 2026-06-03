"""Composition engine for creating, matching, and executing skill compositions."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from thumbelina.llm.base import LLMProvider
from thumbelina.skills.composition import SkillComposition
from thumbelina.skills.composition_repo import CompositionRepository
from thumbelina.skills.models import Skill
from thumbelina.skills.repository import SkillRepository

logger = logging.getLogger(__name__)

SUGGEST_PROMPT = """分析以下对话历史，建议可以组合成工作流的技能。

可用技能列表：
{skills_list}

对话历史：
{conversation_history}

请返回JSON格式的建议列表，每个建议包含：
{{
  "suggestions": [
    {{
      "name": "工作流名称",
      "description": "工作流描述",
      "skill_names": ["技能名称1", "技能名称2"],
      "trigger_patterns": ["触发模式1", "触发模式2"]
    }}
  ]
}}

如果没有可组合的技能，返回空列表：{{"suggestions": []}}"""


class CompositionEngine:
    """Engine for creating, matching, and executing skill compositions.

    Parameters
    ----------
    composition_repo:
        The composition repository for persistence.
    skill_repo:
        The skill repository for looking up skills.
    llm_provider:
        The LLM provider for suggesting compositions.
    """

    def __init__(
        self,
        composition_repo: CompositionRepository,
        skill_repo: SkillRepository,
        llm_provider: LLMProvider,
    ) -> None:
        self.composition_repo = composition_repo
        self.skill_repo = skill_repo
        self.llm_provider = llm_provider

    async def create_composition(
        self,
        skill_ids: list[str],
        name: str,
        description: str,
        trigger_patterns: list[str] | None = None,
    ) -> SkillComposition:
        """Create a new skill composition.

        Parameters
        ----------
        skill_ids:
            Ordered list of skill IDs to chain together.
        name:
            Name for the composition.
        description:
            Description of what the composition does.
        trigger_patterns:
            Optional trigger patterns for matching.

        Returns
        -------
        SkillComposition
            The created composition.
        """
        composition = SkillComposition(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            skill_ids=skill_ids,
            trigger_patterns=trigger_patterns or [],
        )
        await self.composition_repo.save(composition)
        return composition

    async def match_composition(self, user_input: str) -> SkillComposition | None:
        """Find a composition matching the user input.

        Parameters
        ----------
        user_input:
            The user's query.

        Returns
        -------
        SkillComposition | None
            The best matching composition, or None.
        """
        all_compositions = await self.composition_repo.list_all()
        if not all_compositions:
            return None

        user_lower = user_input.lower()

        # Keyword matching against trigger patterns
        for comp in all_compositions:
            for pattern in comp.trigger_patterns:
                if pattern.lower() in user_lower:
                    return comp
                # Check significant words (3+ chars)
                words = [w for w in pattern.lower().split() if len(w) >= 3]
                if words and all(w in user_lower for w in words):
                    return comp

        # Also match by composition name
        for comp in all_compositions:
            if comp.name.lower() in user_lower:
                return comp

        return None

    async def execute_composition(
        self,
        composition: SkillComposition,
        context: str,
        llm_provider: LLMProvider | None = None,
    ) -> str:
        """Execute a skill composition by chaining skills in sequence.

        Each skill's output becomes part of the context for the next skill.

        Parameters
        ----------
        composition:
            The composition to execute.
        context:
            The initial user context/input.
        llm_provider:
            Optional LLM provider override (uses the engine's default if not set).

        Returns
        -------
        str
            The combined result of executing all skills in the composition.
        """
        provider = llm_provider or self.llm_provider
        await self.composition_repo.increment_usage(composition.id)

        # Resolve skills from the ordered skill_ids
        skills: list[Skill] = []
        for sid in composition.skill_ids:
            skill = await self.skill_repo.get(sid)
            if skill is None:
                logger.warning("Skill %s not found in composition %s", sid, composition.id)
                continue
            skills.append(skill)

        if not skills:
            return f"Composition '{composition.name}' has no valid skills."

        # Chain skills: each skill produces context for the next
        accumulated_output = context
        results: list[str] = []

        for i, skill in enumerate(skills):
            steps_text = "\n".join(f"  {j + 1}. {step}" for j, step in enumerate(skill.steps))
            prompt_text = (
                f"技能组合 '{composition.name}' — 步骤 {i + 1}/{len(skills)}\n"
                f"当前技能: {skill.name}\n"
                f"描述: {skill.description}\n"
                f"步骤:\n{steps_text}\n\n"
                f"上一步输出/用户输入:\n{accumulated_output}\n\n"
                f"请根据以上技能步骤处理输入内容，输出结果。"
            )

            try:
                step_result = await provider.chat(
                    [
                        {"role": "user", "content": prompt_text},
                    ]
                )
                accumulated_output = step_result
                results.append(f"[步骤 {i + 1}] {skill.name}: {step_result}")
            except Exception:
                logger.warning(
                    "Skill '%s' failed in composition '%s'",
                    skill.name,
                    composition.name,
                    exc_info=True,
                )
                results.append(f"[步骤 {i + 1}] {skill.name}: 执行失败")
                break

        return "\n\n".join(results)

    async def suggest_compositions(
        self,
        conversation_history: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Use LLM to suggest skill compositions from conversation history.

        Parameters
        ----------
        conversation_history:
            List of message dicts with 'role' and 'content' keys.

        Returns
        -------
        list[dict[str, Any]]
            List of suggestion dicts with 'name', 'description',
            'skill_names', and 'trigger_patterns'.
        """
        all_skills = await self.skill_repo.list_all()
        if not all_skills:
            return []

        skills_list = "\n".join(f"- {s.name}: {s.description}" for s in all_skills)
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in conversation_history)

        prompt = SUGGEST_PROMPT.format(
            skills_list=skills_list,
            conversation_history=history_text,
        )

        try:
            import json

            response = await self.llm_provider.chat(
                [
                    {"role": "user", "content": prompt},
                ]
            )
            data = json.loads(response)
            return data.get("suggestions", [])
        except Exception:
            logger.warning("Failed to suggest compositions", exc_info=True)
            return []
