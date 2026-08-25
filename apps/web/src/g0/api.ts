import {
  parseDemoSessionResponse,
  parseErrorResponse,
  parseFeedbackCreateAccepted,
  parseMemoryDetailResponse,
  parseMemoryJobResponse,
  parseMemoryListResponse,
  parseMemoryUsage,
  parseMemoryUsageList,
  parseMemoryVersionList,
  parseRetrievalTrace,
  parseResolveRequest,
  parseResolveResponse,
  parseTaskCreateAccepted,
  parseTaskSnapshot,
} from './runtime'
import {
  parseConflictDetect,
  parseConflictDetail,
  parseConflictResolve,
  parseImportBatch,
  parseImportCommit,
  parseMemoryDelete,
  parseMemoryMerge,
  parseMemoryPack,
  parseMemoryRelationList,
  parseMemoryVersionDiff,
  parsePackPreview,
  parseTaskDelete,
} from './g4'
import type {
  ConflictDetectRequest,
  ConflictDetectResponse,
  ConflictDetailResponse,
  ConflictResolveRequest,
  ConflictResolveResponse,
  ImportBatchResponse,
  ImportCommitResponse,
  MemoryDeleteResponse,
  MemoryListOptions,
  MemoryMergeRequest,
  MemoryMergeResponse,
  MemoryPackDocument,
  PackPreviewResponse,
  TaskDeleteResponse,
} from './g4'
import type {
  DemoAlias,
  DemoSessionResponse,
  ErrorCode,
  FeedbackCreateAccepted,
  FeedbackCreateRequest,
  MemoryJobId,
  MemoryJobResponse,
  MemoryDetailResponse,
  MemoryId,
  MemoryListResponse,
  MemoryUsage,
  MemoryUsageListResponse,
  MemoryVersionListResponse,
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
    options?: MemoryListOptions,
    signal?: AbortSignal,
  ): Promise<MemoryListResponse>
  getMemory?(
    memoryId: MemoryId,
    signal?: AbortSignal,
  ): Promise<MemoryDetailResponse>
  getRetrievalTrace?(taskId: TaskId, signal?: AbortSignal): Promise<RetrievalTrace>
  getTaskMemoryUsages?(taskId: TaskId, signal?: AbortSignal): Promise<MemoryUsageListResponse>
  getMemoryVersions?(memoryId: MemoryId, cursor?: string, signal?: AbortSignal): Promise<MemoryVersionListResponse>
  getMemoryUsages?(memoryId: MemoryId, cursor?: string, signal?: AbortSignal): Promise<MemoryUsageListResponse>
  editMemory?(memoryId: MemoryId, request: ActiveMemoryEditRequest, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  pauseMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  resumeMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  recordMemoryEffect?(taskId: TaskId, memoryId: MemoryId, effect: UserEffect, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryUsage>
  getMemoryRelations?(memoryId: MemoryId, cursor?: string, signal?: AbortSignal): Promise<import('./types').MemoryRelationListResponse>
  getMemoryVersionDiff?(memoryId: MemoryId, fromVersionId: string, toVersionId: string, signal?: AbortSignal): Promise<import('./types').MemoryVersionDiffResponse>
  archiveMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  restoreMemory?(memoryId: MemoryId, versionId: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDetailResponse>
  deleteMemory?(memoryId: MemoryId, versionId: string, confirmTitle: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryDeleteResponse>
  deleteSourceTask?(taskId: TaskId, idempotencyKey: string, signal?: AbortSignal): Promise<TaskDeleteResponse>
  listMemoryConflicts?(status?: 'unresolved' | 'resolved', cursor?: string, signal?: AbortSignal): Promise<import('./types').MemoryRelationListResponse>
  getMemoryConflict?(relationId: string, signal?: AbortSignal): Promise<ConflictDetailResponse>
  detectMemoryConflict?(request: ConflictDetectRequest, idempotencyKey: string, signal?: AbortSignal): Promise<ConflictDetectResponse>
  resolveMemoryConflict?(relationId: string, request: ConflictResolveRequest, idempotencyKey: string, signal?: AbortSignal): Promise<ConflictResolveResponse>
  mergeMemories?(request: MemoryMergeRequest, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryMergeResponse>
  exportMemoryPack?(memoryIds: MemoryId[] | null, name: string, description: string, idempotencyKey: string, signal?: AbortSignal): Promise<MemoryPackDocument>
  previewMemoryPack?(file: Uint8Array, idempotencyKey: string, signal?: AbortSignal): Promise<PackPreviewResponse>
  commitMemoryPack?(batchId: string, previewToken: string, idempotencyKey: string, signal?: AbortSignal): Promise<ImportCommitResponse>
  getImportBatch?(batchId: string, signal?: AbortSignal): Promise<ImportBatchResponse>
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
      const session = parseDemoSessionResponse(body)
      globalThis.dispatchEvent?.(new CustomEvent('memtrace:session-changed', { detail: session }))
      return session
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
    if (options.query) query.set('query', options.query)
    if (options.kind) query.set('kind', options.kind)
    if (options.domain) query.set('domain', options.domain)
    if (options.task_type) query.set('task_type', options.task_type)
    if (options.source_type) query.set('source_type', options.source_type)
    if (options.used_after) query.set('used_after', options.used_after)
    if (options.sort) query.set('sort', options.sort)
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

  async getMemoryVersions(memoryId, cursor, signal) {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
    const body = await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}/versions${query}`, { signal })
    return parseMemoryVersionList(body)
  },

  async getMemoryUsages(memoryId, cursor, signal) {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
    const body = await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}/usages${query}`, { signal })
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

  async getMemoryRelations(memoryId, cursor, signal) {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
    return parseMemoryRelationList(await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}/relations${query}`, { signal }))
  },

  async getMemoryVersionDiff(memoryId, fromVersionId, toVersionId, signal) {
    const query = new URLSearchParams({ from_version_id: fromVersionId, to_version_id: toVersionId })
    return parseMemoryVersionDiff(await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}/version-diff?${query}`, { signal }))
  },

  async archiveMemory(memoryId, versionId, idempotencyKey, signal) {
    return changeMemoryState(memoryId, 'archive', versionId, idempotencyKey, signal)
  },

  async restoreMemory(memoryId, versionId, idempotencyKey, signal) {
    return changeMemoryState(memoryId, 'restore', versionId, idempotencyKey, signal)
  },

  async deleteMemory(memoryId, versionId, confirmTitle, idempotencyKey, signal) {
    return parseMemoryDelete(await apiJson(`/api/v1/memories/${encodeURIComponent(memoryId)}`, {
      method: 'DELETE', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ expected_current_version_id: versionId, confirm_title: confirmTitle }), signal,
    }))
  },

  async deleteSourceTask(taskId, idempotencyKey, signal) {
    return parseTaskDelete(await apiJson(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
      method: 'DELETE', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ confirm_task_id: taskId, memory_policy: 'preserve_and_mark_evidence_missing' }), signal,
    }))
  },

  async listMemoryConflicts(status, cursor, signal) {
    const query = new URLSearchParams()
    if (status) query.set('status', status)
    if (cursor) query.set('cursor', cursor)
    const suffix = query.size ? `?${query}` : ''
    return parseMemoryRelationList(await apiJson(`/api/v1/memory-conflicts${suffix}`, { signal }))
  },

  async getMemoryConflict(relationId, signal) {
    return parseConflictDetail(await apiJson(`/api/v1/memory-conflicts/${encodeURIComponent(relationId)}`, { signal }))
  },

  async detectMemoryConflict(request, idempotencyKey, signal) {
    return parseConflictDetect(await apiJson('/api/v1/memory-conflicts', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(request), signal,
    }))
  },

  async resolveMemoryConflict(relationId, request, idempotencyKey, signal) {
    return parseConflictResolve(await apiJson(`/api/v1/memory-conflicts/${encodeURIComponent(relationId)}/resolve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(request), signal,
    }))
  },

  async mergeMemories(request, idempotencyKey, signal) {
    return parseMemoryMerge(await apiJson('/api/v1/memories/merge', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(request), signal,
    }))
  },

  async exportMemoryPack(memoryIds, name, description, idempotencyKey, signal) {
    return parseMemoryPack(await apiJson('/api/v1/memory-packs/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ memory_ids: memoryIds, name, description }), signal,
    }))
  },

  async previewMemoryPack(file, idempotencyKey, signal) {
    return parsePackPreview(await apiJson('/api/v1/memory-packs/import/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: file.slice().buffer as ArrayBuffer, signal,
    }))
  },

  async commitMemoryPack(batchId, previewToken, idempotencyKey, signal) {
    return parseImportCommit(await apiJson('/api/v1/memory-packs/import/commit', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ batch_id: batchId, preview_token: previewToken, mode: 'import_all_paused' }), signal,
    }))
  },

  async getImportBatch(batchId, signal) {
    return parseImportBatch(await apiJson(`/api/v1/memory-packs/import/${encodeURIComponent(batchId)}`, { signal }))
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
  action: 'pause' | 'resume' | 'archive' | 'restore',
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
