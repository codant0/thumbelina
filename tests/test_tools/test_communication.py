"""用户沟通工具迁移测试(Task 5)。"""
from __future__ import annotations

import pytest

from thumbelina.tools.base import ToolCategory
from thumbelina.tools.communication import (
    CommunicationTool,
    NotifyUserByChannelTool,
    make_communication_tools,
)


class FakeChannel:
    def __init__(self, last_user_id="u9", result="ok"):
        self.last_user_id, self.result, self.sent = last_user_id, result, None

    async def send_message(self, target, message):
        self.sent = (target, message)
        return self.result


class FakeAgent:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, name):
        return self.channel if name == "wechat" else None

    def list_channels(self):
        return ["wechat"] if self.channel else []


@pytest.mark.asyncio
async def test_notify_falls_back_to_last_user():
    ch = FakeChannel()
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(ch))
    out = await t._arun(message="hi")
    assert ch.sent == ("u9", "hi")
    assert "Message sent to user 'u9'" in out


@pytest.mark.asyncio
async def test_notify_unknown_channel_lists_available():
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(FakeChannel()))
    out = await t._arun(message="hi", channel="qq")
    assert "Available channels: wechat" in out


@pytest.mark.asyncio
async def test_notify_no_recipient():
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(FakeChannel(last_user_id=None)))
    out = await t._arun(message="hi")
    assert "no recent user" in out


@pytest.mark.asyncio
async def test_receipt_unconfirmed_when_none():
    ch = FakeChannel(result=None)
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(ch))
    out = await t._arun(message="hi", user_id="u1")
    assert "delivery not confirmed" in out


def test_category_and_factory():
    assert NotifyUserByChannelTool().category == ToolCategory.COMMUNICATION
    assert len(make_communication_tools(FakeAgent(FakeChannel()))) == 1


def test_base_class_and_schema():
    assert issubclass(NotifyUserByChannelTool, CommunicationTool)
    # 显式 args_schema:字段名与旧 @tool 函数参数名逐字一致
    assert set(NotifyUserByChannelTool().args_schema.model_fields) == {
        "message",
        "channel",
        "user_id",
    }
    assert NotifyUserByChannelTool().name == "notify_user_by_channel"
