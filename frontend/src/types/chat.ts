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
  /** 闸门裁决结果(spec §3.2);实时流与轨迹页共用 */
  verdict?: ToolCallVerdict
  /** 拒绝/标红原因规则键(spec §3.2 reason),i18n 映射文案 */
  reason?: string
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
  /** 闸门裁决结果(spec §3.2/§5.2):allowed/auto_allowed 正常执行;confirmed 用户批准;
   *  denied 用户拒绝或策略拒绝。 */
  verdict?: ToolCallVerdict
}

/** 闸门裁决枚举(spec §3.2):与轨迹页/卡片/工具栏徽标共用 */
export type ToolCallVerdict = 'allowed' | 'confirmed' | 'denied' | 'auto_allowed'

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

/** 工具在内容流中的锚点(设计 §5.3 修订):offset 为 tool_start 到达时
 *  已接收的内容字符数,渲染时按它把芯片穿插进文本流。仅实时消息携带
 *  (useWebSocket 当轮生成),历史回放消息无此字段、维持底部布局。 */
export interface ToolAnchor {
  callId: string
  offset: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  toolCalls?: ToolCall[]
  toolAnchors?: ToolAnchor[]
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
  /** 会话权限模式(spec §3.1 五档);默认 full_access */
  permission?: PermissionMode
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

/**
 * 会话权限模式(spec §3.1 五档,严格递增)。
 * 闸门与工具绑定过滤的输入;前端用此联合类型保证可见集与 PUT 路由一致。
 */
export type PermissionMode =
  | 'read_only'
  | 'workspace_write'
  | 'global_write'
  | 'full_access'
  | 'auto'

/** 闸门裁决输出:allow/confirm/deny 三态(spec §3.2) */
export type ToolCallDecision = 'allow' | 'confirm' | 'deny'

/** 闸门裁决附加的语义标签(供轨迹页/审批卡渲染) */
export type PermissionRisk = 'normal' | 'dangerous'

/**
 * WS 下行 ``{permission_request: {request_id, calls}}`` 帧体(spec §5.4)。
 * 后端 `interrupt(payload)` 时把 `calls` 原样下发;`request_id` 来自
 * `Interrupt.id`(langgraph 生成,稳定)。
 */
export interface PermissionCallPayload {
  call_id: string
  name: string
  args: Record<string, unknown>
  risk: PermissionRisk
  /** 稳定规则键(spec §3.2),如 `confirm.sudo`/`rule.protected_path`;
   *  前端按 key 在 i18n `permission.rule.*` 命名空间下查文案。 */
  reason: string
  /** 仅 run_shell 存在:归一化命令(折续行/剥注释,spec §4.6) */
  args_display?: string
}

export interface PermissionRequestPayload {
  request_id: string
  calls: PermissionCallPayload[]
}

/** WS 上行 ``{permission_response: {request_id, decisions}}`` 帧体 */
export interface PermissionDecision {
  call_id: string
  approved: boolean
}

export interface PermissionResponseFrame {
  request_id: string
  decisions: PermissionDecision[]
}

/** WS 下行 `pending_approval` 快照帧体 */
export interface PendingApprovalSnapshot {
  request_id: string
  calls: PermissionCallPayload[]
}


/* ---------- 共享 UI 工具 ---------- */

/** `global_write` -> `globalWrite`,与 i18n key 命名约定一致。
 *  PermissionSelector 依赖此映射 —— 抽到类型模块避免重复。 */
export function modeCamel(m: PermissionMode): string {
  return m.replace(/_([a-z])/g, (_match, c: string) => c.toUpperCase())
}

/** 五模式全量顺序(由弱到强)。PermissionSelector 用作下拉列表与可见集
 *  比较(chat 隐藏 workspace_write)。 */
export const ALL_PERMISSION_MODES: PermissionMode[] = [
  'read_only',
  'workspace_write',
  'global_write',
  'full_access',
  'auto',
]

/** chat 会话可见的模式(隐藏 workspace_write:chat 无工作区,选项无意义)。 */
export const CHAT_VISIBLE_PERMISSION_MODES: PermissionMode[] = [
  'read_only',
  'global_write',
  'full_access',
  'auto',
]


/* ---------- 模式 → 状态点公共映射 ----------
 * 三档带强调色(用户反馈):
 *   read_only    → ok(绿)     无副作用
 *   global_write → warning(黄) 整盘可写
 *   full_access  → error(红)   助手内部数据/配置可改
 * workspace_write / auto 使用 'idle' -- StatusBarItem 对 idle 不显示状态点
 * 圆点,图标语义(FolderLock/Zap)已足以区分。
 */
export function permissionBadgeState(
  mode: PermissionMode,
): 'idle' | 'ok' | 'warning' | 'error' {
  switch (mode) {
    case 'read_only':
      return 'ok'
    case 'global_write':
      return 'warning'
    case 'full_access':
      return 'error'
    default:
      return 'idle'
  }
}

/** 模式 → 语义图标名(不直接返回 React 元素以避免在 types 模块里
 * 引入 JSX 依赖,组件层根据该名字 lucide-react 中取对应图标)。
 * 5 档 → 5 个不同的 lucide 图标,避免视觉雷同:
 *   read_only       → Eye(眼睛:只看)
 *   workspace_write → FolderLock(文件夹+锁:范围限定)
 *   global_write    → Globe(地球:整盘范围)
 *   full_access     → Unlock(开锁:全开)
 *   auto            → Zap(闪电:免审批自动放行)
 */
export type PermissionIconKind =
  | 'eye'
  | 'folder-lock'
  | 'globe'
  | 'unlock'
  | 'zap'

export function permissionIconKind(mode: PermissionMode): PermissionIconKind {
  switch (mode) {
    case 'read_only':
      return 'eye'
    case 'workspace_write':
      return 'folder-lock'
    case 'global_write':
      return 'globe'
    case 'full_access':
      return 'unlock'
    case 'auto':
      return 'zap'
    default:
      return 'eye'
  }
}
