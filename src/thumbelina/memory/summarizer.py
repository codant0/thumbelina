"""Conversation summarizer using LLM."""

from __future__ import annotations

import logging
from typing import Any

from thumbelina.llm.base import LLMProvider

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = "请用1-2句话总结以下对话的主要内容，简洁概括用户的问题和得到的回答。"


class Summarizer:
    """Generates conversation summaries using an LLM.

    Parameters
    ----------
    llm_provider:
        The LLM provider to use for generating summaries.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    async def generate(self, messages: list[dict[str, Any]]) -> str:
        """Generate a summary for a list of messages.

        Parameters
        ----------
        messages:
            List of message dicts with 'role' and 'content' keys.

        Returns
        -------
        str
            The generated summary, or empty string on failure.
        """
        if not messages:
            return ""

        try:
            conversation_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            prompt = [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
            return await self.llm_provider.chat(prompt)
        except Exception:
            logger.warning("Failed to generate summary", exc_info=True)
            return ""
