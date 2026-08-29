"""用户沟通工具:向人主动发消息(spec §4.3)。

从 ``agent/graph.py`` 的 ``_make_channel_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 生命周期。
channels 仍在调用时查注册表(持 agent 引用),保持热注册语义。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class _NotifyUserByChannelArgs(BaseModel):
    message: str = Field(..., description="The message text to send.")
    channel: str = Field(
        default="wechat",
        description='Channel name, e.g. "wechat" or "qq". Defaults to "wechat".',
    )
    user_id: str = Field(
        default="",
        description="Target user ID. If empty, the channel's most recent user is used.",
    )


class CommunicationTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.COMMUNICATION
    agent_ref: Any = None

    def resolve_target(self, channel_name: str, user_id: str) -> tuple[Any, str, str | None]:
        """返回 (channel|None, target|None, error_message|None)。"""
        ch = self.agent_ref.get_channel(channel_name)
        if ch is None:
            available = ", ".join(sorted(self.agent_ref.list_channels())) or "none"
            return (
                None,
                "",
                f"Channel '{channel_name}' is not registered. Available channels: {available}.",
            )
        target = user_id.strip() or getattr(ch, "last_user_id", None)
        if not target:
            return (
                None,
                "",
                (
                    f"Channel '{channel_name}' has no recent user to notify; "
                    "provide an explicit user_id."
                ),
            )
        return ch, target, None

    @staticmethod
    def format_receipt(channel: str, target: str, delivered: Any, exc: Any = None) -> str:
        if exc is not None:
            return f"Failed to send message via '{channel}': {exc}"
        if delivered is None:
            return (
                f"Message handed to channel '{channel}' for user '{target}'; "
                "delivery not confirmed."
            )
        return f"Message sent to user '{target}' via channel '{channel}'."


class NotifyUserByChannelTool(CommunicationTool):
    name: str = "notify_user_by_channel"
    description: str = (
        "Send a proactive message to a user via an IM channel.\n\n"
        "Use this to notify the user (task completion, reminders, follow-ups)\n"
        "instead of only replying in the current conversation. Defaults to the\n"
        "WeChat channel and to that channel's most recent user.\n\n"
        "Args:\n"
        "    message: The message text to send.\n"
        '    channel: Channel name, e.g. "wechat" or "qq". Defaults to "wechat".\n'
        "    user_id: Target user ID. If empty, the channel's most recent user\n"
        "        is used."
    )
    args_schema: type[BaseModel] = _NotifyUserByChannelArgs

    async def _execute(self, message: str, channel: str = "wechat", user_id: str = "") -> str:
        ch, target, err = self.resolve_target(channel, user_id)
        if err:
            return err
        try:
            result = await ch.send_message(target, message)
        except Exception as exc:
            return self.format_receipt(channel, target, None, exc=exc)
        return self.format_receipt(channel, target, result)


def make_communication_tools(agent_ref: Any) -> list[BaseTool]:
    """返回封装 ``ThumbelinaAgent`` 渠道注册的沟通工具(迁移自 ``_make_channel_tools``)。"""
    return [NotifyUserByChannelTool(agent_ref=agent_ref)]
