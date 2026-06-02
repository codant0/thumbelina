"""Natural language time parser."""

from __future__ import annotations

import re
from datetime import datetime

import dateparser


class TimeParser:
    """Parser for natural language time expressions.

    Supports Chinese and English time expressions including:
    - Relative: 明天, 后天, 下周, tomorrow, next week
    - With time: 明天下午3点, tomorrow at 3pm
    - Recurring: 每天, 每周, every day, every week
    """

    # Chinese recurring patterns
    RECURRING_PATTERNS = {
        "每天": "daily",
        "每日": "daily",
        "每周": "weekly",
        "每月": "monthly",
        "每年": "yearly",
        "every day": "daily",
        "every week": "weekly",
        "every month": "monthly",
        "every year": "yearly",
    }

    def parse(self, text: str) -> datetime | None:
        """Parse a natural language time expression.

        Parameters
        ----------
        text:
            Natural language time expression.

        Returns
        -------
        datetime | None
            Parsed datetime, or None if unparseable.
        """
        if not text or not text.strip():
            return None

        settings = {
            "RETURN_AS_TIMEZONE_AWARE": False,
        }

        result = dateparser.parse(text, settings=settings)
        return result

    def parse_recurring(self, text: str) -> dict | None:
        """Parse a recurring time expression.

        Parameters
        ----------
        text:
            Natural language recurring time expression (e.g., "每天早上9点").

        Returns
        -------
        dict | None
            Dict with 'frequency' and 'time' keys, or None if unparseable.
        """
        if not text or not text.strip():
            return None

        text_lower = text.strip().lower()

        for pattern, frequency in self.RECURRING_PATTERNS.items():
            if pattern in text_lower:
                # Try to extract the time part
                remaining = text_lower.replace(pattern, "").strip()
                time_part = self.parse(remaining) if remaining else None

                return {
                    "frequency": frequency,
                    "time": time_part or datetime.now(),
                }

        return None
