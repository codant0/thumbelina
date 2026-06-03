"""User profiler service for analyzing conversations and building user profiles."""

from __future__ import annotations

import json
import logging
from typing import Any

from thumbelina.llm.base import LLMProvider
from thumbelina.memory.user_profile_repo import UserProfileRepository

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """\
Analyze the following conversation and extract user profile information.
Return a JSON object with exactly these keys:

{
  "communication_style": "formal" | "casual" | "technical",
  "expertise_level": "beginner" | "intermediate" | "advanced",
  "preferences": [
    {"category": "<category>", "key": "<key>", "value": "<value>", "confidence": <0.0-1.0>}
  ],
  "topics_of_interest": ["<topic1>", "<topic2>"]
}

Rules:
- communication_style: "formal" if the user uses polite/structured language, "casual" if
  conversational/informal, "technical" if using domain jargon or precise terminology.
- expertise_level: assess based on the complexity of questions asked and terminology used.
- preferences: extract any explicit or implicit preferences (language, format, detail level, etc.).
- topics_of_interest: list the main topics discussed.
- confidence: 0.0 to 1.0, higher for explicit statements, lower for inferred.
- Return ONLY valid JSON, no markdown fences or extra text.
"""


class UserProfiler:
    """Analyzes conversation history to build and maintain user profiles.

    Parameters
    ----------
    llm_provider:
        The LLM provider to use for conversation analysis.
    profile_repo:
        The repository for persisting user profiles and preferences.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        profile_repo: UserProfileRepository,
    ) -> None:
        self.llm_provider = llm_provider
        self.profile_repo = profile_repo

    async def analyze_conversation(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
    ) -> dict[str, Any] | None:
        """Analyze a conversation to extract user profile information.

        Parameters
        ----------
        messages:
            List of message dicts with 'role' and 'content' keys.
        user_id:
            Identifier for the user.

        Returns
        -------
        dict[str, Any] | None
            The analysis result, or None on failure.
        """
        if not messages:
            return None

        try:
            conversation_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            prompt = [
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
            response = await self.llm_provider.chat(prompt)

            # Parse JSON response
            result = json.loads(response)

            # Persist profile updates
            await self._persist_analysis(user_id, result)

            return result
        except json.JSONDecodeError:
            logger.warning("Failed to parse profiler LLM response as JSON")
            return None
        except Exception:
            logger.warning("Failed to analyze conversation for profiling", exc_info=True)
            return None

    async def _persist_analysis(
        self,
        user_id: str,
        analysis: dict[str, Any],
    ) -> None:
        """Persist analysis results to the database.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        analysis:
            Parsed analysis result from the LLM.
        """
        try:
            # Update profile fields
            style = analysis.get("communication_style")
            level = analysis.get("expertise_level")

            await self.profile_repo.get_or_create_profile(user_id)

            if style or level:
                await self.profile_repo.update_profile(
                    user_id,
                    communication_style=style,
                    expertise_level=level,
                )

            # Upsert preferences
            for pref in analysis.get("preferences", []):
                category = pref.get("category", "general")
                key = pref.get("key", "")
                value = pref.get("value", "")
                confidence = pref.get("confidence", 0.5)
                if key and value:
                    await self.profile_repo.upsert_preference(
                        user_id=user_id,
                        category=category,
                        key=key,
                        value=value,
                        confidence_score=confidence,
                    )

            # Store topics of interest as preferences
            topics = analysis.get("topics_of_interest", [])
            for i, topic in enumerate(topics):
                await self.profile_repo.upsert_preference(
                    user_id=user_id,
                    category="topic",
                    key=f"interest_{i}",
                    value=topic,
                    confidence_score=0.7,
                )

        except Exception:
            logger.warning("Failed to persist user profile analysis", exc_info=True)

    async def get_user_context(
        self,
        user_id: str = "default",
    ) -> str | None:
        """Build a context string from the user's profile for injection into the agent.

        Parameters
        ----------
        user_id:
            Identifier for the user.

        Returns
        -------
        str | None
            A context string summarizing the user's profile, or None if no
            profile exists or on failure.
        """
        try:
            profile = await self.profile_repo.get_profile(user_id)
            if profile is None:
                return None

            preferences = await self.profile_repo.get_preferences(user_id)
            if not preferences and profile["communication_style"] == "casual":
                # Default profile with no meaningful data — skip
                return None

            parts: list[str] = []

            # Communication style and expertise
            style = profile["communication_style"]
            level = profile["expertise_level"]
            parts.append(f"User communication style: {style}. Expertise level: {level}.")

            # Group preferences by category
            by_category: dict[str, list[dict[str, Any]]] = {}
            for pref in preferences:
                cat = pref["category"]
                by_category.setdefault(cat, []).append(pref)

            # Topics of interest
            topics = by_category.get("topic", [])
            if topics:
                topic_values = [t["value"] for t in topics]
                parts.append(f"Topics of interest: {', '.join(topic_values)}.")

            # Other preferences
            for cat, prefs in sorted(by_category.items()):
                if cat == "topic":
                    continue
                pref_strs = [f"{p['key']}={p['value']}" for p in prefs[:5]]
                if pref_strs:
                    parts.append(f"Preferences ({cat}): {', '.join(pref_strs)}.")

            if not parts:
                return None

            return "User Profile:\n" + "\n".join(parts)

        except Exception:
            logger.warning("Failed to build user context", exc_info=True)
            return None

    async def update_profile(
        self,
        user_id: str,
        communication_style: str | None = None,
        expertise_level: str | None = None,
    ) -> dict[str, Any] | None:
        """Manually update a user's profile.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        communication_style:
            New communication style value.
        expertise_level:
            New expertise level value.

        Returns
        -------
        dict[str, Any] | None
            The updated profile, or None if not found.
        """
        try:
            await self.profile_repo.get_or_create_profile(user_id)
            return await self.profile_repo.update_profile(
                user_id,
                communication_style=communication_style,
                expertise_level=expertise_level,
            )
        except Exception:
            logger.warning("Failed to update user profile", exc_info=True)
            return None
