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

export interface GitInfo {
  is_git: boolean
  branch: string | null
}

export interface GitBranches {
  is_git: boolean
  current: string | null
  branches: string[]
}

/** 探测工作区 git 状态;非 git 目录返回 is_git=false。 */
export async function fetchGitInfo(path: string): Promise<GitInfo> {
  const res = await fetch(`${API_BASE}/fs/git?path=${encodeURIComponent(path)}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<GitInfo>
}

/** 列出本地分支及当前分支。 */
export async function fetchGitBranches(path: string): Promise<GitBranches> {
  const res = await fetch(`${API_BASE}/fs/git/branches?path=${encodeURIComponent(path)}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<GitBranches>
}

/** 切换到指定本地分支,返回切换后的 git 状态。 */
export async function checkoutBranch(path: string, branch: string): Promise<GitInfo> {
  const res = await fetch(`${API_BASE}/fs/git/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, branch }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<GitInfo>
}