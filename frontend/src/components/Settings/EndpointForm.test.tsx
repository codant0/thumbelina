import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EndpointForm } from './EndpointForm'

describe('EndpointForm', () => {
  it('validates empty name', async () => {
    const onSubmit = vi.fn()
    render(<EndpointForm onSubmit={onSubmit} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByTestId('endpoint-form-submit'))
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-form-error')).toHaveTextContent('Name is required')
    })
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits correct payload', async () => {
    const onSubmit = vi.fn()
    render(<EndpointForm onSubmit={onSubmit} onCancel={vi.fn()} />)
    fireEvent.change(screen.getByTestId('endpoint-name-input'), { target: { value: 'Default' } })
    fireEvent.change(screen.getByTestId('endpoint-base-url-input'), { target: { value: 'https://api.openai.com/v1' } })
    fireEvent.change(screen.getByTestId('endpoint-api-key-input'), { target: { value: 'sk-test' } })
    fireEvent.click(screen.getByTestId('endpoint-form-submit'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        provider: 'openai',
        name: 'Default',
        base_url: 'https://api.openai.com/v1',
        api_key: 'sk-test',
        is_default: false,
      })
    })
  })

  it('shows keep-current-key hint when editing', () => {
    render(<EndpointForm onSubmit={vi.fn()} onCancel={vi.fn()} initialValues={{ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', api_key_set: true, is_default: false }} />)
    expect(screen.getByPlaceholderText(/leave empty to keep current key/i)).toBeInTheDocument()
  })
})
