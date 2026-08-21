import {
  parseErrorResponse,
  parseTaskCreateAccepted,
  parseTaskSnapshot,
} from './runtime'
import type {
  ErrorCode,
  TaskCreateAccepted,
  TaskCreateRequest,
  TaskId,
  TaskSnapshot,
} from './types'

export interface G0Api {
  createTask(
    request: TaskCreateRequest,
    signal?: AbortSignal,
  ): Promise<TaskCreateAccepted>
  getTask(taskId: TaskId, signal?: AbortSignal): Promise<TaskSnapshot>
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
  async createTask(request, signal) {
    const response = await safeFetch('/api/v1/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
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
  return new G0ApiError('服务返回了不符合 G0 契约的数据，已停止处理。', {
    code: 'INVALID_RESPONSE',
    retryable: false,
    status,
  })
}
