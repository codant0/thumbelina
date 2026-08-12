"""Role prompt registry.

Each role is a ``<role>.md`` file under ``prompts/roles/``. Adding a new
role only requires dropping a new markdown file into that directory.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files

_ROLES_DIR = files("thumbelina.prompts") / "roles"


def list_roles() -> list[str]:
    """Return the names of all available roles, sorted alphabetically."""
    return sorted(
        entry.name.removesuffix(".md")
        for entry in _ROLES_DIR.iterdir()
        if entry.is_file() and entry.name.endswith(".md")
    )


@cache
def get_role_prompt(role: str) -> str:
    """Return the system prompt for *role*.

    Raises
    ------
    ValueError
        If no prompt file exists for the given role.
    """
    resource = _ROLES_DIR / f"{role}.md"
    if not resource.is_file():
        available = ", ".join(list_roles())
        raise ValueError(f"Unknown role: {role!r}. Available roles: {available}")
    return resource.read_text(encoding="utf-8").strip()
