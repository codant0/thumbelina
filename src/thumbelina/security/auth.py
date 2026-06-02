"""Authentication service using JWT."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import jwt


@dataclass
class TokenPayload:
    """JWT token payload."""

    user_id: str
    roles: list[str] = field(default_factory=list)
    exp: float = 0.0


class AuthService:
    """Authentication service for JWT tokens.

    Parameters
    ----------
    secret_key:
        Secret key for signing tokens.
    """

    def __init__(self, secret_key: str) -> None:
        if len(secret_key.encode("utf-8")) < 32:
            raise ValueError(
                "secret_key must be at least 32 bytes. "
                f"Got {len(secret_key.encode('utf-8'))} bytes."
            )
        self.secret_key = secret_key

    def create_token(
        self,
        user_id: str,
        roles: list[str] | None = None,
        expires_seconds: int = 3600,
    ) -> str:
        """Create a JWT token.

        Parameters
        ----------
        user_id:
            ID of the user.
        roles:
            List of roles for the user.
        expires_seconds:
            Token expiration time in seconds.

        Returns
        -------
        str
            JWT token string.
        """
        payload = {
            "user_id": user_id,
            "roles": roles or [],
            "exp": time.time() + expires_seconds,
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def verify_token(self, token: str) -> TokenPayload | None:
        """Verify a JWT token.

        Parameters
        ----------
        token:
            JWT token string.

        Returns
        -------
        TokenPayload | None
            Token payload if valid, None if invalid or expired.
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return TokenPayload(
                user_id=payload["user_id"],
                roles=payload.get("roles", []),
                exp=payload.get("exp", 0),
            )
        except (jwt.InvalidTokenError, KeyError):
            return None
