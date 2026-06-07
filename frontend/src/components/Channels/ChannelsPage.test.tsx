import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { ChannelsPage } from './ChannelsPage'

describe('ChannelsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      if (urlString.includes('/api/v1/config')) {
        return Promise.resolve(new Response(JSON.stringify({
          channels: {
            qq: { enabled: true, app_id: 'test-qq-id', allowed_guilds: ['guild-1'], allowed_groups: [] },
            wechat: { enabled: false, weclaw_api_url: 'http://127.0.0.1:18011' },
          },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/qq/status')) {
        return Promise.resolve(new Response(JSON.stringify({ connected: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/status')) {
        return Promise.resolve(new Response(null, { status: 404 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    })
  })

  it('should render channels page', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('channels-page')).toBeTruthy()
    })
    expect(screen.getByText('Channels')).toBeTruthy()
  })

  it('should render QQ channel card', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('qq-channel-card')).toBeTruthy()
    })
  })

  it('should render WeChat channel card', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('wechat-channel-card')).toBeTruthy()
    })
  })

  it('should show QQ enabled badge', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByText('enabled')).toBeTruthy()
    })
  })

  it('should show WeChat disabled badge', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByText('disabled')).toBeTruthy()
    })
  })

  it('should show QQ app_id', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByText('test-qq-id')).toBeTruthy()
    })
  })

  it('should show allowed guild badge', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByText('guild-1')).toBeTruthy()
    })
  })

  it('should show WeChat disabled message', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByText(/not enabled/)).toBeTruthy()
    })
  })
})
