import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConversationModelSelector } from './ConversationModelSelector'
import * as llmConfig from '../../api/llmConfig'

const endpoints = [
  { id: 'ep1', provider: 'openai' as const, name: 'GPT-4o', base_url: 'https://api.openai.com', model: 'gpt-4o', api_key_set: true, is_default: true },
  { id: 'ep2', provider: 'ollama' as const, name: 'Llama local', base_url: 'http://localhost:11434', model: 'llama3', api_key_set: false, is_default: false },
]

describe('ConversationModelSelector', () => {
  beforeEach(() => {
    vi.spyOn(llmConfig, 'fetchEndpoints').mockResolvedValue(endpoints)
  })

  it('renders nothing when no conversation is selected', () => {
    const { container } = render(
      <ConversationModelSelector conversationId={undefined} onChange={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows the selected endpoint name', async () => {
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId="ep2" onChange={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('conv-model-trigger').textContent).toContain('Llama local')
  })

  it('shows Default model when no endpoint is selected', async () => {
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId={null} onChange={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('conv-model-trigger').textContent).toContain('Default model')
  })

  it('calls onChange with the chosen endpoint id', async () => {
    const onChange = vi.fn()
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId={null} onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('conv-model-trigger'))
    fireEvent.click(screen.getByTestId('conv-model-option-ep1'))
    expect(onChange).toHaveBeenCalledWith('ep1')
  })

  it('calls onChange with null when Default model is chosen', async () => {
    const onChange = vi.fn()
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId="ep1" onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('conv-model-trigger'))
    fireEvent.click(screen.getByTestId('conv-model-default'))
    expect(onChange).toHaveBeenCalledWith(null)
  })
})
