"""Role API routes.

Exposes the available agent persona roles so the frontend can populate
a role selector dropdown.
"""

from __future__ import annotations

from fastapi import APIRouter

from thumbelina.prompts.roles import list_roles

router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=list[str])
async def get_roles() -> list[str]:
    """Return the names of all available agent roles, sorted alphabetically."""
    return list_roles()
