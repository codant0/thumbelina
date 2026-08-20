import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConversationModelSelector } from './ConversationModelSelector'
import * as llmConfig from '../../api/llmConfig'

const endpoints = [
  { id: 'ep1', provider: 'openai' as const, name: 'Mimo', base_url: 'https://api.openai.com', models: [{ name: 'gpt-4o', context_window: '128K', multimodal: true }, { name: 'gpt-4o-mini', context_window: null, multimodal: false }], api_key_set: true, is_default: true, active_model: 'gpt-4o' },
  { id: 'ep2', provider: 'ollama' as const, name: 'Llama local', base_url: 'http://localhost:11434', models: [{ name: 'llama3', context_window: null, multimodal: false }], api_key_set: false, is_default: false },
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

  it('shows Default model when no endpoint is selected', async () => {
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId={null} onChange={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('conv-model-trigger').textContent).toContain('Default model')
  })

  it('shows selected model name when a model is chosen', async () => {
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId="ep1" selectedModel="gpt-4o-mini" onChange={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('conv-model-trigger').textContent).toContain('gpt-4o-mini')
  })

  it('calls onChange with the chosen endpoint and model', async () => {
    const onChange = vi.fn()
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId={null} onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger').textContent).toContain('Default'))
    fireEvent.click(screen.getByTestId('conv-model-trigger'))
    fireEvent.click(screen.getByTestId('conv-model-option-ep1-gpt-4o-mini'))
    expect(onChange).toHaveBeenCalledWith('ep1', 'gpt-4o-mini')
  })

  it('calls onChange with null when Default model is chosen', async () => {
    const onChange = vi.fn()
    render(
      <ConversationModelSelector conversationId="c1" selectedEndpointId="ep1" selectedModel="gpt-4o" onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger').textContent).toContain('gpt-4o'))
    fireEvent.click(screen.getByTestId('conv-model-trigger'))
    fireEvent.click(screen.getByTestId('conv-model-default'))
    expect(onChange).toHaveBeenCalledWith(null, null)
  })

  it('groups endpoints by endpoint name', async () => {
    render(
      <ConversationModelSelector conversationId="c1" onChange={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByTestId('conv-model-trigger').textContent).toContain('Default'))
    fireEvent.click(screen.getByTestId('conv-model-trigger'))
    // Each endpoint with models is its own group
    expect(screen.getByTestId('conv-model-group-ep1')).toBeInTheDocument()
    expect(screen.getByTestId('conv-model-group-ep2')).toBeInTheDocument()
    // Group header shows the endpoint name
    expect(screen.getByTestId('conv-model-group-ep1').textContent).toContain('Mimo')
    expect(screen.getByTestId('conv-model-group-ep2').textContent).toContain('Llama local')
  })
})
