import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../App'

afterEach(() => vi.unstubAllGlobals())

describe('release settings page', () => {
  it('shows safe runtime diagnostics and persists account settings with idempotency', async () => {
    let defaultMode: 'on' | 'off' = 'on'
    const writes: RequestInit[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/v2/auth/session') return json(session(defaultMode))
        if (url === '/api/v2/system') return json(system())
        if (url === '/api/v2/auth/account/preferences') {
          writes.push(init ?? {})
          defaultMode = 'off'
          return json({ schema_version: '2.1.0', request_id: 'req-pref', status: 'preferences_updated' })
        }
        if (url === '/api/v2/auth/recovery-code/rotate') {
          writes.push(init ?? {})
          return json({
            schema_version: '2.1.0',
            request_id: 'req-rotate',
            recovery_code: `rec_${'x'.repeat(43)}`,
          })
        }
        return notFound()
      }),
    )
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '系统设置' })).toBeInTheDocument()
    expect(await screen.findByText('0.1.0 / abcdef123456')).toBeInTheDocument()
    expect(screen.getByText('是（仅布尔值）')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('新对话默认记忆模式'), 'off')
    expect(await screen.findByText('新对话默认记忆模式已更新。')).toBeInTheDocument()
    expect(screen.getByLabelText('新对话默认记忆模式')).toHaveValue('off')

    await user.click(screen.getByRole('button', { name: '轮换恢复码' }))
    expect(await screen.findByText(`rec_${'x'.repeat(43)}`)).toBeInTheDocument()
    expect(screen.getByText('旧恢复码已失效。新恢复码仅显示这一次。')).toBeInTheDocument()
    await waitFor(() => expect(writes).toHaveLength(2))
    for (const write of writes) {
      const headers = new Headers(write.headers)
      expect(headers.get('X-CSRF-Token')).toBe('c'.repeat(43))
      expect(headers.get('Idempotency-Key')).toMatch(/^web-/)
    }
  })
})

function session(defaultMode: 'on' | 'off') {
  return {
    schema_version: '2.1.0',
    request_id: 'req-session',
    authenticated: true,
    account: {
      username: 'release_user',
      display_name: 'Release User',
      status: 'active',
      default_memory_mode: defaultMode,
    },
    csrf_token: 'c'.repeat(43),
    session_expires_at: '2026-08-31T00:00:00Z',
    quota: {
      limit: 50,
      used: 5,
      remaining: 45,
      active: 0,
      resets_at: '2026-08-31T00:00:00Z',
    },
    provider_mode: 'real',
    model: 'deepseek-v4-flash',
    key_configured: true,
  }
}

function system() {
  return {
    schema_version: '2.1.0',
    request_id: 'req-system',
    version: '0.1.0',
    revision: 'abcdef123456',
    migration: '007_day7_public_release',
    provider_mode: 'real',
    model: 'deepseek-v4-flash',
    key_configured: true,
    memory_budget_per_card: 100,
    memory_budget_total: 300,
    tool_allowlist: ['python_ast_check'],
    quota: session('on').quota,
  }
}

function notFound(): Response {
  return json(
    {
      request_id: 'req-not-found',
      error: { code: 'NOT_FOUND', message: 'not found', retryable: false, details: {} },
    },
    404,
  )
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
