import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SettingsPanel } from './SettingsPanel'

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    )
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

  it('should render auth toggle', () => {
    render(<SettingsPanel />)
    expect(screen.getByTestId('auth-toggle')).toBeInTheDocument()
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
})
