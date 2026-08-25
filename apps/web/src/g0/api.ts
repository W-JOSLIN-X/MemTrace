import {
  parseDemoSessionResponse,
  parseErrorResponse,
  parseFeedbackCreateAccepted,
  parseMemoryDetailResponse,
  parseMemoryJobResponse,
  parseMemoryListResponse,
  parseMemoryUsage,
  parseMemoryUsageList,
  parseRetrievalTrace,
  parseResolveRequest,
  parseResolveResponse,
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
  MemoryCardStatus,
  MemoryDetailResponse,
  MemoryId,
  MemoryListResponse,
  MemoryUsage,
  MemoryUsageListResponse,
  RetrievalTrace,
  UserEffect,
  ActiveMemoryEditRequest,
  ResolveRequest,
  ResolveResponse,
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
  retryMemoryJob?(
    memoryJobId: MemoryJobId,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryJobResponse>
  resolveMemoryCandidate?(
    memoryId: MemoryId,
    request: ResolveRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ResolveResponse>
  listMemories?(
    options?: {
      status?: Extract<MemoryCardStatus, 'candidate' | 'active' | 'paused' | 'rejected'>
      cursor?: string
    },
    signal?: AbortSignal,
  ): Promise<MemoryListResponse>
  getMemory?(
    memoryId: MemoryId,
    signal?: AbortSignal,
  ): Promise<MemoryDetailResponse>
  getRetrievalTrace?(taskId: TaskId, signal?: AbortSignal): Promise<RetrievalTrace>
  getTaskMemoryUsages?(taskId: TaskId, signal?: AbortSignal): Promise<MemoryUsageListResponse>
  editMemory?(memoryId: MemoryId, request: ActiveMemoryEditRequest, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  pauseMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  resumeMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  recordMemoryEffect?(taskId: TaskId, memoryId: MemoryId, effect: UserEffect, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryUsage>
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

  async retryMemoryJob(memoryJobId, idempotencyKey, signal) {
    const response = await safeFetch(
      `/api/v1/memory-jobs/${encodeURIComponent(memoryJobId)}/retry`,
      {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
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

  async resolveMemoryCandidate(memoryId, request, idempotencyKey, signal) {
    let normalized: ResolveRequest
    try {
      normalized = parseResolveRequest(request)
    } catch {
      throw invalidResponse()
    }
    const response = await safeFetch(
      `/api/v1/memory-candidates/${encodeURIComponent(memoryId)}/resolve`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(normalized),
        credentials: 'same-origin',
        signal,
      },
    )
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseResolveResponse(body)
    } catch {
      throw invalidResponse()
    }
  },

  async listMemories(options = {}, signal) {
    const query = new URLSearchParams()
    if (options.status) query.set('status', options.status)
    if (options.cursor) query.set('cursor', options.cursor)
    const suffix = query.size > 0 ? `?${query.toString()}` : ''
    const response = await safeFetch(`/api/v1/memories${suffix}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      signal,
    })
    const body = await readJson(response)
    if (!response.ok) throw responseError(response.status, body)
    try {
      return parseMemoryListResponse(body)
    } catch {
      throw invalidResponse()
    }
  },

  async getMemory(memoryId, signal) {
    const response = await safeFetch(
      `/api/v1/memories/${encodeURIComponent(memoryId)}`,
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
      return parseMemoryDetailResponse(body)
    } catch {
      throw invalidResponse()
    }
  },

  async getRetrievalTrace(taskId, signal) {
    const body = await apiJson(`/api/v1/tasks/${encodeURIComponent(taskId)}/retrieval-trace`, { signal })
    return parseRetrievalTrace(body)
  },

  async getTaskMemoryUsages(taskId, signal) {
    const body = await apiJson(`/api/v1/tasks/${encodeURIComponent(taskId)}/memory-usages`, { signal })
    return parseMemoryUsageList(body)
  },

  async editMemory(memoryId, request, idempotencyKey, signal) {
    const body = await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request), signal,
    })
    return parseMemoryDetailResponse(body)
  },

  async pauseMemory(memoryId, versionId, idempotencyKey, signal) {
    return changeMemoryState(memoryId, 'pause', versionId, idempotencyKey, signal)
  },

  async resumeMemory(memoryId, versionId, idempotencyKey, signal) {
    return changeMemoryState(memoryId, 'resume', versionId, idempotencyKey, signal)
  },

  async recordMemoryEffect(taskId, memoryId, effect, idempotencyKey, signal) {
    const body = await apiJson(`/api/v1/tasks/${encodeURIComponent(taskId)}/memory-usages/${encodeURIComponent(memoryId)}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ effect }), signal,
    })
    return parseMemoryUsage(body)
  },
}

async function apiJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await safeFetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    ...init,
  })
  const body = await readJson(response)
  if (!response.ok) throw responseError(response.status, body)
  return body
}

async function changeMemoryState(
  memoryId: MemoryId,
  action: 'pause' | 'resume',
  versionId: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<MemoryDetailResponse> {
  const body = await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ expected_current_version_id: versionId }),
    signal,
  })
  return parseMemoryDetailResponse(body)
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
