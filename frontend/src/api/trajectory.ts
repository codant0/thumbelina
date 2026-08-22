import type { TrajectoryPageData } from '../types/trajectory'

const API_BASE = '/api/v1'

export async function fetchTrajectory(conversationId: string, page = 1, pageSize = 20): Promise<TrajectoryPageData> {
  const res = await fetch(`${API_BASE}/trajectory/${encodeURIComponent(conversationId)}?page=${page}&page_size=${pageSize}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<TrajectoryPageData>
}