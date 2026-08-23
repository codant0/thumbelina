const API_BASE = '/api/v1'

export interface DirEntry {
  name: string
  path: string
}

export interface DirListing {
  path: string | null
  parent: string | null
  children: DirEntry[]
  truncated: boolean
}

export async function listDirs(path?: string): Promise<DirListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const res = await fetch(`${API_BASE}/fs/dirs${query}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<DirListing>
}