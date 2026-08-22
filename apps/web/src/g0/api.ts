import {
  parseDemoSessionResponse,
  parseErrorResponse,
  parseFeedbackCreateAccepted,
  parseMemoryJobResponse,
  parseTaskCreateAccepted,
  parseTaskSnapshot,
} from './runtime'
import type {
  DemoAlias,
  DemoSessionResponse,
  ErrorCode,
  FeedbackCreateAccepted,
  FeedbackCreateRequest,
  MemoryJobId,
  MemoryJobResponse,
  TaskCreateAccepted,
  TaskCreateRequest,
  TaskId,
  TaskSnapshot,
} from './types'

export interface G0Api {
  createTask(
    request: TaskCreateRequest,
    signal?: AbortSignal,
    idempotencyKey?: string,
  ): Promise<TaskCreateAccepted>
  getTask(taskId: TaskId, signal?: AbortSignal): Promise<TaskSnapshot>
  getSession?(signal?: AbortSignal): Promise<DemoSessionResponse>
  createDemoSession?(
    demoAlias: DemoAlias,
    signal?: AbortSignal,
  ): Promise<DemoSessionResponse>
  createFeedback?(
    taskId: TaskId,
    request: FeedbackCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<FeedbackCreateAccepted>
  getMemoryJob?(
    memoryJobId: MemoryJobId,
    signal?: AbortSignal,
  ): Promise<MemoryJobResponse>
}

export class G0ApiError extends Error {
  readonly code: ErrorCode | 'NETWORK_ERROR' | 'INVALID_RESPONSE'
  readonly retryable: boolean
  readonly status: number | null

  constructor(
    message: string,
    options: {
      code: ErrorCode | 'NETWORK_ERROR' | 'INVALID_RESPONSE'
      retryable: boolean
      status: number | null
    },
  ) {
    super(message)
    this.name = 'G0ApiError'
    this.code = options.code
    this.retryable = options.retryable
    this.status = options.status
  }
}

export const browserG0Api: G0Api = {
  async createTask(request, signal, idempotencyKey = newIdempotencyKey()) {
    const response = await safeFetch('/api/v1/tasks', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(request),
      credentials: 'same-origin',
      signal,
    })
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseTaskCreateAccepted(body)
    } catch {
      throw invalidResponse()
    }
  },

  async getTask(taskId, signal) {
    const response = await safeFetch(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      signal,
    })
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseTaskSnapshot(body)
    } catch {
      throw invalidResponse()
    }
  },

  async getSession(signal) {
    const response = await safeFetch('/api/v1/session', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      signal,
    })
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseDemoSessionResponse(body)
    } catch {
      throw invalidResponse()
    }
  },

  async createDemoSession(demoAlias, signal) {
    const response = await safeFetch('/api/v1/session/demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ demo_alias: demoAlias }),
      credentials: 'same-origin',
      signal,
    })
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseDemoSessionResponse(body)
    } catch {
      throw invalidResponse()
    }
  },

  async createFeedback(taskId, request, idempotencyKey, signal) {
    const response = await safeFetch(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/feedback`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(request),
        credentials: 'same-origin',
        signal,
      },
    )
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseFeedbackCreateAccepted(body)
    } catch {
      throw invalidResponse()
    }
  },

  async getMemoryJob(memoryJobId, signal) {
    const response = await safeFetch(
      `/api/v1/memory-jobs/${encodeURIComponent(memoryJobId)}`,
      {
        method: 'GET',
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        signal,
      },
    )
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseMemoryJobResponse(body)
    } catch {
      throw invalidResponse()
    }
  },
}

export function newIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return `memtrace-${globalThis.crypto.randomUUID()}`
  }
  if (typeof globalThis.crypto?.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    globalThis.crypto.getRandomValues(bytes)
    const randomHex = Array.from(bytes, (value) =>
      value.toString(16).padStart(2, '0'),
    ).join('')
    return `memtrace-${randomHex}`
  }
  return `memtrace-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function safeFetch(input: RequestInfo | URL, init: RequestInit) {
  try {
    return await fetch(input, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new G0ApiError('无法连接到 MemTrace 服务，请检查后端是否已启动。', {
      code: 'NETWORK_ERROR',
      retryable: true,
      status: null,
    })
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown
  } catch {
    throw invalidResponse()
  }
}

function responseError(status: number, body: unknown): G0ApiError {
  const parsed = parseErrorResponse(body)
  if (!parsed) return invalidResponse(status)
  return new G0ApiError(parsed.error.message, {
    code: parsed.error.code,
    retryable: parsed.error.retryable,
    status,
  })
}

function invalidResponse(status: number | null = null): G0ApiError {
  return new G0ApiError('服务返回了不符合 G1 契约的数据，已停止处理。', {
    code: 'INVALID_RESPONSE',
    retryable: false,
    status,
  })
}
