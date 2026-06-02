"""Skill extractor for learning loop."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from thumbelina.llm.base import LLMProvider
from thumbelina.skills.models import Skill

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """分析以下对话，如果用户的问题得到了满意的解决，提取一个可复用的技能。
返回JSON格式：
{
  "name": "技能名称（简短英文snake_case）",
  "description": "技能描述",
  "trigger_conditions": ["触发条件1", "触发条件2"],
  "steps": ["步骤1", "步骤2"]
}
如果没有可提取的技能，返回空JSON对象：{}"""


class SkillExtractor:
    """Extracts reusable skills from successful conversations.

    Parameters
    ----------
    llm_provider:
        The LLM provider to use for skill extraction.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    async def extract(self, messages: list[dict[str, Any]]) -> Skill | None:
        """Extract a skill from conversation messages.

        Parameters
        ----------
        messages:
            List of message dicts with 'role' and 'content' keys.

        Returns
        -------
        Skill | None
            Extracted skill, or None if no skill could be extracted.
        """
        if not messages:
            return None

        try:
            conversation_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in messages
            )
            prompt = [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
            response = await self.llm_provider.chat(prompt)

            data = json.loads(response)
            if not data or "name" not in data:
                return None

            return Skill(
                id=str(uuid.uuid4()),
                name=data["name"],
                description=data.get("description", ""),
                trigger_conditions=data.get("trigger_conditions", []),
                steps=data.get("steps", []),
            )
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to extract skill", exc_info=True)
            return None
