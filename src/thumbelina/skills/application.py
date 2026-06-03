"""Skill application engine for applying learned skills."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from thumbelina.llm.base import LLMProvider
from thumbelina.skills.models import Skill
from thumbelina.skills.repository import SkillRepository

if TYPE_CHECKING:
    from thumbelina.memory.feedback_repo import FeedbackRepository

logger = logging.getLogger(__name__)

MATCH_PROMPT = """以下是用户的问题：
{user_input}

以下是可用的技能列表：
{skills_list}

请返回最匹配的技能名称，如果没有匹配的技能，返回空字符串。只返回技能名称，不要其他内容。"""


class SkillApplicationEngine:
    """Engine for finding and applying skills to user queries.

    Parameters
    ----------
    repository:
        The skill repository to search in.
    llm_provider:
        The LLM provider for skill matching.
    feedback_repo:
        Optional feedback repository for adjusting scores based on user feedback.
    """

    def __init__(
        self,
        repository: SkillRepository,
        llm_provider: LLMProvider,
        feedback_repo: FeedbackRepository | None = None,
    ) -> None:
        self.repository = repository
        self.llm_provider = llm_provider
        self.feedback_repo = feedback_repo

    async def _adjust_score_by_feedback(self, skill_id: str, base_score: float) -> float:
        """Adjust a skill's matching score based on user feedback ratings.

        Higher-rated skills receive a score boost, lower-rated skills receive
        a penalty.  If no feedback exists for the skill the base score is
        returned unchanged.

        Parameters
        ----------
        skill_id:
            ID of the skill to look up feedback for.
        base_score:
            The original matching score.

        Returns
        -------
        float
            The adjusted score.
        """
        if self.feedback_repo is None:
            return base_score

        try:
            stats = await self.feedback_repo.get_average_rating(skill_id=skill_id)
            avg = stats["average_rating"]
            count = stats["count"]

            # Need at least 1 feedback to adjust
            if count == 0:
                return base_score

            # Scale adjustment by count (more feedback = more confidence).
            # Max adjustment magnitude is 0.2 (achieved at avg=5 or avg=1 with
            # enough data).
            # adjustment = (avg - 3) / 2 * min(count, 5) / 5 * 0.2
            confidence = min(count, 5) / 5.0
            adjustment = (avg - 3.0) / 2.0 * confidence * 0.2
            return base_score + adjustment
        except Exception:
            logger.warning("Failed to get feedback for skill %s", skill_id, exc_info=True)
            return base_score

    async def find_matching_skills(self, user_input: str) -> list[Skill]:
        """Find skills matching the user input.

        When a ``feedback_repo`` is configured, matching scores are adjusted
        based on historical user feedback ratings so that higher-rated skills
        surface first.

        Parameters
        ----------
        user_input:
            The user's query.

        Returns
        -------
        list[Skill]
            List of matching skills, ordered by relevance.
        """
        all_skills = await self.repository.list_all()
        if not all_skills:
            return []

        # Simple keyword matching first — build (skill, base_score) pairs
        matched: list[tuple[Skill, float]] = []
        user_lower = user_input.lower()
        for skill in all_skills:
            for condition in skill.trigger_conditions:
                # Check if the full condition phrase appears
                if condition.lower() in user_lower:
                    matched.append((skill, 1.0))
                    break
                # Check if significant words (3+ chars) match
                words = [w for w in condition.lower().split() if len(w) >= 3]
                if words and all(w in user_lower for w in words):
                    matched.append((skill, 0.8))
                    break

        if matched:
            # Adjust scores by feedback
            adjusted: list[tuple[Skill, float]] = []
            for skill, base_score in matched:
                new_score = await self._adjust_score_by_feedback(skill.id, base_score)
                adjusted.append((skill, new_score))
            # Sort by adjusted score descending
            adjusted.sort(key=lambda x: x[1], reverse=True)
            return [s for s, _ in adjusted]

        # Fall back to LLM matching
        try:
            skills_list = "\n".join(
                f"- {s.name}: {s.description} (触发条件: {', '.join(s.trigger_conditions)})"
                for s in all_skills
            )
            prompt = MATCH_PROMPT.format(
                user_input=user_input,
                skills_list=skills_list,
            )
            response = await self.llm_provider.chat(
                [
                    {"role": "user", "content": prompt},
                ]
            )
            skill_name = response.strip()
            if skill_name:
                for skill in all_skills:
                    if skill.name == skill_name:
                        return [skill]
        except Exception:
            logger.warning("LLM skill matching failed", exc_info=True)

        return []

    async def apply_skill(self, skill: Skill, user_input: str) -> str:
        """Generate context from a skill for the agent.

        Parameters
        ----------
        skill:
            The skill to apply.
        user_input:
            The user's original query.

        Returns
        -------
        str
            Context string to help the agent respond.
        """
        steps_text = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(skill.steps))
        return f"参考技能: {skill.name}\n描述: {skill.description}\n步骤:\n{steps_text}"

    async def record_usage(self, skill_id: str, success: bool) -> None:
        """Record a skill usage and update success rate.

        Parameters
        ----------
        skill_id:
            ID of the skill used.
        success:
            Whether the usage was successful.
        """
        skill = await self.repository.get(skill_id)
        if not skill:
            return

        # Simple moving average update
        weight = 0.1
        if success:
            skill.success_rate = skill.success_rate * (1 - weight) + weight
        else:
            skill.success_rate = skill.success_rate * (1 - weight)

        await self.repository.save(skill)
