import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from './App'

const session = {
  schema_version: '2.1.0',
  request_id: 'req-session',
  authenticated: true,
  account: {
    username: 'release_user',
    display_name: 'Release User',
    status: 'active',
    default_memory_mode: 'on',
  },
  csrf_token: 'c'.repeat(43),
  session_expires_at: '2026-08-31T00:00:00Z',
  quota: {
    limit: 50,
    used: 2,
    remaining: 48,
    active: 0,
    resets_at: '2026-08-31T00:00:00Z',
  },
  provider_mode: 'real',
  model: 'deepseek-v4-flash',
  key_configured: true,
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v2/auth/session') return json(session)
      if (url === '/api/v2/system') {
        return json({
          schema_version: '2.1.0',
          request_id: 'req-system',
          version: '0.1.1',
          revision: 'abc123',
          migration: '007_day7_public_release',
          provider_mode: 'real',
          model: 'deepseek-v4-flash',
          key_configured: true,
          memory_budget_per_card: 100,
          memory_budget_total: 300,
          tool_allowlist: ['python_ast_check'],
          quota: session.quota,
        })
      }
      if (url.startsWith('/api/v2/tasks?')) {
        return json({
          schema_version: '2.1.0',
          request_id: 'req-tasks',
          items: [],
          next_cursor: null,
        })
      }
      if (url.startsWith('/api/v2/memories?')) {
        return json({ request_id: 'req-memories', items: [], next_cursor: null })
      }
      return json(
        {
          request_id: 'req-error',
          error: {
            code: 'NOT_FOUND',
            message: 'not found',
            retryable: false,
            details: {},
          },
        },
        404,
      )
    }),
  )
})

function renderApp(initialEntry = '/') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

describe('MemTrace public release shell', () => {
  it('does not probe an authenticated session from a public registration entry', async () => {
    renderApp('/register')

    expect(await screen.findByRole('heading', { name: '创建账号' })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalledWith('/api/v2/auth/session', expect.anything())
  })

  it('restores the public account and renders the ordinary Agent experience', async () => {
    renderApp()

    expect(await screen.findByRole('heading', { name: '与 MemTrace 对话' })).toBeInTheDocument()
    expect(screen.getByLabelText('对话内容')).toBeEnabled()
    expect(screen.queryByText('任务类型')).not.toBeInTheDocument()
    expect(screen.getByText('今日剩余 48 轮')).toBeInTheDocument()
    expect(await screen.findByText('0.1.1 · 真实模型')).toBeInTheDocument()
  })

  it('opens the unified Memory Center from authenticated navigation', async () => {
    const user = userEvent.setup()
    renderApp()

    const desktopNavigation = await screen.findByRole('navigation', { name: '主要导航' })
    await user.click(within(desktopNavigation).getByRole('link', { name: '记忆中心' }))

    expect(await screen.findByRole('heading', { name: '记忆中心' })).toBeInTheDocument()
  })

  it('redirects an unauthenticated visitor to login without exposing app data', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      json(
        {
          request_id: 'req-auth',
          error: {
            code: 'SESSION_REQUIRED',
            message: '需要有效会话。',
            retryable: false,
            details: {},
          },
        },
        401,
      ),
    )
    renderApp('/memories')

    expect(await screen.findByRole('heading', { name: '登录 MemTrace' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记忆中心' })).not.toBeInTheDocument()
  })

  it('redirects unknown authenticated routes to the Agent page', async () => {
    renderApp('/does-not-exist')
    expect(await screen.findByRole('heading', { name: '与 MemTrace 对话' })).toBeInTheDocument()
  })
})

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
