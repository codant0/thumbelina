"""Data processing tools for the Thumbelina agent."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter

from langchain_core.tools import tool


@tool
async def parse_json(text: str) -> str:
    """Parse JSON text and return a formatted summary (keys, types, structure)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"Error: Invalid JSON - {exc}"

    def _summarize(obj: object, indent: int = 0) -> str:
        prefix = "  " * indent
        if isinstance(obj, dict):
            if not obj:
                return f"{prefix}(empty object)"
            lines: list[str] = []
            for key, value in obj.items():
                type_name = type(value).__name__
                if isinstance(value, dict):
                    lines.append(f"{prefix}{key}: object ({len(value)} keys)")
                    lines.append(_summarize(value, indent + 1))
                elif isinstance(value, list):
                    lines.append(f"{prefix}{key}: array ({len(value)} items)")
                    if value:
                        lines.append(_summarize(value[0], indent + 1))
                else:
                    lines.append(f"{prefix}{key}: {type_name} = {value!r}")
            return "\n".join(lines)
        if isinstance(obj, list):
            if not obj:
                return f"{prefix}(empty array)"
            return _summarize(obj[0], indent)
        return f"{prefix}{type(obj).__name__} = {obj!r}"

    summary = _summarize(data)
    return f"Type: {type(data).__name__}\n{summary}"


@tool
async def parse_csv(text: str) -> str:
    """Parse CSV text and return column names, row count, and first few rows."""
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except csv.Error as exc:
        return f"Error: Invalid CSV - {exc}"

    if not rows:
        return "Empty CSV - no data"

    headers = rows[0]
    data_rows = rows[1:]
    preview_count = min(5, len(data_rows))

    lines = [
        f"Columns ({len(headers)}): {', '.join(headers)}",
        f"Rows: {len(data_rows)}",
        "",
        f"First {preview_count} rows:",
    ]
    for i, row in enumerate(data_rows[:preview_count]):
        lines.append(f"  [{i}] {', '.join(row)}")

    return "\n".join(lines)


@tool
async def analyze_text(text: str) -> str:
    """Analyze text: word count, line count, character count, top 10 frequent words."""
    if not text:
        return "Empty text"

    lines = text.splitlines()
    # Split on whitespace for word count
    words = re.findall(r"[a-zA-Z0-9一-鿿]+", text.lower())
    word_freq = Counter(words).most_common(10)

    result_lines = [
        f"Characters: {len(text)}",
        f"Words: {len(words)}",
        f"Lines: {len(lines)}",
        "",
        "Top 10 words:",
    ]
    for word, count in word_freq:
        result_lines.append(f"  {word}: {count}")

    return "\n".join(result_lines)


@tool
async def search_text(text: str, pattern: str) -> str:
    """Search for a regex pattern in text and return all matches with line numbers."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"Error: Invalid regex pattern - {exc}"

    lines = text.splitlines()
    matches: list[str] = []
    for line_num, line in enumerate(lines, start=1):
        for match in compiled.finditer(line):
            matches.append(f"  Line {line_num}, Col {match.start() + 1}: {match.group()}")

    if not matches:
        return f"No matches found for pattern: {pattern}"

    header = f"Found {len(matches)} match(es) for pattern: {pattern}"
    return header + "\n" + "\n".join(matches)
