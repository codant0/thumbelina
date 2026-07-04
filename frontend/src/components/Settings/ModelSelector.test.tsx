import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ModelSelector } from './ModelSelector'

describe('ModelSelector', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches models on button click', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ provider: 'openai', base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-3.5-turbo'] }), { status: 200 }),
    )
    const onSelect = vi.fn()
    render(<ModelSelector provider="openai" base_url="https://api.openai.com/v1" api_key="sk-test" model="" onSelect={onSelect} />)
    fireEvent.click(screen.getByTestId('fetch-models-button'))
    await waitFor(() => {
      const options = screen.getAllByTestId('model-option')
      expect(options).toHaveLength(2)
    })
  })

  it('disables button for unsupported provider', () => {
    render(<ModelSelector provider="anthropic" base_url="" api_key="" model="" onSelect={vi.fn()} />)
    expect(screen.getByTestId('fetch-models-button')).toBeDisabled()
  })
})
