import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { ChannelsPage } from './ChannelsPage'

describe('ChannelsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      if (urlString.includes('/api/v1/config')) {
        return Promise.resolve(new Response(JSON.stringify({
          channels: {
            qq: { enabled: true, app_id: 'test-qq-id', app_secret_set: false, allowed_guilds: ['guild-1'], allowed_groups: [] },
            wechat: { enabled: false, ilink_bot_id: '', bot_token_set: false },
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

  it('should show WeChat QR code login button when disabled', async () => {
    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('wechat-qrcode-button')).toBeTruthy()
    })
  })

  it('should show reconnect prompt when WeChat is enabled but needs authentication', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      if (urlString.includes('/api/v1/config')) {
        return Promise.resolve(new Response(JSON.stringify({
          channels: {
            qq: { enabled: false, app_id: '', app_secret_set: false, allowed_guilds: [], allowed_groups: [] },
            wechat: { enabled: true, ilink_bot_id: 'wxid_test', bot_token_set: true },
          },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          connected: false,
          needs_authentication: true,
          error: 'WeChat session expired or not logged in.',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    })

    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('wechat-reconnect-button')).toBeTruthy()
    })
  })

  it('should start QR code flow when reconnect button is clicked', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      if (urlString.includes('/api/v1/config')) {
        return Promise.resolve(new Response(JSON.stringify({
          channels: {
            qq: { enabled: false, app_id: '', app_secret_set: false, allowed_guilds: [], allowed_groups: [] },
            wechat: { enabled: true, ilink_bot_id: 'wxid_test', bot_token_set: true },
          },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          connected: false,
          needs_authentication: true,
          error: 'WeChat session expired or not logged in.',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/qrcode') && !urlString.includes('status')) {
        return Promise.resolve(new Response(JSON.stringify({
          qrcode: 'qr-123',
          qrcode_img_content: 'https://ilinkai.weixin.qq.com/qr/xxx',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/qrcode/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          status: 'confirmed',
          credentials: {
            bot_token: 'tok-123',
            ilink_bot_id: 'wxid_test',
            base_url: 'https://ilinkai.weixin.qq.com',
            ilink_user_id: 'user-123',
          },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (urlString.includes('/api/v1/wechat/qrcode/confirm')) {
        return Promise.resolve(new Response(JSON.stringify({ status: 'ok', connected: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    })

    render(<ChannelsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('wechat-reconnect-button')).toBeTruthy()
    })
    fireEvent.click(screen.getByTestId('wechat-reconnect-button'))
    await waitFor(() => {
      expect(screen.getByText('Login successful!')).toBeTruthy()
    })
  })
})
