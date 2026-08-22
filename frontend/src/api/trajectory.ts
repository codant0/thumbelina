import type { TrajectoryPageData } from '../types/trajectory'

const API_BASE = '/api/v1'

/** 携带 HTTP 状态码的轨迹接口错误,调用方据此区分 404 等场景。 */
export class TrajectoryApiError extends Error {
  status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.status = status
  }
}

export async function fetchTrajectory(conversationId: string, page = 1, pageSize = 20): Promise<TrajectoryPageData> {
  const res = await fetch(`${API_BASE}/trajectory/${encodeURIComponent(conversationId)}?page=${page}&page_size=${pageSize}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new TrajectoryApiError(data.detail || `HTTP ${res.status}`, res.status)
  }
  return res.json() as Promise<TrajectoryPageData>
}
