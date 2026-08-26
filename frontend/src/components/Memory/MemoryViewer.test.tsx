import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LocaleProvider } from '../../i18n'
import { MemoryViewer } from './MemoryViewer'

type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetch(handler: FetchHandler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init),
  )
}

const SAMPLE_ENTRIES = [
  {
    title: '用户:编程偏好',
    category: 'user',
    slug: 'prog',
    summary: '偏好 Python 与类型注解',
    updated: '2026-08-16',
    source: '对话 2026-08-10',
    relpath: 'user/prog.md',
  },
  {
    title: '项目:部署环境',
    category: 'project',
    slug: 'deploy',
    summary: '线上为 Docker 部署',
    updated: '2026-08-15',
    source: '',
    relpath: 'project/deploy.md',
  },
  {
    title: '项目:数据库选型',
    category: 'project',
    slug: 'db',
    summary: '已选 SQLite',
    updated: '2026-08-14',
    source: '',
    relpath: 'project/db.md',
  },
]

const SAMPLE_HITS = [
  {
    title: '用户:旅行计划',
    category: 'user',
    slug: 'trip',
    summary: '计划日本之行',
    score: 0.61,
    matched_field: 'full_text',
    snippet: '- 2026-09-03:购买环球影城门票。',
    updated: '2026-08-20',
    source: '',
  },
  {
    title: '项目:数据库选型',
    category: 'project',
    slug: 'db',
    summary: '已选 SQLite',
    score: 0.5,
    matched_field: 'title',
    snippet: '项目:数据库选型',
    updated: '2026-08-14',
    source: '',
  },
]

const FULL_DETAIL = {
  title: '项目:数据库选型',
  category: 'project',
  slug: 'db',
  summary: '已选 SQLite',
  overview: '生产使用 SQLite,单文件易备份。',
  full_text: '- 2026-08-14:确定 SQLite,不引入外部服务。',
  updated: '2026-08-14',
  source: '',
  relpath: 'project/db.md',
}

/** Default handler: memory enabled with sample entries; search returns hits. */
function enabledHandler(
  override?: (url: string, init?: RequestInit) => Response | undefined,
): FetchHandler {
  return (url, init) => {
    const custom = override?.(url, init)
    if (custom) return custom
    if (url === '/api/v1/memory/status') return jsonResponse({ enabled: true, entries: 3 })
    if (url === '/api/v1/memory/entries') return jsonResponse(SAMPLE_ENTRIES)
    if (url.startsWith('/api/v1/memory/search?q=')) return jsonResponse(SAMPLE_HITS)
    if (url === '/api/v1/memory/project/db?depth=full') return jsonResponse(FULL_DETAIL)
    return jsonResponse([])
  }
}

beforeEach(() => {
  localStorage.setItem('thumbelina-locale', 'zh-CN')
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

function renderMemory() {
  return render(
    <LocaleProvider>
      <MemoryViewer />
    </LocaleProvider>,
  )
}

describe('MemoryViewer', () => {
  it('应该渲染标题与搜索控件', async () => {
    mockFetch(enabledHandler())
    renderMemory()
    await screen.findByTestId('search-input')
    expect(screen.getByTestId('memory-viewer')).toBeInTheDocument()
    expect(screen.getByTestId('search-button')).toBeInTheDocument()
    expect(screen.getByTestId('search-results')).toBeInTheDocument()
  })

  it('应该渲染统计条:记忆数/分类数/最近更新', async () => {
    mockFetch(enabledHandler())
    renderMemory()
    await screen.findByTestId('memory-stats')
    const stats = screen.getByTestId('memory-stats')
    expect(stats.textContent).toContain('3')
    expect(stats.textContent).toContain('2')
    expect(stats.textContent).toContain('2026-08-16')
    expect(stats.textContent).toContain('条记忆')
    expect(stats.textContent).toContain('个分类')
  })

  it('浏览模式按分类分组展示', async () => {
    mockFetch(enabledHandler())
    renderMemory()
    const groups = await screen.findAllByTestId('memory-group')
    expect(groups).toHaveLength(2)
    const headers = screen.getAllByTestId('memory-group-header').map(el => el.textContent ?? '')
    expect(headers.some(el => el.includes('用户'))).toBe(true)
    expect(headers.some(el => el.includes('项目'))).toBe(true)
    expect(screen.getAllByTestId('memory-entry')).toHaveLength(3)
  })

  it('分组过滤卡片带计数,默认全部', async () => {
    mockFetch(enabledHandler())
    renderMemory()
    await screen.findByTestId('memory-group-filter')
    const cards = screen.getAllByTestId('memory-group-filter-card')
    expect(cards[0].textContent).toContain('全部')
    expect(cards[0].textContent).toContain('3')
    expect(cards[1].textContent).toContain('用户')
    expect(cards[1].getAttribute('aria-pressed')).toBe('false')
  })

  it('点击分组卡片后聚焦该组', async () => {
    mockFetch(enabledHandler())
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('memory-group-filter')
    const cards = screen.getAllByTestId('memory-group-filter-card')
    await user.click(cards[2])
    expect(screen.queryByTestId('memory-group')).toBeNull()
    const entries = screen.getAllByTestId('memory-entry')
    expect(entries).toHaveLength(2)
    expect(entries[0].textContent).toContain('部署')
    expect(entries[1].textContent).toContain('数据库')
  })

  it('搜索返回命中文档,显示片段高亮与命中层级徽标', async () => {
    mockFetch(enabledHandler())
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('search-input')
    await user.type(screen.getByTestId('search-input'), '环球影城')
    await user.click(screen.getByTestId('search-button'))
    await waitFor(() => {
      expect(screen.getAllByTestId('memory-entry').length).toBeGreaterThan(0)
    })
    const summary = screen.getAllByTestId('memory-entry-summary')[0]
    const marks = within(summary as HTMLElement).queryAllByText('环球影城', { selector: 'mark' })
    expect(marks.length).toBeGreaterThan(0)
    expect(screen.getByText('正文')).toBeInTheDocument()
    expect(screen.getByText('标题')).toBeInTheDocument()
    expect(screen.getByTestId('memory-group-filter')).toBeInTheDocument()
  })

  it('搜索无结果时展示空态', async () => {
    mockFetch(
      enabledHandler(url => {
        if (url.startsWith('/api/v1/memory/search?q=')) return jsonResponse([])
        return undefined
      }),
    )
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('search-input')
    await user.type(screen.getByTestId('search-input'), 'zzz')
    await user.click(screen.getByTestId('search-button'))
    await screen.findByTestId('memory-no-results')
  })

  it('清空关键词恢复浏览模式', async () => {
    mockFetch(enabledHandler())
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('search-input')
    await user.type(screen.getByTestId('search-input'), '环球影城')
    await user.click(screen.getByTestId('search-button'))
    await screen.findByTestId('memory-group-filter')
    await user.click(screen.getByTestId('search-clear'))
    expect(screen.queryByTestId('search-clear')).toBeNull()
    expect(screen.getByTestId('search-input')).toHaveValue('')
    expect(screen.getAllByTestId('memory-entry').length).toBe(3)
  })

  it('点击条目内联展开概览与全文,再次点击收起', async () => {
    mockFetch(enabledHandler())
    const user = userEvent.setup()
    renderMemory()
    const toggles = await screen.findAllByTestId('memory-entry-toggle')
    await user.click(toggles[2])
    await screen.findByTestId('memory-entry-detail')
    expect(screen.getByText('概览')).toBeInTheDocument()
    expect(screen.getByText('全文')).toBeInTheDocument()
    await user.click(screen.getAllByTestId('memory-entry-toggle')[2])
    await waitFor(() => {
      expect(screen.queryByTestId('memory-entry-detail')).toBeNull()
    })
  })

  it('无记忆时展示空态,隐藏分组卡片', async () => {
    mockFetch(
      enabledHandler(url => {
        if (url === '/api/v1/memory/entries') return jsonResponse([])
        return undefined
      }),
    )
    renderMemory()
    await screen.findByTestId('memory-empty')
    expect(screen.queryByTestId('memory-group-filter')).toBeNull()
  })

  it('模块禁用时展示禁用提示', async () => {
    mockFetch(url => {
      if (url === '/api/v1/memory/status') return jsonResponse({ enabled: false })
      return jsonResponse([])
    })
    renderMemory()
    await screen.findByTestId('memory-disabled')
  })

  it('搜索失败时展示错误', async () => {
    mockFetch(
      enabledHandler(url => {
        if (url.startsWith('/api/v1/memory/search?q=')) return jsonResponse({}, 500)
        return undefined
      }),
    )
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('search-input')
    await user.type(screen.getByTestId('search-input'), 'x')
    await user.click(screen.getByTestId('search-button'))
    await screen.findByTestId('search-error')
  })

  it('回车键触发搜索', async () => {
    mockFetch(enabledHandler())
    const user = userEvent.setup()
    renderMemory()
    await screen.findByTestId('search-input')
    await user.type(screen.getByTestId('search-input'), 'SQLite{enter}')
    await waitFor(() => {
      expect(screen.getAllByTestId('memory-entry').length).toBeGreaterThan(0)
    })
  })
})