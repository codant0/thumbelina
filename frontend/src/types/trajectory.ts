export interface TrajectoryEvent {
  seq: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface TrajectoryTurn {
  turn_id: string
  started_at: string
  events: TrajectoryEvent[]
}

export interface TrajectoryPageData {
  conversation_id: string
  conversation_name?: string | null
  total_turns: number
  page: number
  page_size: number
  turns: TrajectoryTurn[]
}

export type TrajectoryDetail =
  | { kind: 'event'; event: TrajectoryEvent; turnIndex: number }
  // 全局轮次序号：倒序列表中最旧（底部）为 #1，越往上越大。
  | { kind: 'turn-meta'; turn: TrajectoryTurn; turnNumber: number }