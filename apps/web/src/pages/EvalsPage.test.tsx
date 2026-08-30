import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EvalsPage } from './EvalsPage'

describe('read-only release evidence page', () => {
  it('shows measured semantic results and the honest external-gate blocker', () => {
    render(<EvalsPage />)
    expect(screen.getByRole('heading', { name: '真实模型评测' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('仍等待 Docker、双浏览器和第二设备')
    expect(screen.getByText('真实 Provider 六项预检')).toBeInTheDocument()
    expect(screen.getByText('64 / 64')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })
})
