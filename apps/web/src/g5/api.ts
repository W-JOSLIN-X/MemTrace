import { newIdempotencyKey } from '../g0/api'
import {
  parseConversationCreate,
  parseConversationSnapshot,
  parseConversationTurn,
  parseMemoryEvents,
  parseMemoryLifecycle,
  parseMemoryList,
  parseMemoryMutation,
  parseReflectionJob,
} from './runtime'
import type {
  ConversationCreateResponse,
  ConversationSnapshot,
  ConversationTurnResponse,
  MemoryEditRequest,
  MemoryEventList,
  MemoryId,
  MemoryKind,
  MemoryLifecycleResponse,
  MemoryListResponse,
  MemoryProjection,
  MemoryMode,
  ReflectionJob,
  ReflectionJobId,
  ReviewStatus,
  TaskId,
} from './types'

export class G5ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number | null

  constructor(
    message: string,
    options: { code: string; retryable: boolean; status: number | null },
  ) {
    super(message)
    this.name = 'G5ApiError'
    this.code = options.code
    this.retryable = options.retryable
    this.status = options.status
  }
}

export interface G5Api {
  createTask(
    memoryMode: MemoryMode,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ConversationCreateResponse>
  createTurn(
    taskId: TaskId,
    content: string,
    memoryMode: MemoryMode,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ConversationTurnResponse>
  getTask(taskId: TaskId, signal?: AbortSignal): Promise<ConversationSnapshot>
  listMemories(
    filters?: { kind?: MemoryKind; reviewStatus?: ReviewStatus; cursor?: MemoryId },
    signal?: AbortSignal,
  ): Promise<MemoryListResponse>
  getTaskEvents(
    taskId: TaskId,
    afterEventSeq: number,
    signal?: AbortSignal,
  ): Promise<MemoryEventList>
  getMemoryEvents(afterSeq: number, signal?: AbortSignal): Promise<MemoryEventList>
  getReflectionJob(jobId: ReflectionJobId, signal?: AbortSignal): Promise<ReflectionJob>
  editMemory(
    memoryId: MemoryId,
    request: MemoryEditRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryProjection>
  changeMemory(
    memoryId: MemoryId,
    action: 'confirm' | 'dismiss' | 'pause' | 'resume',
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryLifecycleResponse>
}

export const browserG5Api: G5Api = {
  async createTask(memoryMode, idempotencyKey, signal) {
    return parseConversationCreate(
      await apiJson('/api/v2/tasks', {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({ memory_mode: memoryMode }),
        signal,
      }),
    )
  },

  async createTurn(taskId, content, memoryMode, idempotencyKey, signal) {
    return parseConversationTurn(
      await apiJson(`/api/v2/tasks/${encodeURIComponent(taskId)}/turns`, {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({ content, memory_mode: memoryMode }),
        signal,
      }),
    )
  },

  async getTask(taskId, signal) {
    return parseConversationSnapshot(
      await apiJson(`/api/v2/tasks/${encodeURIComponent(taskId)}`, { signal }),
    )
  },

  async listMemories(filters = {}, signal) {
    const query = new URLSearchParams({ limit: '100' })
    if (filters.kind) query.set('kind', filters.kind)
    if (filters.reviewStatus) query.set('review_status', filters.reviewStatus)
    if (filters.cursor) query.set('cursor', filters.cursor)
    return parseMemoryList(await apiJson(`/api/v2/memories?${query}`, { signal }))
  },

  async getTaskEvents(taskId, afterEventSeq, signal) {
    const query = new URLSearchParams({ after_event_seq: String(afterEventSeq) })
    return parseMemoryEvents(
      await apiJson(`/api/v2/tasks/${encodeURIComponent(taskId)}/events?${query}`, {
        signal,
      }),
    )
  },

  async getMemoryEvents(afterSeq, signal) {
    const query = new URLSearchParams({ after_seq: String(afterSeq) })
    return parseMemoryEvents(await apiJson(`/api/v2/memory-events?${query}`, { signal }))
  },

  async getReflectionJob(jobId, signal) {
    return parseReflectionJob(
      await apiJson(`/api/v2/reflection-jobs/${encodeURIComponent(jobId)}`, {
        signal,
      }),
    )
  },

  async editMemory(memoryId, request, idempotencyKey, signal) {
    return parseMemoryMutation(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}`, {
        method: 'PATCH',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify(request),
        signal,
      }),
    )
  },

  async changeMemory(memoryId, action, idempotencyKey, signal) {
    return parseMemoryLifecycle(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}/${action}`, {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        signal,
      }),
    )
  },
}

export { newIdempotencyKey }

function jsonHeaders(idempotencyKey: string): HeadersInit {
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'Idempotency-Key': idempotencyKey,
  }
}

async function apiJson(path: string, init: RequestInit): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(path, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
      ...init,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new G5ApiError('无法连接到 MemTrace 服务。', {
      code: 'NETWORK_ERROR',
      retryable: true,
      status: null,
    })
  }
  let body: unknown
  try {
    body = (await response.json()) as unknown
  } catch {
    throw new G5ApiError('服务返回了无法解析的响应。', {
      code: 'INVALID_RESPONSE',
      retryable: false,
      status: response.status,
    })
  }
  if (!response.ok) throw responseError(response.status, body)
  return body
}

function responseError(status: number, body: unknown): G5ApiError {
  const fallback = new G5ApiError('请求未完成，请稍后重试。', {
    code: 'HTTP_ERROR',
    retryable: status >= 500,
    status,
  })
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return fallback
  const envelope = body as Record<string, unknown>
  if (typeof envelope.error !== 'object' || envelope.error === null) return fallback
  const error = envelope.error as Record<string, unknown>
  if (
    typeof error.code !== 'string' ||
    typeof error.message !== 'string' ||
    typeof error.retryable !== 'boolean'
  ) {
    return fallback
  }
  return new G5ApiError(error.message, {
    code: error.code,
    retryable: error.retryable,
    status,
  })
}
