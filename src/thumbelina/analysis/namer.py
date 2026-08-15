"""Auto-naming of conversations from the first few user messages."""

from __future__ import annotations

import logging
import re
from typing import Any

from thumbelina.llm.base import LLMProvider

logger = logging.getLogger(__name__)

NAME_PROMPT = (
    "请根据下面的用户消息，为这个会话生成一个简短的标题（不超过20个字，不要包含引号、句号或换行）。"
    "标题应概括用户的核心问题或主题，直接输出标题文本，不要任何额外说明。"
)

# Trigger auto-naming after this many user messages have been exchanged.
AUTO_NAME_AFTER_MESSAGES = 1

_MAX_INPUT_CHARS = 2000
_MAX_NAME_LEN = 50
_QUOTE_RE = re.compile(r"[\"'“”‘’「」『』]")


class ConversationNamer:
    """Generates short conversation titles from early user messages.

    Parameters
    ----------
    llm_provider:
        The LLM provider used to produce the title.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    async def suggest_name(self, messages: list[dict[str, Any]]) -> str:
        """Return a candidate title for a conversation given its messages.

        Returns an empty string if no title could be produced.
        """
        user_texts = [m["content"] for m in messages if m.get("role") == "user"]
        if not user_texts:
            return ""

        joined = " ".join(str(t) for t in user_texts)[:_MAX_INPUT_CHARS]
        try:
            prompt = [
                {"role": "system", "content": NAME_PROMPT},
                {"role": "user", "content": joined},
            ]
            raw = await self.llm_provider.chat(prompt)
        except Exception:
            logger.warning("Failed to generate conversation name", exc_info=True)
            return ""

        name = self._clean(raw)
        return name

    @staticmethod
    def _clean(raw: str) -> str:
        name = (raw or "").strip()
        # Strip surrounding quotes and line breaks the model sometimes adds.
        name = name.splitlines()[0].strip() if name else ""
        name = _QUOTE_RE.sub("", name)
        name = name.strip().strip("。.")
        if len(name) > _MAX_NAME_LEN:
            name = name[:_MAX_NAME_LEN].rstrip()
        return name
