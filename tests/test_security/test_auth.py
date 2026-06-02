"""Tests for authentication module."""

from __future__ import annotations

import pytest

from thumbelina.security.auth import AuthService, TokenPayload


@pytest.fixture
def auth_service():
    """Create an AuthService."""
    return AuthService(secret_key="test-secret-key")


class TestAuthService:
    """Tests for the AuthService class."""

    def test_auth_service_class_exists(self):
        """AuthService should be importable."""
        assert AuthService is not None

    def test_auth_service_requires_secret_key(self):
        """Should accept a secret key."""
        service = AuthService(secret_key="my-secret")
        assert service.secret_key == "my-secret"

    def test_create_token(self, auth_service):
        """Should create a JWT token."""
        token = auth_service.create_token(user_id="user-1")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_token(self, auth_service):
        """Should verify a valid token."""
        token = auth_service.create_token(user_id="user-1")
        payload = auth_service.verify_token(token)

        assert payload is not None
        assert payload.user_id == "user-1"

    def test_verify_invalid_token(self, auth_service):
        """Should return None for invalid token."""
        payload = auth_service.verify_token("invalid-token")
        assert payload is None

    def test_verify_expired_token(self, auth_service):
        """Should return None for expired token."""
        token = auth_service.create_token(user_id="user-1", expires_seconds=-1)
        payload = auth_service.verify_token(token)
        assert payload is None

    def test_token_with_roles(self, auth_service):
        """Should include roles in token."""
        token = auth_service.create_token(user_id="user-1", roles=["admin"])
        payload = auth_service.verify_token(token)

        assert payload is not None
        assert "admin" in payload.roles

    def test_token_default_roles(self, auth_service):
        """Should default to empty roles."""
        token = auth_service.create_token(user_id="user-1")
        payload = auth_service.verify_token(token)

        assert payload is not None
        assert payload.roles == []


class TestTokenPayload:
    """Tests for the TokenPayload class."""

    def test_token_payload_class_exists(self):
        """TokenPayload should be importable."""
        assert TokenPayload is not None

    def test_token_payload_create(self):
        """Should create a TokenPayload."""
        payload = TokenPayload(user_id="user-1", roles=["admin"])
        assert payload.user_id == "user-1"
        assert payload.roles == ["admin"]
