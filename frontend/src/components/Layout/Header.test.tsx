import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Header } from './Header'

describe('Header', () => {
  it('should render app title', () => {
    render(<Header />)
    expect(screen.getByText('Thumbelina')).toBeInTheDocument()
  })

  it('should render navigation', () => {
    render(<Header />)
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })
})
