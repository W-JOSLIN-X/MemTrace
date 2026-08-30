import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { publicApi } from '../auth/api'
import { EvalsPage } from './EvalsPage'

afterEach(() => vi.restoreAllMocks())

describe('read-only release evidence page', () => {
  it('shows measured semantic results and the authenticated runtime revision', async () => {
    vi.spyOn(publicApi, 'system').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-eval-system',
      version: '0.1.0',
      revision: 'aeddcecf55bcd4b4df16f3a773cbfa293d99727e',
      migration: '007_day7_public_release',
      provider_mode: 'real',
      model: 'deepseek-v4-flash',
      key_configured: true,
      memory_budget_per_card: 100,
      memory_budget_total: 300,
      tool_allowlist: ['python_ast_check'],
      quota: {
        limit: 50,
        used: 12,
        remaining: 38,
        active: 0,
        resets_at: '2026-08-31T00:00:00Z',
      },
    })
    render(<EvalsPage />)
    expect(screen.getByRole('heading', { name: '真实模型评测' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('仍等待 Docker、双浏览器和第二设备')
    expect(screen.getByText('真实 Provider 六项预检')).toBeInTheDocument()
    expect(screen.getByText('64 / 64')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
    expect(
      await screen.findByText('aeddcecf55bcd4b4df16f3a773cbfa293d99727e'),
    ).toBeInTheDocument()
  })
})
