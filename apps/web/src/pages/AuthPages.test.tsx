import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../App'

const RECOVERY = `rec_${'r'.repeat(43)}`
const NEXT_RECOVERY = `rec_${'n'.repeat(43)}`

afterEach(() => vi.unstubAllGlobals())

describe('public account pages', () => {
  it('logs in through the uniform public form and enters the ordinary Agent page', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        requests.push({ url, init })
        if (url === '/api/v2/auth/session') return authRequired()
        if (url === '/api/v2/auth/login') return json(session())
        if (url === '/api/v2/system') return json(system())
        if (url.startsWith('/api/v2/tasks?')) return json(taskList())
        if (url.startsWith('/api/v2/memories?')) return json(memoryList())
        if (url.startsWith('/api/v2/memory-events')) return json(memoryEvents())
        return notFound()
      }),
    )
    const user = userEvent.setup()
    renderRoute('/login')

    await user.type(await screen.findByLabelText('用户名'), 'release_user')
    await user.type(screen.getByLabelText('密码'), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('heading', { name: '与 MemTrace 对话' })).toBeInTheDocument()
    const login = requests.find((request) => request.url === '/api/v2/auth/login')
    expect(JSON.parse(String(login?.init?.body))).toEqual({
      username: 'release_user',
      password: 'correct horse battery staple',
    })
  })

  it('registers with an invite and keeps the one-time recovery code visible', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v2/auth/session') return authRequired()
        if (url === '/api/v2/auth/register') {
          return json({
            schema_version: '2.1.0',
            request_id: 'req-register',
            session: session(),
            recovery_code: RECOVERY,
          })
        }
        return notFound()
      }),
    )
    const user = userEvent.setup()
    renderRoute('/register')

    await user.type(await screen.findByLabelText('邀请码'), `inv_${'i'.repeat(43)}`)
    await user.type(screen.getByLabelText('用户名'), 'Release_User')
    await user.type(screen.getByLabelText('显示名'), 'Release User')
    await user.type(screen.getByLabelText('密码（至少 12 位）'), 'correct horse battery staple')
    await user.type(screen.getByLabelText('确认密码'), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: '注册并生成恢复码' }))

    expect(await screen.findByRole('heading', { name: '立即保存恢复码' })).toBeInTheDocument()
    expect(screen.getByText(RECOVERY)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下载恢复码' })).toBeInTheDocument()
  })

  it('rotates the recovery code and does not expose the previous value again', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v2/auth/session') return authRequired()
        if (url === '/api/v2/auth/recover') {
          return json({
            schema_version: '2.1.0',
            request_id: 'req-recover',
            recovery_code: NEXT_RECOVERY,
            sessions_revoked: 2,
          })
        }
        return notFound()
      }),
    )
    const user = userEvent.setup()
    renderRoute('/recover')

    await user.type(await screen.findByLabelText('用户名'), 'release_user')
    await user.type(screen.getByLabelText('恢复码'), RECOVERY)
    await user.type(screen.getByLabelText('新密码'), 'new correct horse battery staple')
    await user.type(screen.getByLabelText('确认新密码'), 'new correct horse battery staple')
    await user.click(screen.getByRole('button', { name: '重设密码并轮换恢复码' }))

    expect(await screen.findByText(NEXT_RECOVERY)).toBeInTheDocument()
    expect(screen.queryByText(RECOVERY)).not.toBeInTheDocument()
  })

  it('shows a generic rate-limit message without revealing account existence', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/v2/auth/session') return authRequired()
        return json(
          {
            request_id: 'req-rate',
            error: {
              code: 'RATE_LIMITED',
              message: '尝试次数过多，请稍后再试。',
              retryable: true,
              details: { retry_after_seconds: 90 },
            },
          },
          429,
        )
      }),
    )
    const user = userEvent.setup()
    renderRoute('/login')
    await user.type(await screen.findByLabelText('用户名'), 'unknown_user')
    await user.type(screen.getByLabelText('密码'), 'wrong password value')
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('约 90 秒后重试')
  })
})

function renderRoute(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

function session() {
  return {
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
      used: 0,
      remaining: 50,
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
    version: '0.1.1',
    revision: 'a'.repeat(40),
    migration: '007_day7_public_release',
    provider_mode: 'real',
    model: 'deepseek-v4-flash',
    key_configured: true,
    memory_budget_per_card: 100,
    memory_budget_total: 300,
    tool_allowlist: ['python_ast_check'],
    quota: session().quota,
  }
}

function taskList() {
  return { schema_version: '2.1.0', request_id: 'req-tasks', items: [], next_cursor: null }
}

function memoryList() {
  return { schema_version: '2.1.0', request_id: 'req-memories', items: [], next_cursor: null }
}

function memoryEvents() {
  return { schema_version: '2.1.0', request_id: 'req-events', items: [], next_seq: 0 }
}

function authRequired() {
  return json(
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
  )
}

function notFound() {
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
