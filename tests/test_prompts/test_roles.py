"""Tests for thumbelina.prompts.roles."""

from __future__ import annotations

import pytest

from thumbelina.prompts.roles import get_role_prompt, list_roles


class TestListRoles:
    def test_builtin_roles_available(self):
        roles = list_roles()
        assert "assistant" in roles
        assert "coder" in roles

    def test_roles_sorted(self):
        roles = list_roles()
        assert roles == sorted(roles)


class TestGetRolePrompt:
    @pytest.mark.parametrize("role", ["assistant", "coder"])
    def test_builtin_prompts_non_empty(self, role: str):
        prompt = get_role_prompt(role)
        assert isinstance(prompt, str)
        assert prompt.strip()

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="Unknown role"):
            get_role_prompt("no-such-role")
