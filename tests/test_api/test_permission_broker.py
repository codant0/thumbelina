"""PermissionBroker unit tests — spec §5.3/§5.4."""

from __future__ import annotations

import asyncio

import pytest

from thumbelina.api.permission_broker import PermissionBroker


@pytest.mark.asyncio
async def test_resolve_wakes_waiter():
    b = PermissionBroker(timeout_seconds=5)
    rid = b.register("c1", {"calls": [{"call_id": "x"}]})
    task = asyncio.create_task(b.wait(rid))
    await asyncio.sleep(0)
    assert b.resolve(rid, [{"call_id": "x", "approved": True}]) is True
    assert await task == [{"call_id": "x", "approved": True}]


@pytest.mark.asyncio
async def test_timeout_settles_deny_all():
    b = PermissionBroker(timeout_seconds=0.05)
    rid = b.register("c1", {"calls": [{"call_id": "x"}]})
    assert await b.wait(rid) == [{"call_id": "x", "approved": False}]


@pytest.mark.asyncio
async def test_early_response_cached():
    b = PermissionBroker(timeout_seconds=5)
    rid = b.register("c1", {"calls": []})
    assert b.resolve(rid, [{"call_id": "x", "approved": False}]) is True
    assert await b.wait(rid) == [{"call_id": "x", "approved": False}]


def test_unknown_and_snapshot():
    b = PermissionBroker(timeout_seconds=5)
    assert b.resolve("nope", []) is False


@pytest.mark.asyncio
async def test_snapshot_and_clear():
    b = PermissionBroker(timeout_seconds=5)
    rid = b.register("c1", {"calls": []})
    assert b.snapshot("c1")["request_id"] == rid
    b.clear_conversation("c1")
    assert b.snapshot("c1") is None
