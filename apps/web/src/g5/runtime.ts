import type {
  ConversationCreateResponse,
  ConversationMessage,
  ConversationSnapshot,
  ConversationTurnResponse,
  ConversationTurnState,
  MemoryDecision,
  MemoryEvent,
  MemoryEventList,
  MemoryKind,
  MemoryLifecycleResponse,
  MemoryListResponse,
  MemoryProjection,
  ProviderMode,
  ReflectionJob,
  ReviewStatus,
  StageUsage,
} from './types'

const patterns = {
  task: /^task_[0-9A-HJKMNP-TV-Z]{26}$/,
  run: /^run_[0-9A-HJKMNP-TV-Z]{26}$/,
  message: /^msg_[0-9A-HJKMNP-TV-Z]{26}$/,
  memory: /^mem_[0-9A-HJKMNP-TV-Z]{26}$/,
  version: /^memver_[0-9A-HJKMNP-TV-Z]{26}$/,
  job: /^job_[0-9A-HJKMNP-TV-Z]{26}$/,
  hash: /^sha256:[0-9a-f]{64}$/,
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('expected object')
  }
  return value as Record<string, unknown>
}

function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const row = object(value)
  const actual = Object.keys(row).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, i) => key !== expected[i])) {
    throw new Error('unknown or missing field')
  }
  return row
}

function string(value: unknown, max = Number.MAX_SAFE_INTEGER): string {
  if (typeof value !== 'string' || value.length > max) throw new Error('expected string')
  return value
}

function id(value: unknown, pattern: RegExp): string {
  const parsed = string(value, 96)
  if (!pattern.test(parsed)) throw new Error('invalid id')
  return parsed
}

function number(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
    throw new Error('invalid number')
  }
  return value
}

function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  const parsed = number(value, min, max)
  if (!Number.isInteger(parsed)) throw new Error('expected integer')
  return parsed
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): T {
  const parsed = string(value)
  if (!values.includes(parsed as T)) throw new Error('invalid enum')
  return parsed as T
}

function nullable<T>(value: unknown, parse: (input: unknown) => T): T | null {
  return value === null ? null : parse(value)
}

const providerModes = ['real', 'mock'] as const
const memoryModes = ['on', 'off'] as const
const kinds = ['preference', 'rule', 'experience'] as const
const reviewStatuses = ['pending', 'active', 'paused', 'archived', 'superseded'] as const

function parseProviderMode(value: unknown): ProviderMode {
  return oneOf(value, providerModes)
}

function parseKind(value: unknown): MemoryKind {
  return oneOf(value, kinds)
}

function parseReviewStatus(value: unknown): ReviewStatus {
  return oneOf(value, reviewStatuses)
}

function parseMessage(value: unknown): ConversationMessage {
  const row = exact(value, [
    'message_id',
    'run_id',
    'role',
    'content',
    'turn_index',
    'created_at',
  ])
  return {
    message_id: id(row.message_id, patterns.message) as ConversationMessage['message_id'],
    run_id: nullable(row.run_id, (item) => id(item, patterns.run)) as ConversationMessage['run_id'],
    role: oneOf(row.role, ['user', 'assistant'] as const),
    content: string(row.content, 262_144),
    turn_index: integer(row.turn_index, 1),
    created_at: string(row.created_at, 64),
  }
}

function parseUsage(value: unknown): StageUsage {
  const row = exact(value, [
    'stage',
    'provider_mode',
    'model',
    'prompt_hash',
    'input_tokens',
    'output_tokens',
    'total_tokens',
    'reasoning_tokens',
    'latency_ms',
  ])
  const promptHash = string(row.prompt_hash, 71)
  if (!patterns.hash.test(promptHash)) throw new Error('invalid prompt hash')
  return {
    stage: oneOf(
      row.stage,
      ['summary', 'applicability', 'chat', 'reflection', 'consolidation', 'effect'] as const,
    ),
    provider_mode: parseProviderMode(row.provider_mode),
    model: string(row.model, 128),
    prompt_hash: promptHash,
    input_tokens: integer(row.input_tokens),
    output_tokens: integer(row.output_tokens),
    total_tokens: integer(row.total_tokens),
    reasoning_tokens: nullable(row.reasoning_tokens, (item) => integer(item)),
    latency_ms: integer(row.latency_ms),
  }
}

function parseDecision(value: unknown): MemoryDecision {
  const row = exact(value, [
    'memory_id',
    'applicability',
    'reason_code',
    'confidence',
    'injected',
    'estimated_tokens',
    'effect',
  ])
  if (typeof row.injected !== 'boolean') throw new Error('invalid injected flag')
  return {
    memory_id: id(row.memory_id, patterns.memory) as MemoryDecision['memory_id'],
    applicability: oneOf(
      row.applicability,
      ['applicable', 'current_instruction_override', 'conflict', 'irrelevant'] as const,
    ),
    reason_code: oneOf(
      row.reason_code,
      [
        'semantic_match',
        'current_instruction_override',
        'memory_conflict',
        'scope_mismatch',
        'outdated',
        'irrelevant',
        'ambiguous',
      ] as const,
    ),
    confidence: number(row.confidence, 0, 1),
    injected: row.injected,
    estimated_tokens: integer(row.estimated_tokens, 0, 100),
    effect: nullable(row.effect, (item) =>
      oneOf(item, ['applied', 'violated', 'not_observable', 'unknown'] as const),
    ),
  }
}

export function parseConversationCreate(value: unknown): ConversationCreateResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'task_id',
    'provider_mode',
    'model',
    'memory_mode',
    'created_at',
  ])
  if (row.schema_version !== '2.0.0') throw new Error('invalid schema version')
  return {
    schema_version: '2.0.0',
    request_id: string(row.request_id, 64),
    task_id: id(row.task_id, patterns.task) as ConversationCreateResponse['task_id'],
    provider_mode: parseProviderMode(row.provider_mode),
    model: string(row.model, 128),
    memory_mode: oneOf(row.memory_mode, memoryModes),
    created_at: string(row.created_at, 64),
  }
}

export function parseConversationTurn(value: unknown): ConversationTurnResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'task_id',
    'run_id',
    'turn_index',
    'user_message',
    'assistant_message',
    'reflection_job_id',
    'memory_mode',
    'memory_decisions',
    'usage',
  ])
  if (row.schema_version !== '2.0.0') throw new Error('invalid schema version')
  if (!Array.isArray(row.memory_decisions) || !Array.isArray(row.usage)) {
    throw new Error('invalid collections')
  }
  return {
    schema_version: '2.0.0',
    request_id: string(row.request_id, 64),
    task_id: id(row.task_id, patterns.task) as ConversationTurnResponse['task_id'],
    run_id: id(row.run_id, patterns.run) as ConversationTurnResponse['run_id'],
    turn_index: integer(row.turn_index, 1),
    user_message: parseMessage(row.user_message),
    assistant_message: parseMessage(row.assistant_message),
    reflection_job_id: nullable(row.reflection_job_id, (item) =>
      id(item, patterns.job),
    ) as ConversationTurnResponse['reflection_job_id'],
    memory_mode: oneOf(row.memory_mode, memoryModes),
    memory_decisions: row.memory_decisions.map(parseDecision),
    usage: row.usage.map(parseUsage),
  }
}

function parseConversationTurnState(value: unknown): ConversationTurnState {
  const row = exact(value, [
    'run_id',
    'turn_index',
    'reflection_job_id',
    'memory_decisions',
    'usage',
  ])
  if (!Array.isArray(row.memory_decisions) || !Array.isArray(row.usage)) {
    throw new Error('invalid last turn collections')
  }
  if (row.memory_decisions.length > 50 || row.usage.length < 1 || row.usage.length > 102) {
    throw new Error('invalid last turn collection size')
  }
  return {
    run_id: id(row.run_id, patterns.run) as ConversationTurnState['run_id'],
    turn_index: integer(row.turn_index, 1),
    reflection_job_id: nullable(row.reflection_job_id, (item) =>
      id(item, patterns.job),
    ) as ConversationTurnState['reflection_job_id'],
    memory_decisions: row.memory_decisions.map(parseDecision),
    usage: row.usage.map(parseUsage),
  }
}

export function parseConversationSnapshot(value: unknown): ConversationSnapshot {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'task_id',
    'memory_mode',
    'provider_mode',
    'model',
    'messages',
    'last_turn',
    'last_event_seq',
    'created_at',
    'updated_at',
  ])
  if (row.schema_version !== '2.0.0' || !Array.isArray(row.messages)) {
    throw new Error('invalid snapshot')
  }
  return {
    schema_version: '2.0.0',
    request_id: string(row.request_id, 64),
    task_id: id(row.task_id, patterns.task) as ConversationSnapshot['task_id'],
    memory_mode: oneOf(row.memory_mode, memoryModes),
    provider_mode: parseProviderMode(row.provider_mode),
    model: string(row.model, 128),
    messages: row.messages.map(parseMessage),
    last_turn: nullable(row.last_turn, parseConversationTurnState),
    last_event_seq: integer(row.last_event_seq),
    created_at: string(row.created_at, 64),
    updated_at: string(row.updated_at, 64),
  }
}

function parseMemory(value: unknown): MemoryProjection {
  const row = exact(value, [
    'memory_id',
    'kind',
    'content',
    'applies_when',
    'review_status',
    'confidence',
    'current_version_id',
    'version',
    'source_type',
    'created_at',
    'updated_at',
  ])
  return {
    memory_id: id(row.memory_id, patterns.memory) as MemoryProjection['memory_id'],
    kind: parseKind(row.kind),
    content: string(row.content, 4000),
    applies_when: string(row.applies_when, 500),
    review_status: parseReviewStatus(row.review_status),
    confidence: number(row.confidence, 0, 1),
    current_version_id: id(
      row.current_version_id,
      patterns.version,
    ) as MemoryProjection['current_version_id'],
    version: integer(row.version, 1),
    source_type: oneOf(row.source_type, ['conversation_turn', 'user_edit'] as const),
    created_at: string(row.created_at, 64),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryList(value: unknown): MemoryListResponse {
  const row = exact(value, ['request_id', 'items', 'next_cursor'])
  if (!Array.isArray(row.items)) throw new Error('invalid memory items')
  return {
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemory),
    next_cursor: nullable(row.next_cursor, (item) =>
      id(item, patterns.memory),
    ) as MemoryListResponse['next_cursor'],
  }
}

export function parseReflectionJob(value: unknown): ReflectionJob {
  const row = exact(value, [
    'request_id',
    'job_id',
    'task_id',
    'run_id',
    'turn_index',
    'status',
    'attempt',
    'mutation_decision',
    'provider_model',
    'schema_version',
    'error_code',
    'created_at',
    'updated_at',
  ])
  if (row.schema_version !== '2.0') throw new Error('invalid job schema')
  return {
    request_id: string(row.request_id, 64),
    job_id: id(row.job_id, patterns.job) as ReflectionJob['job_id'],
    task_id: id(row.task_id, patterns.task) as ReflectionJob['task_id'],
    run_id: id(row.run_id, patterns.run) as ReflectionJob['run_id'],
    turn_index: integer(row.turn_index, 1),
    status: oneOf(row.status, ['pending', 'running', 'completed', 'failed'] as const),
    attempt: integer(row.attempt),
    mutation_decision: nullable(row.mutation_decision, (item) =>
      oneOf(item, ['mutate', 'noop', 'needs_review'] as const),
    ),
    provider_model: string(row.provider_model, 128),
    schema_version: '2.0',
    error_code: nullable(row.error_code, (item) => string(item, 64)),
    created_at: string(row.created_at, 64),
    updated_at: string(row.updated_at, 64),
  }
}

function parseMemoryEvent(value: unknown): MemoryEvent {
  const row = exact(value, [
    'event_id',
    'event_seq',
    'event_type',
    'memory_id',
    'version_id',
    'old_status',
    'new_status',
    'reason_code',
    'job_id',
    'created_at',
  ])
  return {
    event_id: string(row.event_id, 96),
    event_seq: integer(row.event_seq, 1),
    event_type: string(row.event_type, 96),
    memory_id: nullable(row.memory_id, (item) => id(item, patterns.memory)) as MemoryEvent['memory_id'],
    version_id: nullable(row.version_id, (item) => id(item, patterns.version)) as MemoryEvent['version_id'],
    old_status: nullable(row.old_status, parseReviewStatus),
    new_status: nullable(row.new_status, parseReviewStatus),
    reason_code: nullable(row.reason_code, (item) => string(item, 64)),
    job_id: nullable(row.job_id, (item) => id(item, patterns.job)) as MemoryEvent['job_id'],
    created_at: nullable(row.created_at, (item) => string(item, 64)),
  }
}

export function parseMemoryEvents(value: unknown): MemoryEventList {
  const row = exact(value, ['request_id', 'items', 'next_seq'])
  if (!Array.isArray(row.items)) throw new Error('invalid events')
  if (row.items.length > 100) throw new Error('too many events')
  return {
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemoryEvent),
    next_seq: nullable(row.next_seq, (item) => integer(item)),
  }
}

export function parseMemoryLifecycle(value: unknown): MemoryLifecycleResponse {
  const row = exact(value, [
    'request_id',
    'memory_id',
    'old_status',
    'new_status',
    'updated_at',
  ])
  return {
    request_id: string(row.request_id, 64),
    memory_id: id(row.memory_id, patterns.memory) as MemoryLifecycleResponse['memory_id'],
    old_status: parseReviewStatus(row.old_status),
    new_status: parseReviewStatus(row.new_status),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryMutation(value: unknown): MemoryProjection {
  const row = object(value)
  if ('memory_id' in row && 'review_status' in row) return parseMemory(row)
  const edit = exact(value, [
    'request_id',
    'memory_id',
    'kind',
    'content',
    'applies_when',
    'status',
    'current_version_id',
    'updated_at',
  ])
  return {
    memory_id: id(edit.memory_id, patterns.memory) as MemoryProjection['memory_id'],
    kind: parseKind(edit.kind),
    content: string(edit.content, 4000),
    applies_when: string(edit.applies_when, 500),
    review_status: parseReviewStatus(edit.status),
    confidence: 1,
    current_version_id: id(
      edit.current_version_id,
      patterns.version,
    ) as MemoryProjection['current_version_id'],
    version: 1,
    source_type: 'user_edit',
    created_at: string(edit.updated_at, 64),
    updated_at: string(edit.updated_at, 64),
  }
}
