"""压缩策略抽象与共享辅助函数。

压缩节点（entry → compress → agent）在检查点消息的预估 token 用量达到
``window × context.compress.threshold`` 时调用
:class:`ContextCompressor`。每个策略都遵循同一契约（设计文档 四.5）：

- 压缩到至多 ``window_tokens × LOW_WATERMARK``（50% 低水位），
  避免压缩在接下来的每一轮都反复触发；
- 绝不把 ``AIMessage(tool_calls)`` 与其 ``ToolMessage`` 回复拆开 ——
  增删均以原子单元为单位进行（见 :func:`group_atomic_units`）；
- 返回的序列写回图状态，因此检查点存储器会把压缩后的历史
  固定下来供下一轮使用。
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from thumbelina.rag.retrieval.context_formatter import estimate_tokens

# 低水位：最多压缩到窗口的 50%，让后续轮次可以继续追加，
# 而不会立即再次触发压缩。
LOW_WATERMARK = 0.5

# 承载模型推理的内容块类型；Anthropic 会拒绝重放的、thinking 块
# 丢失签名的 assistant 轮次（HTTP 400）。
_THINKING_BLOCK_TYPES = ("thinking", "redacted_thinking", "reasoning")

# 图像内容块的固定 token 占位（GPT-4V 基线，设计文档 §3.2/Task B4）：
# base64 无法按文本估算视觉开销，每张图按固定值计入，
# 否则压缩阈值会因图像块被当成空文本而失真。
IMAGE_BLOCK_TOKEN_PLACEHOLDER = 765


def message_text(message: BaseMessage) -> str:
    """从消息的 ``content`` 中提取可估算的文本。

    同时处理纯字符串内容与结构化内容块（text/thinking 字典，
    例如 Anthropic），使用量估算同样覆盖块式内容的 assistant 轮次。
    图像块不含文本，其固定开销由 :func:`estimate_messages_tokens`
    单独计入（本函数保持纯文本口径）。
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("thinking") or ""
                parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _image_block_count(content: object) -> int:
    """统计消息 ``content`` 中标准图像内容块（``type == "image"``）的数量。"""
    if not isinstance(content, list):
        return 0
    return sum(1 for block in content if isinstance(block, dict) and block.get("type") == "image")


def estimate_messages_tokens(messages: Sequence[BaseMessage]) -> int:
    """估算 *messages* 的总 token 用量。

    复用 RAG 的
    :func:`~thumbelina.rag.retrieval.context_formatter.estimate_tokens`
    估算器（CJK ≈ 2 tokens/字符，其他 ≈ 0.25 tokens/字符）——对窗口
    预算控制来说足够准确，且与 formatter 共享，保证两层口径一致。
    结构化 content 中的每个图像内容块按
    :data:`IMAGE_BLOCK_TOKEN_PLACEHOLDER`（GPT-4V 基线占位）固定计入。
    """
    return sum(
        estimate_tokens(message_text(message))
        + _image_block_count(message.content) * IMAGE_BLOCK_TOKEN_PLACEHOLDER
        for message in messages
    )


def group_atomic_units(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """将 *messages* 切分为原子单元。

    携带 ``tool_calls`` 的 ``AIMessage`` 会与其后紧跟的 ``ToolMessage``
    回复（按 ``tool_call_id`` 匹配）归为一组，因此一个单元只能整体
    删除或整体保留。这保证了 ``ToolMessage`` 永远不会失去拥有它的
    assistant 轮次 —— 提供商会拒绝未配对的工具结果（例如 Anthropic 400）。
    其余消息各自构成单元素单元。
    """
    units: list[list[BaseMessage]] = []
    index = 0
    total = len(messages)
    while index < total:
        message = messages[index]
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            unit: list[BaseMessage] = [message]
            expected = {
                call.get("id")
                for call in message.tool_calls
                if isinstance(call, dict) and call.get("id")
            }
            cursor = index + 1
            while cursor < total:
                candidate = messages[cursor]
                if not isinstance(candidate, ToolMessage):
                    break
                if expected and candidate.tool_call_id not in expected:
                    break
                unit.append(candidate)
                cursor += 1
            units.append(unit)
            index = cursor
        else:
            units.append([message])
            index += 1
    return units


#: 悬空 tool_calls 修复时注入的占位 ``ToolMessage`` 内容。
#: 被中断的轮次可能在检查点里留下没有任何工具响应的 assistant 工具调用；
#: OpenAI 兼容端点会以 400 拒绝这种序列（``insufficient tool messages``）。
INTERRUPTED_TOOL_PLACEHOLDER = "[工具调用被中断，未返回结果]"


def _tool_call_ids(message: AIMessage) -> list[str]:
    """收集一条 assistant 消息声明的全部 ``tool_call_id``（去重、保序）。

    同时涵盖 ``tool_calls``、``invalid_tool_calls`` 与
    ``additional_kwargs["tool_calls"]`` —— 某些 OpenAI 兼容端点流式返回的
    工具调用可能只落在后者里，但发送时仍会被当作 ``tool_calls`` 带上，
    因此修复配对时必须一并计入。
    """
    ids: list[str] = []

    def _collect(calls: object) -> None:
        if isinstance(calls, list):
            for call in calls:
                cid = call.get("id") if isinstance(call, dict) else None
                if cid and cid not in ids:
                    ids.append(cid)

    _collect(getattr(message, "tool_calls", None))
    _collect(getattr(message, "invalid_tool_calls", None))
    additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict):
        _collect(additional.get("tool_calls"))
    return ids


def ensure_tool_pairing(messages: list[BaseMessage]) -> list[BaseMessage]:
    """修复序列中的 ``tool_calls``/``ToolMessage`` 配对不变量。

    OpenAI 兼容端点要求：携带 ``tool_calls`` 的 assistant 消息之后必须紧跟
    能覆盖**每一个** ``tool_call_id`` 的 tool 消息；否则以 400 拒绝。
    流式轮次若在 assistant 产出 ``tool_calls`` 之后、tools 节点执行之前被
    中断，检查点里就会留下悬空状态，且之后每一轮都会原样重放
    （用户重发也无法自愈）。本函数在每轮 LLM 调用前无条件执行：

    - 为缺失响应的 ``tool_call_id`` 注入占位 ``ToolMessage`` —— 保留
      assistant 的工具调用意图，同时满足端点配对要求；
    - 丢弃孤儿 ``ToolMessage`` —— 前面没有声明对应 ``tool_call_id`` 的
      assistant 消息，或与紧随其前的 ``tool_calls`` 不匹配。

    无需修复时返回**原列表对象**（调用方用 ``is`` 判断零改动），以便
    保留纯追加前缀（provider 前缀缓存）；有修复时返回新列表。保留的
    消息沿用原对象（从而保留 id），使状态更新可以是最小的增删。
    """
    result: list[BaseMessage] = []
    changed = False
    index = 0
    total = len(messages)
    while index < total:
        message = messages[index]
        if isinstance(message, AIMessage):
            call_ids = _tool_call_ids(message)
            if call_ids:
                result.append(message)
                index += 1
                answered: set[str] = set()
                call_ids_set = set(call_ids)
                # 收集紧随其后的 ToolMessage 响应；不匹配的属于孤儿，丢弃。
                while index < total:
                    candidate = messages[index]
                    if not isinstance(candidate, ToolMessage):
                        break
                    if candidate.tool_call_id in call_ids_set:
                        result.append(candidate)
                        answered.add(candidate.tool_call_id)
                    else:
                        changed = True
                    index += 1
                # 为缺失的 tool_call_id 补占位响应。
                for cid in call_ids:
                    if cid not in answered:
                        result.append(
                            ToolMessage(content=INTERRUPTED_TOOL_PLACEHOLDER, tool_call_id=cid)
                        )
                        changed = True
                continue
        if isinstance(message, ToolMessage):  # 孤儿：无 owner assistant。
            changed = True
            index += 1
            continue
        result.append(message)
        index += 1
    return messages if not changed else result


def strip_thinking_blocks(message: AIMessage) -> AIMessage:
    """返回移除了 thinking/reasoning 内容块的 *message*。

    压缩后某个 assistant 轮次可能落到序列开头；重放丢失签名的过期
    thinking 块会让 Anthropic 返回 HTTP 400，因此防御性地将其剥离。
    纯字符串内容或不含 thinking 块的消息原样返回（同一对象）。
    """
    content = message.content
    if not isinstance(content, list):
        return message
    kept = [
        block
        for block in content
        if not (isinstance(block, dict) and block.get("type") in _THINKING_BLOCK_TYPES)
    ]
    if len(kept) == len(content):
        return message
    if not kept:
        return message.model_copy(update={"content": ""})
    return message.model_copy(update={"content": kept})


def leading_system_unit_count(units: list[list[BaseMessage]]) -> int:
    """统计仅由 ``SystemMessage`` 构成的前导原子单元数量。

    会话级头部（角色提示词 + 首轮用户画像）必须在整个会话期间保持
    稳定，因此每个策略都保护这段前导序列免于删除/摘要。
    """
    count = 0
    while count < len(units) and all(isinstance(m, SystemMessage) for m in units[count]):
        count += 1
    return count


def flatten_units(units: list[list[BaseMessage]]) -> list[BaseMessage]:
    """把原子单元展平回单条消息序列。"""
    return [message for unit in units for message in unit]


def truncate_text_to_tokens(text: str, budget_tokens: int, marker: str = "…") -> str:
    """截断 *text*，使其不超过 *budget_tokens* 个预估 token。

    文本被截断时追加 *marker*；marker 自身的 token 开销也被计入，
    因此结果永远不会超出预算。当连 marker 都放不下时返回 ``""``。
    用作 LLM 调用的硬性输入截断保护（摘要分批、过大的摘要）。
    """
    if estimate_tokens(text) <= budget_tokens:
        return text
    if budget_tokens <= 0:
        return ""
    ratio = budget_tokens / max(estimate_tokens(text), 1)
    cutoff = max(1, int(len(text) * ratio))
    result = text[:cutoff]
    # 按字符比例截断对 CJK/ASCII 混合文本只是近似（估算器也有下限），
    # 因此在加上 marker 后仍超出预算时逐步回退 —— 返回的字符串
    # 永远不会超出。
    while result and estimate_tokens(result + marker) > budget_tokens:
        result = result[:-1]
    return result + marker


def strip_first_assistant_thinking(messages: list[BaseMessage]) -> list[BaseMessage]:
    """若存在，则剥离第一条 assistant 消息中的 thinking 块。

    压缩可能把某条 ``AIMessage`` 提升到（或接近）序列头部。Anthropic
    要求重放轮次的 thinking 块保持完整，而删除后无法保证这一点，
    因此移除第一条 assistant 消息的 thinking 块。其后的 assistant 消息
    不受影响（就本防御而言，它们前面的工具/用户轮次仍然提供了所需的
    顺序保证）。

    未剥离任何内容时原样返回原列表。
    """
    for position, message in enumerate(messages):
        if isinstance(message, AIMessage):
            stripped = strip_thinking_blocks(message)
            if stripped is message:
                break
            result = list(messages)
            result[position] = stripped
            return result
    return messages


@dataclass(frozen=True)
class CompressionResult:
    """单次压缩的诊断结果。

    策略直接返回压缩后的序列；本容器供需要连同载荷一起拿到
    压缩前后用量数据的调用方（压缩节点、测试、指标）使用。
    """

    messages: list[BaseMessage]
    tokens_before: int
    tokens_after: int

    @property
    def saved_tokens(self) -> int:
        """本次压缩释放的 token 数。"""
        return self.tokens_before - self.tokens_after


class ContextCompressor(abc.ABC):
    """上下文压缩策略的基类。

    实现把超预算的消息序列压缩到至多
    ``window_tokens × LOW_WATERMARK`` 个 token，同时保持
    ``AIMessage(tool_calls)``/``ToolMessage`` 配对完整。新策略只需
    继承本类并通过
    :func:`thumbelina.agent.compression.factory.register_compressor` 注册。
    """

    #: 策略注册时使用的配置名
    #: （``context.compress.strategy``）。
    name: ClassVar[str] = ""

    @abc.abstractmethod
    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """返回 *messages* 的压缩替代序列。

        Parameters
        ----------
        messages:
            来自图状态的当前完整消息序列。
        window_tokens:
            当前模型的上下文窗口，单位为 token。返回的序列应占用至多
            ``window_tokens × LOW_WATERMARK``。

        Returns
        -------
        list[BaseMessage]
            压缩后的序列。保留的消息必须沿用原对象（从而保留 id），
            使状态更新可以是纯追加删除；替换消息（例如摘要）是新对象。
        """
        raise NotImplementedError


def compression_stats(
    before: Sequence[BaseMessage], after: Sequence[BaseMessage]
) -> CompressionResult:
    """构建用于日志/指标的 :class:`CompressionResult`。"""
    return CompressionResult(
        messages=list(after),
        tokens_before=estimate_messages_tokens(before),
        tokens_after=estimate_messages_tokens(after),
    )
