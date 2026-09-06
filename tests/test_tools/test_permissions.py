"""tests/test_tools/test_permissions.py"""
import pytest

from thumbelina.tools.permissions import (
    LADDER,
    PermissionMode,
    effective_mode,
    get_permission_mode,
    has_approver,
    parse_mode,
    set_approval_context,
    set_permission_mode,
)


def test_contextvar_defaults_fail_closed():
    assert get_permission_mode() is PermissionMode.READ_ONLY
    assert has_approver() is False


def test_setters_roundtrip():
    set_permission_mode(PermissionMode.FULL_ACCESS)
    set_approval_context(True)
    assert get_permission_mode() is PermissionMode.FULL_ACCESS
    assert has_approver() is True


def test_parse_mode():
    assert parse_mode("auto") is PermissionMode.AUTO
    assert parse_mode("bogus") is None
    assert parse_mode(None) is None


@pytest.mark.parametrize("mode,expected", [
    (PermissionMode.READ_ONLY, PermissionMode.READ_ONLY),
    (PermissionMode.WORKSPACE_WRITE, PermissionMode.WORKSPACE_WRITE),
    (PermissionMode.GLOBAL_WRITE, PermissionMode.WORKSPACE_WRITE),
    (PermissionMode.FULL_ACCESS, PermissionMode.WORKSPACE_WRITE),
])
def test_effective_mode_unattended_caps_at_workspace_write(mode, expected):
    assert effective_mode(mode, unattended=True, has_workspace=True) is expected


def test_effective_mode_unattended_no_workspace_drops_to_read_only():
    assert effective_mode(PermissionMode.FULL_ACCESS, unattended=True, has_workspace=False) \
        is PermissionMode.READ_ONLY


def test_effective_mode_auto_exempt_and_attended_passthrough():
    assert effective_mode(PermissionMode.AUTO, unattended=True, has_workspace=False) \
        is PermissionMode.AUTO
    assert effective_mode(PermissionMode.GLOBAL_WRITE, unattended=False, has_workspace=False) \
        is PermissionMode.GLOBAL_WRITE


def test_ladder_strictly_increasing():
    assert LADDER[0] is PermissionMode.READ_ONLY and LADDER[-1] is PermissionMode.AUTO
