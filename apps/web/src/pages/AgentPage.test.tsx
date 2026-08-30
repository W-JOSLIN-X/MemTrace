import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../App'
import {
  createG5Response,
  createG5JobResponse,
  createG5SnapshotResponse,
  createG5TurnResponse,
} from '../test/g5Fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
  FakeEventSource.instances = []
  globalThis.history.replaceState({}, '', '/')
})

describe('production Agent streaming page', () => {
  it('restores the newest server task after a browser refresh', async () => {
    const snapshot = createG5SnapshotResponse()
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v2/auth/session') return json(session())
        if (url === '/api/v2/system') return json(system())
        if (url.startsWith('/api/v2/tasks?')) {
          return json({
            schema_version: '2.1.0',
            request_id: 'req-tasks',
            items: [
              {
                task_id: snapshot.task_id,
                title: '恢复后的会话',
                memory_mode: 'on',
                message_count: 2,
                created_at: snapshot.created_at,
                updated_at: snapshot.updated_at,
              },
            ],
            next_cursor: null,
          })
        }
        if (url === `/api/v2/tasks/${snapshot.task_id}`) return json(snapshot)
        if (url.startsWith('/api/v2/reflection-jobs/')) {
          return json({ ...createG5JobResponse(), mutation_decision: 'noop' })
        }
        if (url.startsWith('/api/v2/memories?')) return json(memoryList())
        if (url.startsWith('/api/v2/memory-events?')) return json(memoryEvents())
        return notFound()
      }),
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByText('以后请用中文回答。')).toBeInTheDocument()
    expect(screen.getByText('本轮实际 token：30')).toBeInTheDocument()
    expect(new URLSearchParams(globalThis.location.search).get('task')).toBe(snapshot.task_id)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    expect(FakeEventSource.instances[0].url).toContain(snapshot.task_id)
  })

  it('opens SSE before the first real turn, renders deltas, then replaces them with authority', async () => {
    let resolveTurn!: (response: Response) => void
    const turnResponse = new Promise<Response>((resolve) => {
      resolveTurn = resolve
    })
    const writes: Array<{ url: string; init?: RequestInit }> = []
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method && init.method !== 'GET') writes.push({ url, init })
        if (url === '/api/v2/auth/session') return json(session())
        if (url === '/api/v2/system') return json(system())
        if (url.startsWith('/api/v2/tasks?')) return json(taskList())
        if (url.startsWith('/api/v2/memories?')) return json(memoryList())
        if (url.startsWith('/api/v2/memory-events?')) return json(memoryEvents())
        if (url === '/api/v2/tasks' && init?.method === 'POST') return json(createG5Response(), 201)
        if (url.endsWith('/turns') && init?.method === 'POST') return turnResponse
        if (url.startsWith('/api/v2/reflection-jobs/')) {
          return json({ ...createG5JobResponse(), mutation_decision: 'noop' })
        }
        return notFound()
      }),
    )
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    const input = await screen.findByLabelText('对话内容')
    await user.type(input, '以后请用中文回答。')
    await user.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = FakeEventSource.instances[0]
    expect(source.url).toContain('/api/v2/tasks/task_')
    source.emit('open')
    await waitFor(() => expect(writes.some((item) => item.url.endsWith('/turns'))).toBe(true))
    source.emit(
      'assistant.delta',
      JSON.stringify({
        run_id: 'run_01J00000000000000000000001',
        delta_index: 1,
        delta: '正在流式回答',
      }),
    )
    expect(await screen.findByText(/正在流式回答/)).toBeInTheDocument()

    resolveTurn(json(createG5TurnResponse()))
    expect(await screen.findByText('好的。')).toBeInTheDocument()
    expect(screen.queryByText(/正在流式回答/)).not.toBeInTheDocument()
    expect(screen.getByText('本轮实际 token：30')).toBeInTheDocument()
    expect(screen.getByText('首 token：20 ms')).toBeInTheDocument()
    expect(await screen.findByText('本轮没有新增长期记忆。')).toBeInTheDocument()
    const turnWrite = writes.find((item) => item.url.endsWith('/turns'))
    expect(new Headers(turnWrite?.init?.headers).get('Idempotency-Key')).toMatch(/^memtrace-/)
  })
})

class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly url: string
  readonly withCredentials: boolean
  readyState = 0
  onerror: ((event: Event) => void) | null = null
  private listeners = new Map<string, Set<(event: Event | MessageEvent<string>) => void>>()

  constructor(url: string | URL, init?: EventSourceInit) {
    this.url = String(url)
    this.withCredentials = init?.withCredentials ?? false
    FakeEventSource.instances.push(this)
  }

  addEventListener(
    type: string,
    callback: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void {
    if (callback === null) return
    const once = typeof options === 'object' && options.once === true
    const listener = (event: Event | MessageEvent<string>) => {
      if (typeof callback === 'function') callback(event)
      else callback.handleEvent(event)
      if (once) this.listeners.get(type)?.delete(listener)
    }
    const listeners = this.listeners.get(type) ?? new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  close(): void {
    this.readyState = 2
  }

  emit(type: string, data?: string): void {
    if (type === 'open') this.readyState = 1
    const event =
      data === undefined ? new Event(type) : new MessageEvent(type, { data })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
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
    version: '0.1.0',
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
