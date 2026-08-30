import { newIdempotencyKey } from '../g0/api'
import { csrfHeaders } from '../auth/api'
import {
  parseConversationList,
  parseConversationCreate,
  parseConversationSnapshot,
  parseConversationTurn,
  parseMemoryEvents,
  parseMemoryConflict,
  parseMemoryConflictResolution,
  parseMemoryDelete,
  parseMemoryDetail,
  parseMemoryFeedback,
  parseMemoryLifecycle,
  parseMemoryList,
  parseMemoryMutation,
  parseMemoryPack,
  parseMemoryRelations,
  parseMemoryUsages,
  parseMemoryVersionDiff,
  parsePackCommit,
  parsePackPreview,
  parseReflectionJob,
  parseSourceTaskDelete,
} from './runtime'
import type {
  ConversationCreateResponse,
  ConversationListResponse,
  ConversationSnapshot,
  ConversationTurnResponse,
  MemoryEditRequest,
  MemoryConflictDetail,
  MemoryConflictResolveRequest,
  MemoryConflictResolveResponse,
  MemoryDeleteResponse,
  MemoryDetailResponse,
  MemoryEventList,
  MemoryId,
  MemoryKind,
  MemoryLifecycleResponse,
  MemoryListResponse,
  MemoryProjection,
  MemoryRelationListResponse,
  MemoryUsageListResponse,
  MemoryVersionDiffResponse,
  MemoryVersionId,
  MemoryPackDocument,
  PackCommitResponse,
  PackPreview,
  MemoryMode,
  ReflectionJob,
  ReflectionJobId,
  ReviewStatus,
  SourceTaskDeleteResponse,
  TaskId,
  UserEffect,
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
  listTasks(cursor?: TaskId, signal?: AbortSignal): Promise<ConversationListResponse>
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
    filters?: {
      query?: string
      kind?: MemoryKind
      reviewStatus?: ReviewStatus
      source?: 'conversation_turn' | 'user_edit' | 'import'
      sort?: 'newest' | 'oldest'
      cursor?: MemoryId
    },
    signal?: AbortSignal,
  ): Promise<MemoryListResponse>
  getMemory(memoryId: MemoryId, signal?: AbortSignal): Promise<MemoryDetailResponse>
  getMemoryVersionDiff(
    memoryId: MemoryId,
    fromVersionId: MemoryVersionId,
    toVersionId: MemoryVersionId,
    signal?: AbortSignal,
  ): Promise<MemoryVersionDiffResponse>
  getMemoryUsages(
    memoryId: MemoryId,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<MemoryUsageListResponse>
  getMemoryRelations(
    memoryId: MemoryId,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<MemoryRelationListResponse>
  restoreMemoryVersion(
    memoryId: MemoryId,
    sourceVersionId: MemoryVersionId,
    expectedCurrentVersionId: MemoryVersionId,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryProjection>
  listMemoryConflicts(
    status?: 'unresolved' | 'resolved',
    signal?: AbortSignal,
  ): Promise<MemoryRelationListResponse>
  getMemoryConflict(
    relationId: string,
    signal?: AbortSignal,
  ): Promise<MemoryConflictDetail>
  resolveMemoryConflict(
    relationId: string,
    request: MemoryConflictResolveRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryConflictResolveResponse>
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
    action: 'confirm' | 'dismiss' | 'pause' | 'resume' | 'archive' | 'restore',
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryLifecycleResponse>
  deleteMemory(
    memoryId: MemoryId,
    expectedCurrentVersionId: MemoryVersionId,
    confirmContent: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryDeleteResponse>
  deleteSourceTask(
    taskId: TaskId,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SourceTaskDeleteResponse>
  exportMemoryPack(
    memoryIds: MemoryId[],
    name: string,
    description: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MemoryPackDocument>
  previewMemoryPack(
    bytes: ArrayBuffer,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<PackPreview>
  commitMemoryPack(
    batchId: `batch_${string}`,
    previewToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<PackCommitResponse>
  recordMemoryEffect(
    taskId: TaskId,
    memoryId: MemoryId,
    effect: UserEffect,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<void>
}

export const browserG5Api: G5Api = {
  async listTasks(cursor, signal) {
    const query = new URLSearchParams({ limit: '50' })
    if (cursor) query.set('cursor', cursor)
    return parseConversationList(await apiJson(`/api/v2/tasks?${query}`, { signal }))
  },
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
    if (filters.query) query.set('query', filters.query)
    if (filters.kind) query.set('kind', filters.kind)
    if (filters.reviewStatus) query.set('review_status', filters.reviewStatus)
    if (filters.source) query.set('source', filters.source)
    if (filters.sort) query.set('sort', filters.sort)
    if (filters.cursor) query.set('cursor', filters.cursor)
    return parseMemoryList(await apiJson(`/api/v2/memories?${query}`, { signal }))
  },

  async getMemory(memoryId, signal) {
    return parseMemoryDetail(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}`, { signal }),
    )
  },

  async getMemoryVersionDiff(memoryId, fromVersionId, toVersionId, signal) {
    const query = new URLSearchParams({
      from_version_id: fromVersionId,
      to_version_id: toVersionId,
    })
    return parseMemoryVersionDiff(
      await apiJson(
        `/api/v2/memories/${encodeURIComponent(memoryId)}/version-diff?${query}`,
        { signal },
      ),
    )
  },

  async getMemoryUsages(memoryId, cursor, signal) {
    const query = new URLSearchParams({ limit: '50' })
    if (cursor) query.set('cursor', cursor)
    return parseMemoryUsages(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}/usages?${query}`, {
        signal,
      }),
    )
  },

  async getMemoryRelations(memoryId, cursor, signal) {
    const query = new URLSearchParams({ limit: '50' })
    if (cursor) query.set('cursor', cursor)
    return parseMemoryRelations(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}/relations?${query}`, {
        signal,
      }),
    )
  },

  async restoreMemoryVersion(
    memoryId,
    sourceVersionId,
    expectedCurrentVersionId,
    idempotencyKey,
    signal,
  ) {
    return parseMemoryMutation(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}/versions/restore`, {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({
          source_version_id: sourceVersionId,
          expected_current_version_id: expectedCurrentVersionId,
        }),
        signal,
      }),
    )
  },

  async listMemoryConflicts(status, signal) {
    const query = new URLSearchParams({ limit: '50' })
    if (status) query.set('status', status)
    return parseMemoryRelations(await apiJson(`/api/v2/memory-conflicts?${query}`, { signal }))
  },

  async getMemoryConflict(relationId, signal) {
    return parseMemoryConflict(
      await apiJson(`/api/v2/memory-conflicts/${encodeURIComponent(relationId)}`, { signal }),
    )
  },

  async resolveMemoryConflict(relationId, request, idempotencyKey, signal) {
    return parseMemoryConflictResolution(
      await apiJson(
        `/api/v2/memory-conflicts/${encodeURIComponent(relationId)}/resolve`,
        {
          method: 'POST',
          headers: jsonHeaders(idempotencyKey),
          body: JSON.stringify(request),
          signal,
        },
      ),
    )
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

  async deleteMemory(
    memoryId,
    expectedCurrentVersionId,
    confirmContent,
    idempotencyKey,
    signal,
  ) {
    return parseMemoryDelete(
      await apiJson(`/api/v2/memories/${encodeURIComponent(memoryId)}`, {
        method: 'DELETE',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({
          expected_current_version_id: expectedCurrentVersionId,
          confirm_content: confirmContent,
        }),
        signal,
      }),
    )
  },

  async deleteSourceTask(taskId, idempotencyKey, signal) {
    return parseSourceTaskDelete(
      await apiJson(`/api/v2/tasks/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({
          confirm_task_id: taskId,
          memory_policy: 'preserve_and_mark_evidence_missing',
        }),
        signal,
      }),
    )
  },

  async exportMemoryPack(memoryIds, name, description, idempotencyKey, signal) {
    return parseMemoryPack(
      await apiJson('/api/v2/memory-packs/export', {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({ memory_ids: memoryIds, name, description }),
        signal,
      }),
    )
  },

  async previewMemoryPack(bytes, idempotencyKey, signal) {
    return parsePackPreview(
      await apiJson('/api/v2/memory-packs/import/preview', {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
          ...csrfHeaders(),
        },
        body: bytes,
        signal,
      }),
    )
  },

  async commitMemoryPack(batchId, previewToken, idempotencyKey, signal) {
    return parsePackCommit(
      await apiJson('/api/v2/memory-packs/import/commit', {
        method: 'POST',
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify({
          batch_id: batchId,
          preview_token: previewToken,
          mode: 'import_all_paused',
        }),
        signal,
      }),
    )
  },

  async recordMemoryEffect(taskId, memoryId, effect, idempotencyKey, signal) {
    parseMemoryFeedback(
      await apiJson(
        `/api/v2/tasks/${encodeURIComponent(taskId)}/memory-effect/${encodeURIComponent(memoryId)}/feedback`,
        {
          method: 'POST',
          headers: jsonHeaders(idempotencyKey),
          body: JSON.stringify({ effect }),
          signal,
        },
      ),
    )
  },
}

export { newIdempotencyKey }

function jsonHeaders(idempotencyKey: string): HeadersInit {
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'Idempotency-Key': idempotencyKey,
    ...csrfHeaders(),
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
  if (!response.ok) {
    if (response.status === 401) globalThis.dispatchEvent(new Event('memtrace:auth-required'))
    throw responseError(response.status, body)
  }
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
