/**
 * 聊天流内实时工具调用卡(设计 §5.1):由 WS ``tool_event`` 帧实时驱动,
 * 按 ``call_id`` 在同一 assistant 消息上 upsert。
 * ``args`` 为截断参数时后端下发 ``{"_truncated_json": "<json 字符串>"}``
 * 并置 ``argsTruncated``(契约冻结段);完整参数/结果事后在轨迹页查看。
 */
export interface ToolCall {
  call_id?: string
  name: string
  args: Record<string, unknown>
  result?: string
  status: 'running' | 'ok' | 'error' | 'interrupted'
  durationMs?: number
  resultTruncated?: boolean
  argsTruncated?: boolean
}

/**
 * WS 下行 ``{tool_event: …}`` 帧体(契约冻结):``phase`` 由后端 WS 层从
 * stream() 的 tool_start/tool_end 事件映射,其余字段原样透传。
 */
export interface ToolEventPayload {
  phase: 'start' | 'end'
  call_id: string
  name?: string
  args?: Record<string, unknown>
  args_truncated?: boolean
  duration_ms?: number
  is_error?: boolean
  result_preview?: string
  result_truncated?: boolean
}

export type ThinkingEffort = 'low' | 'medium' | 'high'

export type SubagentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

/**
 * Lifecycle payload of a subagent, pushed from the backend over WS as
 * `{ subagent_event: SubagentEventPayload, conversation_id }`. Mirrors
 * `SubagentEvent` on the Python side. Type is one of:
 *   subagent.started | subagent.completed | subagent.failed | subagent.cancelled
 */
export interface SubagentEventPayload {
  type: string
  id: string
  task: string
  status: SubagentStatus
  result?: string | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

/**
 * 消息附件引用(设计 §3.2/§4.2):后端持久化在 messages.attachments JSON 列,
 * 随历史回放原样下发;图片 URL 由前端按 id 自拼(`/api/v1/attachments/{id}`),
 * 不存 base64、不存 url。首版仅 user 角色使用。
 *
 * ``mime`` 为可选:历史回放的条目恒有 mime(§4.2),而发送时的乐观插入
 * 直接复用上行引用 —— 其元数据虽来自上传响应,但类型上不强制存在。
 */
export interface AttachmentRef {
  /** 服务端分配的附件 id */
  id: string
  /** image/png | image/jpeg | image/webp | image/gif */
  mime?: string
  width?: number
  height?: number
  alt?: string
}

/**
 * WS 上行帧携带的附件输入(设计 §4.1):协议只需 id/alt,帧构造时会剥离其余
 * 字段;mime/width/height 为本地就绪附件随带的元数据(来自上传响应),供
 * 乐观插入的消息直接作为 AttachmentRef 渲染。
 */
export interface SendAttachmentInput {
  id: string
  alt?: string
  mime?: string
  width?: number
  height?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  toolCalls?: ToolCall[]
  thinking?: string
  attachments?: AttachmentRef[]
}

export interface Conversation {
  id: string
  name?: string | null
  pinned?: boolean
  mode?: 'chat' | 'coder'
  workspace?: string | null
  endpoint_id?: string | null
  model?: string | null
  knowledge_base_id?: string | null
  role?: string | null
  thinking_enabled?: boolean
  thinking_effort?: ThinkingEffort
  created_at: string
  updated_at: string
  summary?: string | null
  messages?: Message[]
}

export interface ChatRequest {
  message: string
  conversation_id?: string
  /** 附件引用列表;与 message 至少一项非空(协议 §4.1)。 */
  attachments?: SendAttachmentInput[]
}

export interface ChatResponse {
  response: string
  conversation_id: string
}
