import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SettingsPanel } from './SettingsPanel'

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      if (urlString.includes('/api/v1/user/profile')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: {
                id: '1',
                user_id: 'default',
                communication_style: 'casual',
                expertise_level: 'intermediate',
              },
              preferences: [
                {
                  id: 'p1',
                  category: 'theme',
                  key: 'color',
                  value: 'dark',
                  confidence_score: 0.9,
                },
              ],
            }),
            { status: 200 },
          ),
        )
      }
      if (urlString.includes('/config/llm/endpoints')) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
    })
  })

  it('should render settings panel', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('settings-panel')).toBeInTheDocument()
  })

  it('should render provider dropdown', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('provider-select')).toBeInTheDocument()
  })

  it('should render model input', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('model-input')).toBeInTheDocument()
  })

  it('should render base url input', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('base-url-input')).toBeInTheDocument()
  })

  it('should render rate limit toggle', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('rate-limit-toggle')).toBeInTheDocument()
  })

  it('should render save button', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('save-button')).toBeInTheDocument()
  })

  it('should have openai as default provider', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('provider-select')).toHaveValue('openai')
  })

  it('should render user profile card', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('user-profile-card')).toBeInTheDocument()
  })

  it('should display user profile data after loading', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByText('casual')).toBeInTheDocument()
      expect(screen.getByText('intermediate')).toBeInTheDocument()
    })
  })

  it('should display preferences with confidence scores', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByTestId('preference-item')).toBeInTheDocument()
      expect(screen.getByText('theme/color:')).toBeInTheDocument()
      expect(screen.getByText('dark')).toBeInTheDocument()
      expect(screen.getByText('(90%)')).toBeInTheDocument()
    })
  })

  it('should render data management card', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('data-management-card')).toBeInTheDocument()
  })

  it('should render export button', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('export-button')).toBeInTheDocument()
  })

  it('should render delete all button', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('delete-all-button')).toBeInTheDocument()
  })

  it('should show confirmation prompt when delete button is clicked once', async () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByTestId('delete-all-button'))
    await waitFor(() => {
      expect(screen.getByText('Click again to confirm')).toBeInTheDocument()
    })
  })

  it('should show cancel button during delete confirmation', async () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByTestId('delete-all-button'))
    await waitFor(() => {
      expect(screen.getByText('Cancel')).toBeInTheDocument()
    })
  })

  it('should cancel delete confirmation when cancel is clicked', async () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByTestId('delete-all-button'))
    await waitFor(() => {
      expect(screen.getByText('Cancel')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Cancel'))
    await waitFor(() => {
      expect(screen.getByText('Delete All Data')).toBeInTheDocument()
    })
  })

  it('should call delete endpoint on second confirm click', async () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByTestId('delete-all-button'))
    await waitFor(() => {
      expect(screen.getByText('Click again to confirm')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('delete-all-button'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/v1/data/all?confirm=true',
        { method: 'DELETE' },
      )
    })
  })

  it('should call export endpoint when export button is clicked', async () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByTestId('export-button'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/data/export')
    })
  })

  it('should render endpoint manager', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-manager')).toBeInTheDocument()
    })
  })

  it('should render fetch models button', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByTestId('fetch-models-button')).toBeInTheDocument()
    })
  })
})
