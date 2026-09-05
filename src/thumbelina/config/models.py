"""Pydantic configuration models for Thumbelina."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from thumbelina.channels.config import (  # noqa: F401
    ChannelsConfig,
    QQChannelConfig,
    WeChatChannelConfig,
)

_CONTEXT_WINDOW_PATTERN = re.compile(r"^(\d+)\s*([KM])?$", re.IGNORECASE)
_CONTEXT_WINDOW_MULTIPLIERS = {"K": 1_000, "M": 1_000_000}


def parse_context_window(value: str | int) -> int:
    """把上下文窗口规格解析为 token 数量。

    接受纯 token 数量（``200000`` 或 ``"200000"``），或带大小写不敏感的
    ``K``（千）/ ``M``（百万）token 后缀的数量，例如
    ``"128K"`` 或 ``"1M"``。

    Raises:
        ValueError: 如果规格畸形或为非正数。
    """
    if isinstance(value, bool):
        raise ValueError(f"Invalid context window: {value!r}")
    if isinstance(value, int):
        tokens = value
    elif isinstance(value, str):
        match = _CONTEXT_WINDOW_PATTERN.match(value.strip())
        if match is None:
            raise ValueError(
                f"Invalid context window {value!r}; expected a positive token count "
                "with an optional K/M suffix (e.g. '128K', '1M')"
            )
        suffix = (match.group(2) or "").upper()
        tokens = int(match.group(1)) * _CONTEXT_WINDOW_MULTIPLIERS.get(suffix, 1)
    else:
        raise ValueError(f"Invalid context window: {value!r}")
    if tokens <= 0:
        raise ValueError(f"Context window must be positive, got {value!r}")
    return tokens


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openai", min_length=1, description="LLM provider name")
    model: str = Field(default="gpt-4o", description="Model identifier")
    api_key: str = Field(default="", description="API key for the provider")
    base_url: str | None = Field(
        default=None,
        description="Custom API base URL for OpenAI-compatible providers",
    )
    request_timeout: float | None = Field(
        default=None,
        description="Timeout in seconds for each LLM request. None = no timeout.",
    )
    streaming_enabled: bool = Field(
        default=True,
        description="Enable streaming responses. When false, full response is sent at once.",
    )
    role: str = Field(
        default="assistant",
        min_length=1,
        description=(
            "Role persona name; the matching prompt file under "
            "prompts/roles/<role>.md is injected as the system prompt."
        ),
    )
    context_window: str = Field(
        default="128K",
        description=(
            "Default context window of the provider model. Supports K (thousand) / "
            "M (million) token suffixes, case-insensitive. Endpoints may override "
            "this via their own context_window field."
        ),
    )

    @field_validator("context_window", mode="before")
    @classmethod
    def _validate_context_window(cls, value: Any) -> str:
        parse_context_window(value)  # 格式无效时抛出 ValueError
        return str(value).strip()

    @property
    def context_window_tokens(self) -> int:
        """归一化为 token 数量的上下文窗口。"""
        return parse_context_window(self.context_window)


class RepositoryConfig(BaseModel):
    """Repository/database configuration."""

    database_url: str = Field(
        default="sqlite:///thumbelina.db", description="Database connection URL"
    )
    attachments_directory: str = Field(
        default="attachments",
        description=(
            "Directory (relative to working directory) for uploaded image "
            "attachments; sharded yyyy/mm."
        ),
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )


class AuthConfig(BaseModel):
    """Authentication configuration.

    When ``secret_key`` is set, all API routes (except ``/health``)
    require a valid Bearer JWT token.

    When ``required_roles`` is non-empty, authenticated users must have
    at least one of the listed roles to access any protected route.
    """

    secret_key: str = Field(
        default="",
        description="Secret key for JWT token signing. Leave empty to disable auth.",
    )
    required_roles: list[str] = Field(
        default_factory=list,
        description=(
            "Global list of roles required to access protected routes. "
            "Leave empty to allow all authenticated users."
        ),
    )


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(default=False, description="Enable rate limiting")
    max_requests: int = Field(default=60, description="Max requests per window")
    window_seconds: int = Field(default=60, description="Time window in seconds")


class TodoConfig(BaseModel):
    """TODO module configuration (local Markdown files)."""

    enabled: bool = Field(default=True, description="Enable the TODO module")
    directory: str = Field(
        default="TODO",
        description="Directory for the Markdown files (todolist.md / notes.md)",
    )


class ContextCompressConfig(BaseModel):
    """用量接近窗口时应用的上下文压缩设置。"""

    strategy: Literal["sliding_window", "full_summary", "summary_recent"] = Field(
        default="summary_recent",
        description="Compression strategy used when the context nears the window",
    )
    threshold: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Fraction of the window (0, 1] at which compression triggers",
    )
    recent_turns: int = Field(
        default=6,
        ge=1,
        description="Number of recent turns kept verbatim by the summary_recent strategy",
    )


class ContextConfig(BaseModel):
    """会话上下文（检查点存储器）配置。"""

    compress: ContextCompressConfig = Field(default_factory=ContextCompressConfig)


class MemoryExtractConfig(BaseModel):
    """后台 LLM 抽取/改写配置（见设计文档 §10 extract 段）。"""

    enabled: bool = Field(default=True, description="启用后台 LLM 抽取/改写")
    on_user_message: bool = Field(
        default=True,
        description="仅对用户消息触发抽取,关闭则对所有消息触发",
    )
    max_input_tokens: int = Field(
        default=8000,
        ge=256,
        description="单次抽取输入 token 预算,超限时先截断全文再截断历史",
    )
    min_message_chars: int = Field(
        default=5,
        ge=0,
        description="用户消息低于该字符数不触发后台抽取(排除'好的/谢谢'等无信息量语气词)",
    )


class MemoryToolsConfig(BaseModel):
    """记忆工具暴露配置(见设计文档 §10 tools 段)。"""

    enabled: bool = Field(
        default=True,
        description="暴露 search_memory/read_memory/remember 工具给 Agent",
    )


class MemoryConfig(BaseModel):
    """基于 Markdown 文件系统的分层记忆配置(见设计文档 §10)。

    记忆以 Markdown 存于 ``directory`` 目录,索引为派生产物,
    分层按需加载(L0 摘要/L1 概览/L2 全文)省 token。本期单用户,
    ``user_id`` 固定 ``"default"``。
    """

    enabled: bool = Field(default=True, description="关闭后路由与注入整体禁用")
    directory: str = Field(
        default="MEMORY",
        description="Markdown 记忆目录,相对路径基于工作目录",
    )
    categories: list[str] = Field(
        default_factory=lambda: ["user", "project", "decision", "topic"],
        description="分类白名单,索引按此顺序分组;白名单外分类被忽略",
    )
    inject_index: bool = Field(
        default=True,
        description="每轮注入索引摘要(L0 triage)",
    )
    inject_top_k: int = Field(
        default=8,
        ge=1,
        description="索引超过 token 阈值时按相关性注入前 K 条",
    )
    index_token_cap: int = Field(
        default=3000,
        ge=32,
        description="索引摘要全量注入的 token 上限(estimate_tokens 口径)",
    )
    max_full_tokens: int = Field(
        default=4000,
        ge=128,
        description="read_full 单条全文注入上限,超限截断",
    )
    max_entries: int = Field(
        default=200,
        ge=1,
        description="记忆条目总量护栏",
    )
    max_total_bytes: int = Field(
        default=5_000_000,
        ge=1024,
        description="记忆目录总字节护栏",
    )
    extract: MemoryExtractConfig = Field(default_factory=MemoryExtractConfig)
    tools: MemoryToolsConfig = Field(default_factory=MemoryToolsConfig)


class WebSearchConfig(BaseModel):
    """网页搜索工具(web_search)配置。

    ``provider`` 决定搜索后端：``tavily`` 需要配置 ``api_key``，
    ``duckduckgo`` 无需任何密钥。
    """

    enabled: bool = Field(default=True, description="暴露 web_search 工具给 Agent")
    provider: Literal["tavily", "duckduckgo"] = Field(
        default="tavily",
        description="搜索后端：tavily(需 API key) 或 duckduckgo(免 key)",
    )
    api_key: str = Field(
        default="",
        description="Tavily API key，仅 provider=tavily 时使用",
    )


class ToolsConfig(BaseModel):
    """内置工具配置。当前仅实现 web_search 搜索后端策略。"""

    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class SchedulerConfig(BaseModel):
    """任务调度器配置（事件驱动定时任务，设计文档 §10）。

    全部字段有默认值：YAML 缺省该段时零行为差异。
    """

    enabled: bool = Field(
        default=True,
        description="是否启用内置任务调度器（关闭后任务路由 503/空列表）",
    )
    heartbeat_interval_seconds: int = Field(
        default=30,
        description="Heartbeat 巡检间隔（秒）",
    )
    missed_policy: Literal["mark", "run"] = Field(
        default="mark",
        description="错过处置策略：mark=标记 MISSED 终态 / run=立即补跑一次",
    )
    missed_grace_minutes: int = Field(
        default=5,
        description="超过触发时间多久才算“错过”的宽限期（分钟）",
    )
    stale_running_minutes: int = Field(
        default=10,
        description="RUNNING 任务卡住多久后判定为僵尸并置 FAILED（分钟）",
    )
    event_retention: int = Field(
        default=500,
        description="task_events 事件日志保留条数（Heartbeat 周期修剪）",
    )
    prompt_timeout_seconds: int = Field(
        default=300,
        description=(
            "prompt 模式任务后台执行的超时（秒）：LLM 调用超过该时长即按 "
            "'prompt timed out' 结算 FAILED（cron 保持 PENDING 等下一场次）"
        ),
    )
    default_channel: Literal["web", "wechat", "qq"] = Field(
        default="web",
        description="web 端创建任务未指定渠道时的默认交付渠道",
    )


class AppConfig(BaseModel):
    """Top-level application configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    repository: RepositoryConfig = Field(default_factory=RepositoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    todo: TodoConfig = Field(default_factory=TodoConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins. Use ['*'] for development only.",
    )
    plugin_dirs: list[str] = Field(
        default_factory=list,
        description="Directories to scan for plugins at startup",
    )
