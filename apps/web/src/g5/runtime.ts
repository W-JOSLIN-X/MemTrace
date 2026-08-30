import type {
  ConversationCreateResponse,
  ConversationMessage,
  ConversationListResponse,
  ConversationSnapshot,
  ConversationTurnResponse,
  ConversationTurnState,
  MemoryDecision,
  MemoryDetailResponse,
  MemoryEvent,
  MemoryEventList,
  MemoryEvidenceProjection,
  MemoryFeedbackResponse,
  MemoryKind,
  MemoryLifecycleResponse,
  MemoryListResponse,
  MemoryProjection,
  MemoryRelation,
  MemoryRelationListResponse,
  MemoryConflictDetail,
  MemoryConflictResolveResponse,
  MemoryDeleteResponse,
  MemoryUsage,
  MemoryUsageListResponse,
  MemoryVersionDiffResponse,
  MemoryVersionProjection,
  MemoryPackDocument,
  PackCommitResponse,
  PackPreview,
  ProviderMode,
  ReflectionJob,
  ReviewStatus,
  StageUsage,
  SourceTaskDeleteResponse,
  ToolCall,
} from './types'

const patterns = {
  task: /^task_[0-9A-HJKMNP-TV-Z]{26}$/,
  run: /^run_[0-9A-HJKMNP-TV-Z]{26}$/,
  message: /^msg_[0-9A-HJKMNP-TV-Z]{26}$/,
  memory: /^mem_[0-9A-HJKMNP-TV-Z]{26}$/,
  version: /^memver_[0-9A-HJKMNP-TV-Z]{26}$/,
  evidence: /^evidence_[0-9A-HJKMNP-TV-Z]{26}$/,
  usage: /^usage_[0-9A-HJKMNP-TV-Z]{26}$/,
  relation: /^rel_[0-9A-HJKMNP-TV-Z]{26}$/,
  pack: /^pack_[0-9A-HJKMNP-TV-Z]{26}$/,
  batch: /^batch_[0-9A-HJKMNP-TV-Z]{26}$/,
  externalCard: /^card_[A-Za-z0-9_-]{1,64}$/,
  hexHash: /^[0-9a-f]{64}$/,
  job: /^job_[0-9A-HJKMNP-TV-Z]{26}$/,
  tool: /^tool_[0-9A-HJKMNP-TV-Z]{26}$/,
  toolResult: /^toolres_[0-9A-HJKMNP-TV-Z]{26}$/,
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
    'first_token_ms',
  ])
  const promptHash = string(row.prompt_hash, 71)
  if (!patterns.hash.test(promptHash)) throw new Error('invalid prompt hash')
  return {
    stage: oneOf(
      row.stage,
      [
        'summary',
        'applicability',
        'tool_planning',
        'chat',
        'reflection',
        'consolidation',
        'effect',
      ] as const,
    ),
    provider_mode: parseProviderMode(row.provider_mode),
    model: string(row.model, 128),
    prompt_hash: promptHash,
    input_tokens: integer(row.input_tokens),
    output_tokens: integer(row.output_tokens),
    total_tokens: integer(row.total_tokens),
    reasoning_tokens: nullable(row.reasoning_tokens, (item) => integer(item)),
    latency_ms: integer(row.latency_ms),
    first_token_ms: nullable(row.first_token_ms, (item) => integer(item)),
  }
}

function parseToolCall(value: unknown): ToolCall {
  const row = exact(value, [
    'tool_call_id',
    'tool_name',
    'reason',
    'args_summary',
    'status',
    'latency_ms',
    'result_ref',
    'result',
  ])
  const args = exact(row.args_summary, ['language', 'code_source', 'code_bytes'])
  const status = oneOf(row.status, ['running', 'succeeded', 'failed'] as const)
  const result = nullable(row.result, (input) => {
    const resultRow = exact(input, ['valid', 'syntax_error'])
    if (typeof resultRow.valid !== 'boolean') throw new Error('invalid tool result')
    const syntaxError = nullable(resultRow.syntax_error, (errorInput) => {
      const error = exact(errorInput, [
        'message',
        'line',
        'column',
        'end_line',
        'end_column',
      ])
      return {
        message: string(error.message, 200),
        line: nullable(error.line, (item) => integer(item, 1)),
        column: nullable(error.column, (item) => integer(item, 1)),
        end_line: nullable(error.end_line, (item) => integer(item, 1)),
        end_column: nullable(error.end_column, (item) => integer(item, 1)),
      }
    })
    if (resultRow.valid === (syntaxError !== null)) throw new Error('inconsistent tool result')
    return { valid: resultRow.valid, syntax_error: syntaxError }
  })
  const latency = nullable(row.latency_ms, (item) => number(item))
  const resultRef = nullable(row.result_ref, (item) => id(item, patterns.toolResult))
  if (status === 'running' && (latency !== null || resultRef !== null || result !== null)) {
    throw new Error('running tool has result')
  }
  if (status === 'succeeded' && (latency === null || resultRef === null || result === null)) {
    throw new Error('successful tool is incomplete')
  }
  if (status === 'failed' && (latency === null || resultRef !== null || result !== null)) {
    throw new Error('failed tool is inconsistent')
  }
  return {
    tool_call_id: id(row.tool_call_id, patterns.tool) as ToolCall['tool_call_id'],
    tool_name: oneOf(row.tool_name, ['python_ast_check'] as const),
    reason: string(row.reason, 240),
    args_summary: {
      language: oneOf(args.language, ['python'] as const),
      code_source: oneOf(
        args.code_source,
        ['fenced_python', 'whole_task_valid_python'] as const,
      ),
      code_bytes: integer(args.code_bytes, 1, 102_400),
    },
    status,
    latency_ms: latency,
    result_ref: resultRef as ToolCall['result_ref'],
    result,
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
  if (row.schema_version !== '2.1.0') throw new Error('invalid schema version')
  return {
    schema_version: '2.1.0',
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
    'tool_calls',
    'usage',
  ])
  if (row.schema_version !== '2.1.0') throw new Error('invalid schema version')
  if (
    !Array.isArray(row.memory_decisions) ||
    !Array.isArray(row.tool_calls) ||
    !Array.isArray(row.usage)
  ) {
    throw new Error('invalid collections')
  }
  return {
    schema_version: '2.1.0',
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
    tool_calls: row.tool_calls.map(parseToolCall),
    usage: row.usage.map(parseUsage),
  }
}

function parseConversationTurnState(value: unknown): ConversationTurnState {
  const row = exact(value, [
    'run_id',
    'turn_index',
    'reflection_job_id',
    'memory_decisions',
    'tool_calls',
    'usage',
  ])
  if (
    !Array.isArray(row.memory_decisions) ||
    !Array.isArray(row.tool_calls) ||
    !Array.isArray(row.usage)
  ) {
    throw new Error('invalid last turn collections')
  }
  if (
    row.memory_decisions.length > 50 ||
    row.tool_calls.length > 1 ||
    row.usage.length < 1 ||
    row.usage.length > 102
  ) {
    throw new Error('invalid last turn collection size')
  }
  return {
    run_id: id(row.run_id, patterns.run) as ConversationTurnState['run_id'],
    turn_index: integer(row.turn_index, 1),
    reflection_job_id: nullable(row.reflection_job_id, (item) =>
      id(item, patterns.job),
    ) as ConversationTurnState['reflection_job_id'],
    memory_decisions: row.memory_decisions.map(parseDecision),
    tool_calls: row.tool_calls.map(parseToolCall),
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
  if (row.schema_version !== '2.1.0' || !Array.isArray(row.messages)) {
    throw new Error('invalid snapshot')
  }
  return {
    schema_version: '2.1.0',
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

export function parseConversationList(value: unknown): ConversationListResponse {
  const row = exact(value, ['schema_version', 'request_id', 'items', 'next_cursor'])
  if (row.schema_version !== '2.1.0' || !Array.isArray(row.items) || row.items.length > 100) {
    throw new Error('invalid conversation list')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    items: row.items.map((value) => {
      const item = exact(value, [
        'task_id',
        'title',
        'memory_mode',
        'message_count',
        'created_at',
        'updated_at',
      ])
      return {
        task_id: id(item.task_id, patterns.task) as ConversationListResponse['items'][number]['task_id'],
        title: string(item.title, 120),
        memory_mode: oneOf(item.memory_mode, memoryModes),
        message_count: integer(item.message_count),
        created_at: string(item.created_at, 64),
        updated_at: string(item.updated_at, 64),
      }
    }),
    next_cursor: nullable(row.next_cursor, (item) => id(item, patterns.task)) as ConversationListResponse['next_cursor'],
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
    'retrieved_count',
    'injected_count',
    'verified_applied_count',
    'helpful_count',
    'harmful_count',
    'stale_count',
    'last_used_at',
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
    source_type: oneOf(row.source_type, ['conversation_turn', 'user_edit', 'import'] as const),
    retrieved_count: integer(row.retrieved_count),
    injected_count: integer(row.injected_count),
    verified_applied_count: integer(row.verified_applied_count),
    helpful_count: integer(row.helpful_count),
    harmful_count: integer(row.harmful_count),
    stale_count: integer(row.stale_count),
    last_used_at: nullable(row.last_used_at, (item) => string(item, 64)),
    created_at: string(row.created_at, 64),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryList(value: unknown): MemoryListResponse {
  const row = exact(value, ['schema_version', 'request_id', 'items', 'next_cursor'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory schema')
  if (!Array.isArray(row.items)) throw new Error('invalid memory items')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemory),
    next_cursor: nullable(row.next_cursor, (item) =>
      id(item, patterns.memory),
    ) as MemoryListResponse['next_cursor'],
  }
}

function parseMemoryVersion(value: unknown): MemoryVersionProjection {
  const row = exact(value, [
    'version_id',
    'version',
    'kind',
    'content',
    'applies_when',
    'review_status',
    'confidence',
    'created_by_action',
    'created_at',
  ])
  return {
    version_id: id(row.version_id, patterns.version) as MemoryVersionProjection['version_id'],
    version: integer(row.version, 1),
    kind: parseKind(row.kind),
    content: string(row.content, 4000),
    applies_when: string(row.applies_when, 500),
    review_status: parseReviewStatus(row.review_status),
    confidence: number(row.confidence, 0, 1),
    created_by_action: oneOf(
      row.created_by_action,
      [
        'accept',
        'edit_accept',
        'edit',
        'import',
        'merge',
        'scope_resolution',
        'llm_extract',
        'llm_update',
        'llm_supersede',
        'llm_coexist',
        'user_edit',
        'user_restore',
      ] as const,
    ),
    created_at: string(row.created_at, 64),
  }
}

function parseMemoryEvidence(value: unknown): MemoryEvidenceProjection {
  const row = exact(value, [
    'evidence_id',
    'message_id',
    'task_id',
    'turn_index',
    'source_type',
    'is_primary',
    'created_at',
  ])
  if (typeof row.is_primary !== 'boolean') throw new Error('invalid evidence primary flag')
  return {
    evidence_id: id(row.evidence_id, patterns.evidence) as MemoryEvidenceProjection['evidence_id'],
    message_id: id(row.message_id, patterns.message) as MemoryEvidenceProjection['message_id'],
    task_id: id(row.task_id, patterns.task) as MemoryEvidenceProjection['task_id'],
    turn_index: integer(row.turn_index, 1),
    source_type: oneOf(row.source_type, ['conversation_turn', 'user_edit'] as const),
    is_primary: row.is_primary,
    created_at: string(row.created_at, 64),
  }
}

export function parseMemoryDetail(value: unknown): MemoryDetailResponse {
  const row = exact(value, ['schema_version', 'request_id', 'memory', 'versions', 'evidence'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory detail schema')
  if (!Array.isArray(row.versions) || !Array.isArray(row.evidence)) {
    throw new Error('invalid memory detail collections')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    memory: parseMemory(row.memory),
    versions: row.versions.map(parseMemoryVersion),
    evidence: row.evidence.map(parseMemoryEvidence),
  }
}

export function parseMemoryVersionDiff(value: unknown): MemoryVersionDiffResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'from_version',
    'to_version',
    'changed_fields',
  ])
  if (row.schema_version !== '2.1.0' || !Array.isArray(row.changed_fields)) {
    throw new Error('invalid memory diff')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    from_version: parseMemoryVersion(row.from_version),
    to_version: parseMemoryVersion(row.to_version),
    changed_fields: row.changed_fields.map((item) =>
      oneOf(item, ['kind', 'content', 'applies_when', 'review_status', 'confidence'] as const),
    ),
  }
}

function parseMemoryUsage(value: unknown): MemoryUsage {
  const row = exact(value, [
    'usage_id',
    'task_id',
    'run_id',
    'memory_id',
    'memory_version_id',
    'injected',
    'estimated_tokens',
    'verification_status',
    'user_effect',
    'created_at',
    'updated_at',
  ])
  if (typeof row.injected !== 'boolean') throw new Error('invalid usage injected flag')
  return {
    usage_id: id(row.usage_id, patterns.usage) as MemoryUsage['usage_id'],
    task_id: id(row.task_id, patterns.task) as MemoryUsage['task_id'],
    run_id: id(row.run_id, patterns.run) as MemoryUsage['run_id'],
    memory_id: id(row.memory_id, patterns.memory) as MemoryUsage['memory_id'],
    memory_version_id: id(row.memory_version_id, patterns.version) as MemoryUsage['memory_version_id'],
    injected: row.injected,
    estimated_tokens: integer(row.estimated_tokens),
    verification_status: oneOf(
      row.verification_status,
      ['pending', 'applied', 'violated', 'not_observable', 'unknown'] as const,
    ),
    user_effect: nullable(row.user_effect, (item) =>
      oneOf(item, ['helpful', 'harmful', 'stale'] as const),
    ),
    created_at: string(row.created_at, 64),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryUsages(value: unknown): MemoryUsageListResponse {
  const row = exact(value, ['schema_version', 'request_id', 'items', 'next_cursor'])
  if (row.schema_version !== '2.1.0' || !Array.isArray(row.items)) {
    throw new Error('invalid memory usage page')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemoryUsage),
    next_cursor: nullable(row.next_cursor, (item) => id(item, patterns.usage)) as MemoryUsageListResponse['next_cursor'],
  }
}

function parseMemoryRelation(value: unknown): MemoryRelation {
  const row = exact(value, [
    'relation_id',
    'from_memory_id',
    'to_memory_id',
    'relation_type',
    'status',
    'resolution_action',
    'resolution_memory_id',
    'created_at',
  ])
  return {
    relation_id: id(row.relation_id, patterns.relation) as MemoryRelation['relation_id'],
    from_memory_id: id(row.from_memory_id, patterns.memory) as MemoryRelation['from_memory_id'],
    to_memory_id: id(row.to_memory_id, patterns.memory) as MemoryRelation['to_memory_id'],
    relation_type: oneOf(
      row.relation_type,
      ['duplicate_of', 'conflicts_with', 'supersedes', 'reinforces', 'merged_into', 'related_to'] as const,
    ),
    status: oneOf(row.status, ['unresolved', 'resolved'] as const),
    resolution_action: nullable(row.resolution_action, (item) =>
      oneOf(item, ['prefer', 'separate_scopes', 'merge', 'pause_both'] as const),
    ),
    resolution_memory_id: nullable(row.resolution_memory_id, (item) =>
      id(item, patterns.memory),
    ) as MemoryRelation['resolution_memory_id'],
    created_at: string(row.created_at, 64),
  }
}

export function parseMemoryRelations(value: unknown): MemoryRelationListResponse {
  const row = exact(value, ['schema_version', 'request_id', 'items', 'next_cursor'])
  if (row.schema_version !== '2.1.0' || !Array.isArray(row.items)) {
    throw new Error('invalid memory relation page')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemoryRelation),
    next_cursor: nullable(row.next_cursor, (item) => id(item, patterns.relation)) as MemoryRelationListResponse['next_cursor'],
  }
}

export function parseMemoryConflict(value: unknown): MemoryConflictDetail {
  const row = exact(value, ['schema_version', 'request_id', 'relation', 'left', 'right'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid conflict schema')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    relation: parseMemoryRelation(row.relation),
    left: parseMemory(row.left),
    right: parseMemory(row.right),
  }
}

export function parseMemoryConflictResolution(value: unknown): MemoryConflictResolveResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'relation_id',
    'action',
    'status',
    'resolution_memory_id',
  ])
  if (row.schema_version !== '2.1.0' || row.status !== 'resolved') {
    throw new Error('invalid conflict resolution')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    relation_id: id(row.relation_id, patterns.relation) as MemoryConflictResolveResponse['relation_id'],
    action: oneOf(row.action, ['prefer', 'separate_scopes', 'merge', 'pause_both'] as const),
    status: 'resolved',
    resolution_memory_id: nullable(row.resolution_memory_id, (item) =>
      id(item, patterns.memory),
    ) as MemoryConflictResolveResponse['resolution_memory_id'],
  }
}

export function parseMemoryDelete(value: unknown): MemoryDeleteResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'memory_id',
    'status',
    'deleted_at',
  ])
  if (row.schema_version !== '2.1.0' || row.status !== 'deleted') {
    throw new Error('invalid memory delete response')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    memory_id: id(row.memory_id, patterns.memory) as MemoryDeleteResponse['memory_id'],
    status: 'deleted',
    deleted_at: string(row.deleted_at, 64),
  }
}

export function parseSourceTaskDelete(value: unknown): SourceTaskDeleteResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'task_id',
    'status',
    'memory_policy',
    'affected_memory_count',
  ])
  if (
    row.schema_version !== '2.1.0' ||
    row.status !== 'deleted' ||
    row.memory_policy !== 'preserve_and_mark_evidence_missing'
  ) {
    throw new Error('invalid source task delete response')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    task_id: id(row.task_id, patterns.task) as SourceTaskDeleteResponse['task_id'],
    status: 'deleted',
    memory_policy: 'preserve_and_mark_evidence_missing',
    affected_memory_count: integer(row.affected_memory_count),
  }
}

export function parseMemoryPack(value: unknown): MemoryPackDocument {
  const row = exact(value, [
    'schema_ref',
    'format',
    'format_version',
    'pack_id',
    'name',
    'description',
    'created_at',
    'producer',
    'source',
    'privacy',
    'cards',
    'relations',
    'integrity',
  ])
  if (
    row.schema_ref !== 'memtrace-memory-pack@2.0.0' ||
    row.format !== 'memtrace-memory-pack' ||
    row.format_version !== '2.0.0' ||
    !Array.isArray(row.cards) ||
    !Array.isArray(row.relations)
  ) {
    throw new Error('invalid memory pack')
  }
  const producer = exact(row.producer, ['name', 'version'])
  const source = exact(row.source, ['kind', 'trust'])
  const privacy = exact(row.privacy, ['contains_raw_evidence', 'anonymized'])
  const integrity = exact(row.integrity, ['algorithm', 'canonical_payload_sha256'])
  if (
    privacy.contains_raw_evidence !== false ||
    privacy.anonymized !== true ||
    integrity.algorithm !== 'sha256'
  ) {
    throw new Error('invalid memory pack privacy or integrity')
  }
  const checksum = string(integrity.canonical_payload_sha256, 64)
  if (!patterns.hexHash.test(checksum)) throw new Error('invalid memory pack hash')
  return {
    schema_ref: 'memtrace-memory-pack@2.0.0',
    format: 'memtrace-memory-pack',
    format_version: '2.0.0',
    pack_id: id(row.pack_id, patterns.pack) as MemoryPackDocument['pack_id'],
    name: string(row.name, 80),
    description: string(row.description, 500),
    created_at: string(row.created_at, 64),
    producer: { name: string(producer.name, 80), version: string(producer.version, 32) },
    source: {
      kind: oneOf(source.kind, ['user_export', 'external_import'] as const),
      trust: oneOf(source.trust, ['self_asserted', 'unverified'] as const),
    },
    privacy: { contains_raw_evidence: false, anonymized: true },
    cards: row.cards.map((value) => {
      const card = exact(value, [
        'external_id',
        'schema_version',
        'kind',
        'content',
        'applies_when',
        'claimed_origin',
        'version',
        'updated_at',
      ])
      if (card.schema_version !== '2.0') throw new Error('invalid pack card schema')
      const origin = exact(card.claimed_origin, [
        'source_type',
        'trust_level',
        'created_at',
        'source_version',
      ])
      return {
        external_id: id(card.external_id, patterns.externalCard) as `card_${string}`,
        schema_version: '2.0' as const,
        kind: parseKind(card.kind),
        content: string(card.content, 4000),
        applies_when: string(card.applies_when, 500),
        claimed_origin: {
          source_type: oneOf(origin.source_type, ['conversation_turn', 'user_edit', 'import'] as const),
          trust_level: oneOf(
            origin.trust_level,
            ['user_confirmed', 'self_asserted', 'imported_unverified'] as const,
          ),
          created_at: string(origin.created_at, 64),
          source_version: integer(origin.source_version, 1),
        },
        version: integer(card.version, 1),
        updated_at: string(card.updated_at, 64),
      }
    }),
    relations: row.relations.map((value) => {
      const relation = exact(value, [
        'from_external_id',
        'to_external_id',
        'relation_type',
      ])
      return {
        from_external_id: id(relation.from_external_id, patterns.externalCard) as `card_${string}`,
        to_external_id: id(relation.to_external_id, patterns.externalCard) as `card_${string}`,
        relation_type: oneOf(
          relation.relation_type,
          ['duplicate_of', 'reinforces', 'conflicts_with', 'supersedes', 'merged_into', 'related_to'] as const,
        ),
      }
    }),
    integrity: { algorithm: 'sha256', canonical_payload_sha256: checksum },
  }
}

export function parsePackPreview(value: unknown): PackPreview {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'batch_id',
    'name',
    'description',
    'format_version',
    'legal_new_count',
    'duplicate_count',
    'potential_conflict_count',
    'suspicious_count',
    'items',
    'preview_token',
    'expires_at',
  ])
  if (
    row.schema_version !== '2.1.0' ||
    row.format_version !== '2.0.0' ||
    !Array.isArray(row.items)
  ) {
    throw new Error('invalid pack preview')
  }
  const token = string(row.preview_token, 43)
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('invalid preview token')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    batch_id: id(row.batch_id, patterns.batch) as PackPreview['batch_id'],
    name: string(row.name, 80),
    description: string(row.description, 500),
    format_version: '2.0.0',
    legal_new_count: integer(row.legal_new_count),
    duplicate_count: integer(row.duplicate_count),
    potential_conflict_count: integer(row.potential_conflict_count),
    suspicious_count: integer(row.suspicious_count),
    items: row.items.map((value) => {
      const item = exact(value, [
        'external_id',
        'kind',
        'content',
        'applies_when',
        'classification',
        'reason',
      ])
      return {
        external_id: id(item.external_id, patterns.externalCard) as `card_${string}`,
        kind: parseKind(item.kind),
        content: string(item.content, 4000),
        applies_when: string(item.applies_when, 500),
        classification: oneOf(
          item.classification,
          ['legal_new', 'duplicate', 'potential_conflict', 'suspicious'] as const,
        ),
        reason: nullable(item.reason, (reason) =>
          oneOf(reason, ['exact_duplicate', 'declared_conflict', 'suspicious_text'] as const),
        ),
      }
    }),
    preview_token: token,
    expires_at: string(row.expires_at, 64),
  }
}

export function parsePackCommit(value: unknown): PackCommitResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'batch_id',
    'inserted_count',
    'skipped_count',
    'warning_count',
  ])
  if (row.schema_version !== '2.1.0') throw new Error('invalid pack commit schema')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    batch_id: id(row.batch_id, patterns.batch) as PackCommitResponse['batch_id'],
    inserted_count: integer(row.inserted_count),
    skipped_count: integer(row.skipped_count),
    warning_count: integer(row.warning_count),
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
    new_status: nullable(row.new_status, (item) =>
      oneOf(item, ['pending', 'active', 'paused', 'archived', 'superseded', 'deleted'] as const),
    ),
    reason_code: nullable(row.reason_code, (item) => string(item, 64)),
    job_id: nullable(row.job_id, (item) => id(item, patterns.job)) as MemoryEvent['job_id'],
    created_at: nullable(row.created_at, (item) => string(item, 64)),
  }
}

export function parseMemoryEvents(value: unknown): MemoryEventList {
  const row = exact(value, ['schema_version', 'request_id', 'items', 'next_seq'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory event schema')
  if (!Array.isArray(row.items)) throw new Error('invalid events')
  if (row.items.length > 100) throw new Error('too many events')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    items: row.items.map(parseMemoryEvent),
    next_seq: nullable(row.next_seq, (item) => integer(item)),
  }
}

export function parseMemoryLifecycle(value: unknown): MemoryLifecycleResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'memory_id',
    'old_status',
    'new_status',
    'updated_at',
  ])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory lifecycle schema')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    memory_id: id(row.memory_id, patterns.memory) as MemoryLifecycleResponse['memory_id'],
    old_status: parseReviewStatus(row.old_status),
    new_status: parseReviewStatus(row.new_status),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryFeedback(value: unknown): MemoryFeedbackResponse {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'task_id',
    'memory_id',
    'effect',
    'updated_at',
  ])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory feedback schema')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 64),
    task_id: id(row.task_id, patterns.task) as MemoryFeedbackResponse['task_id'],
    memory_id: id(row.memory_id, patterns.memory) as MemoryFeedbackResponse['memory_id'],
    effect: oneOf(row.effect, ['helpful', 'harmful', 'stale'] as const),
    updated_at: string(row.updated_at, 64),
  }
}

export function parseMemoryMutation(value: unknown): MemoryProjection {
  const row = exact(value, ['schema_version', 'request_id', 'memory'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid memory mutation schema')
  string(row.request_id, 64)
  return parseMemory(row.memory)
}
