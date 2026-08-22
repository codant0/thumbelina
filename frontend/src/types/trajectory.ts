export interface TrajectoryEvent {
  seq: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface TrajectoryTurn {
  turn_id: string
  started_at: string
  legacy: boolean
  events: TrajectoryEvent[]
}

export interface TrajectoryPageData {
  conversation_id: string
  conversation_name?: string | null
  legacy: boolean
  total_turns: number
  page: number
  page_size: number
  turns: TrajectoryTurn[]
}