import {
  G0_EVENT_TYPES,
  type ErrorCode,
  type ErrorResponse,
  type DemoSessionResponse,
  type FeedbackCreateAccepted,
  type G0EventType,
  type G0SseEvent,
  type MemoryDetailResponse,
  type MemoryJobResponse,
  type MemoryListResponse,
  type MemoryUsage,
  type MemoryUsageListResponse,
  type RetrievalTrace,
  type ResolveRequest,
  type ResolveResponse,
  type TaskCreateAccepted,
  type TaskSnapshot,
} from './types'

const taskIdPattern = /^task_[0-9A-HJKMNP-TV-Z]{26}$/
const runIdPattern = /^run_[0-9A-HJKMNP-TV-Z]{26}$/
const requestIdPattern = /^req_[0-9A-HJKMNP-TV-Z]{26}$/
const messageIdPattern = /^msg_[0-9A-HJKMNP-TV-Z]{26}$/
const fingerprintIdPattern = /^fp_[0-9A-HJKMNP-TV-Z]{26}$/
const planIdPattern = /^plan_[0-9A-HJKMNP-TV-Z]{26}$/
const toolCallIdPattern = /^tool_[0-9A-HJKMNP-TV-Z]{26}$/
const toolResultIdPattern = /^toolres_[0-9A-HJKMNP-TV-Z]{26}$/
const errorIdPattern = /^err_[0-9A-HJKMNP-TV-Z]{26}$/
const feedbackIdPattern = /^feedback_[0-9A-HJKMNP-TV-Z]{26}$/
const memoryJobIdPattern = /^job_[0-9A-HJKMNP-TV-Z]{26}$/
const memoryIdPattern = /^mem_[0-9A-HJKMNP-TV-Z]{26}$/
const memoryVersionIdPattern = /^memver_[0-9A-HJKMNP-TV-Z]{26}$/
const evidenceIdPattern = /^evidence_[0-9A-HJKMNP-TV-Z]{26}$/
const retrievalTraceIdPattern = /^trace_[0-9A-HJKMNP-TV-Z]{26}$/
const usageIdPattern = /^usage_[0-9A-HJKMNP-TV-Z]{26}$/
const textEncoder = new TextEncoder()

export class ContractError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ContractError'
  }
}

export function utf8ByteLength(value: string): number {
  return textEncoder.encode(value).byteLength
}

export function parseSseEvent(
  expectedType: G0EventType,
  rawData: string,
  wireLastEventId: string,
): G0SseEvent {
  const value = parseJson(rawData, 'SSE event')
  const event = record(value, 'SSE event')
  exactKeys(event, [
    'event_version',
    'event_type',
    'event_seq',
    'task_id',
    'run_id',
    'at',
    'data',
  ])
  constant(event.event_version, '1.0', 'event_version')
  const eventType = enumValue(event.event_type, G0_EVENT_TYPES, 'event_type')
  if (eventType !== expectedType) {
    throw new ContractError(
      `Wire event ${expectedType} does not match data.event_type ${eventType}`,
    )
  }
  patternString(event.task_id, taskIdPattern, 'task_id')
  patternString(event.run_id, runIdPattern, 'run_id')
  timestamp(event.at, 'at')

  const transient =
    eventType === 'memory.retrieval.started' || eventType === 'agent.chunk'
  if (transient) {
    if (event.event_seq !== null) {
      throw new ContractError(`${eventType} must have a null event_seq`)
    }
  } else {
    const eventSequence = positiveInteger(event.event_seq, 'event_seq')
    if (wireLastEventId.length === 0 || wireLastEventId !== String(eventSequence)) {
      throw new ContractError('Persistent SSE id does not match data.event_seq')
    }
  }

  validateEventPayload(eventType, event.data, event.run_id as string)
  return event as unknown as G0SseEvent
}

export function parseTaskCreateAccepted(value: unknown): TaskCreateAccepted {
  const body = record(value, 'TaskCreateAccepted')
  exactKeys(body, [
    'request_id',
    'task_id',
    'run_id',
    'events_url',
    'provider_mode',
    'effective_memory_mode',
  ])
  patternString(body.request_id, requestIdPattern, 'request_id')
  const taskId = patternString(body.task_id, taskIdPattern, 'task_id')
  patternString(body.run_id, runIdPattern, 'run_id')
  const eventsUrl = stringValue(body.events_url, 'events_url')
  if (eventsUrl !== `/api/v1/tasks/${taskId}/events`) {
    throw new ContractError('events_url does not belong to task_id')
  }
  enumValue(body.provider_mode, ['mock', 'real'] as const, 'provider_mode')
  enumValue(
    body.effective_memory_mode,
    ['on', 'off'] as const,
    'effective_memory_mode',
  )
  return body as unknown as TaskCreateAccepted
}

export function parseDemoSessionResponse(value: unknown): DemoSessionResponse {
  const body = record(value, 'DemoSessionResponse')
  exactKeys(body, ['request_id', 'demo_alias', 'expires_at'])
  patternString(body.request_id, requestIdPattern, 'request_id')
  enumValue(body.demo_alias, ['blank_demo', 'seeded_demo'] as const, 'demo_alias')
  timestamp(body.expires_at, 'expires_at')
  return body as unknown as DemoSessionResponse
}

export function parseFeedbackCreateAccepted(
  value: unknown,
): FeedbackCreateAccepted {
  const body = record(value, 'FeedbackCreateAccepted')
  exactKeys(body, [
    'request_id',
    'feedback_id',
    'memory_job_id',
    'feedback_type',
    'job_status',
  ])
  patternString(body.request_id, requestIdPattern, 'request_id')
  patternString(body.feedback_id, feedbackIdPattern, 'feedback_id')
  patternString(body.memory_job_id, memoryJobIdPattern, 'memory_job_id')
  enumValue(
    body.feedback_type,
    [
      'explicit_text',
      'edited_output',
      'rating',
      'accepted',
      'rejected',
      'composite',
    ] as const,
    'feedback_type',
  )
  constant(body.job_status, 'pending', 'job_status')
  return body as unknown as FeedbackCreateAccepted
}

export function parseMemoryJobResponse(value: unknown): MemoryJobResponse {
  const body = record(value, 'MemoryJobResponse')
  exactKeys(body, [
    'request_id',
    'memory_job_id',
    'feedback_id',
    'job_type',
    'status',
    'stage',
    'attempt',
    'candidate_ids',
    'disposition',
    'error_code',
    'retryable',
    'created_at',
    'updated_at',
  ])
  patternString(body.request_id, requestIdPattern, 'request_id')
  patternString(body.memory_job_id, memoryJobIdPattern, 'memory_job_id')
  patternString(body.feedback_id, feedbackIdPattern, 'feedback_id')
  constant(body.job_type, 'extract_feedback', 'job_type')
  enumValue(
    body.status,
    ['pending', 'running', 'completed', 'failed'] as const,
    'status',
  )
  enumValue(
    body.stage,
    [
      'queued',
      'diffing',
      'classifying_durability',
      'extracting',
      'validating',
      'admitting',
      'done',
      'failed',
    ] as const,
    'stage',
  )
  nonNegativeInteger(body.attempt, 'attempt')
  const candidateIds = arrayValue(body.candidate_ids, 'candidate_ids')
  if (candidateIds.length > 3) throw new ContractError('candidate_ids exceeds 3')
  candidateIds.forEach((id) => patternString(id, memoryIdPattern, 'candidate_id'))
  if (body.disposition !== null) {
    enumValue(
      body.disposition,
      [
        'candidate_created',
        'episode_only',
        'reinforce_usage_only',
        'no_memory',
        'failed',
      ] as const,
      'disposition',
    )
  }
  if (body.error_code !== null) {
    enumValue(
      body.error_code,
      [
        'MEMORY_JOB_INTERRUPTED',
        'MEMORY_JSON_INVALID',
        'MEMORY_SCHEMA_INVALID',
        'MEMORY_REPAIR_FAILED',
        'MEMORY_PROVIDER_ERROR',
        'MEMORY_PROVIDER_TIMEOUT',
        'MEMORY_EVIDENCE_NOT_FOUND',
        'MEMORY_NO_REUSABLE_CONTENT',
        'MEMORY_SCOPE_TOO_BROAD',
      ] as const,
      'error_code',
    )
  }
  booleanValue(body.retryable, 'retryable')
  timestamp(body.created_at, 'created_at')
  timestamp(body.updated_at, 'updated_at')
  return body as unknown as MemoryJobResponse
}

export function parseResolveRequest(value: unknown): ResolveRequest {
  const body = record(value, 'ResolveRequest')
  const actual = Object.keys(body)
  if (
    !actual.includes('action') ||
    actual.some((key) => key !== 'action' && key !== 'patch')
  ) {
    throw new ContractError('ResolveRequest has invalid keys')
  }
  const action = enumValue(
    body.action,
    ['accept', 'edit_accept', 'reject', 'one_shot'] as const,
    'action',
  )
  const patch = actual.includes('patch') ? body.patch : null
  if (action === 'edit_accept') {
    if (patch === null || patch === undefined) {
      throw new ContractError('edit_accept requires patch')
    }
    validateMemoryCardPatch(patch)
  } else if (patch !== null && patch !== undefined) {
    throw new ContractError('only edit_accept may carry patch')
  }
  return {
    action,
    patch: patch === undefined ? null : (patch as ResolveRequest['patch']),
  }
}

export function parseResolveResponse(value: unknown): ResolveResponse {
  const body = record(value, 'ResolveResponse')
  exactKeys(body, [
    'request_id',
    'memory_id',
    'action',
    'old_status',
    'new_status',
    'disposition',
    'memory_version_id',
    'card',
  ])
  patternString(body.request_id, requestIdPattern, 'request_id')
  patternString(body.memory_id, memoryIdPattern, 'memory_id')
  enumValue(
    body.action,
    ['accept', 'edit_accept', 'reject', 'one_shot'] as const,
    'action',
  )
  validateMemoryCardStatus(body.old_status, 'old_status')
  validateMemoryCardStatus(body.new_status, 'new_status')
  validateDisposition(body.disposition, 'disposition')
  nullablePattern(
    body.memory_version_id,
    memoryVersionIdPattern,
    'memory_version_id',
  )
  validateMemoryCard(body.card)
  const card = body.card as Record<string, unknown>
  if (card.memory_id !== body.memory_id || card.status !== body.new_status) {
    throw new ContractError('ResolveResponse card does not match resolution')
  }
  return body as unknown as ResolveResponse
}

export function parseMemoryListResponse(value: unknown): MemoryListResponse {
  const body = record(value, 'MemoryListResponse')
  exactKeys(body, ['request_id', 'items', 'next_cursor'])
  patternString(body.request_id, requestIdPattern, 'request_id')
  const items = arrayValue(body.items, 'items')
  if (items.length > 100) throw new ContractError('items exceeds 100')
  items.forEach(validateMemoryCard)
  if (body.next_cursor !== null) {
    patternString(body.next_cursor, memoryIdPattern, 'next_cursor')
  }
  return body as unknown as MemoryListResponse
}

export function parseMemoryDetailResponse(
  value: unknown,
): MemoryDetailResponse {
  const body = record(value, 'MemoryDetailResponse')
  exactKeys(body, ['request_id', 'card', 'evidence', 'versions'])
  patternString(body.request_id, requestIdPattern, 'request_id')
  validateMemoryCard(body.card)
  arrayValue(body.evidence, 'evidence').forEach(validateMemoryEvidence)
  arrayValue(body.versions, 'versions').forEach(validateMemoryVersion)
  return body as unknown as MemoryDetailResponse
}

export function parseRetrievalTrace(value: unknown): RetrievalTrace {
  validateRetrievalTrace(value)
  if (value === null) throw new ContractError('retrieval trace cannot be null')
  return value as RetrievalTrace
}

export function parseMemoryUsage(value: unknown): MemoryUsage {
  validateMemoryUsage(value)
  return value as MemoryUsage
}

export function parseMemoryUsageList(value: unknown): MemoryUsageListResponse {
  const body = record(value, 'MemoryUsageListResponse')
  exactKeys(body, ['request_id', 'items', 'next_cursor'])
  patternString(body.request_id, requestIdPattern, 'request_id')
  arrayValue(body.items, 'items').forEach(validateMemoryUsage)
  if (body.next_cursor !== null) stringValue(body.next_cursor, 'next_cursor')
  return body as unknown as MemoryUsageListResponse
}

function validateMemoryCard(value: unknown): void {
  const body = record(value, 'MemoryCard')
  exactKeys(body, [
    'memory_id',
    'schema_version',
    'kind',
    'title',
    'rule',
    'avoid',
    'trigger_text',
    'scope',
    'exceptions',
    'status',
    'rejection_reason',
    'source_type',
    'save_preselected',
    'source_trust',
    'rule_confidence',
    'scope_confidence',
    'evidence_count',
    'version',
    'current_version_id',
    'valid_from',
    'valid_to',
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
  patternString(body.memory_id, memoryIdPattern, 'memory_id')
  constant(body.schema_version, '1.0', 'schema_version')
  enumValue(
    body.kind,
    [
      'preference',
      'constraint',
      'procedure',
      'experience',
      'environment',
      'learning_checkpoint',
    ] as const,
    'kind',
  )
  validateSizedString(body.title, 4, 40, 'title')
  validateSizedString(body.rule, 20, 300, 'rule')
  boundedString(body.avoid, 400, 'avoid')
  boundedString(body.trigger_text, 240, 'trigger_text')
  validateMemoryScope(body.scope)
  validateExceptions(body.exceptions)
  const status = validateMemoryCardStatus(body.status, 'status')
  const rejectionReason =
    body.rejection_reason === null
      ? null
      : enumValue(
          body.rejection_reason,
          ['user_rejected', 'episode_only'] as const,
          'rejection_reason',
        )
  enumValue(
    body.source_type,
    [
      'explicit_feedback',
      'explicit_correction',
      'edit_diff',
      'accept',
      'reject',
      'rating',
      'outcome',
      'import',
    ] as const,
    'source_type',
  )
  booleanValue(body.save_preselected, 'save_preselected')
  validateUnitInterval(body.source_trust, 'source_trust', false)
  validateUnitInterval(body.rule_confidence, 'rule_confidence', true)
  validateUnitInterval(body.scope_confidence, 'scope_confidence', true)
  nonNegativeInteger(body.evidence_count, 'evidence_count')
  const version = nonNegativeInteger(body.version, 'version')
  nullablePattern(
    body.current_version_id,
    memoryVersionIdPattern,
    'current_version_id',
  )
  nullableTimestamp(body.valid_from, 'valid_from')
  nullableTimestamp(body.valid_to, 'valid_to')
  nonNegativeInteger(body.retrieved_count, 'retrieved_count')
  nonNegativeInteger(body.injected_count, 'injected_count')
  nonNegativeInteger(body.verified_applied_count, 'verified_applied_count')
  nonNegativeInteger(body.helpful_count, 'helpful_count')
  nonNegativeInteger(body.harmful_count, 'harmful_count')
  nonNegativeInteger(body.stale_count, 'stale_count')
  nullableTimestamp(body.last_used_at, 'last_used_at')
  timestamp(body.created_at, 'created_at')
  timestamp(body.updated_at, 'updated_at')
  if (
    status === 'candidate' &&
    (rejectionReason !== null || version !== 0 || body.current_version_id !== null ||
      body.rule_confidence !== null || body.scope_confidence !== null)
  ) {
    throw new ContractError('candidate card violates admission invariants')
  }
  if (
    (status === 'active' || status === 'paused') &&
    (rejectionReason !== null || version < 1 || body.current_version_id === null ||
      body.rule_confidence === null || body.scope_confidence === null)
  ) {
    throw new ContractError('active card violates admission invariants')
  }
  if (status === 'rejected' && rejectionReason === null) {
    throw new ContractError('rejected card requires rejection_reason')
  }
}

function validateMemoryCardPatch(value: unknown): void {
  const body = record(value, 'MemoryCardPatch')
  const allowed = ['title', 'rule', 'avoid', 'scope', 'exceptions']
  const keys = Object.keys(body)
  if (keys.length === 0 || keys.some((key) => !allowed.includes(key))) {
    throw new ContractError('MemoryCardPatch has invalid keys')
  }
  if (keys.every((key) => body[key] === null)) {
    throw new ContractError('MemoryCardPatch must modify a field')
  }
  if (body.title !== undefined && body.title !== null) {
    validateSizedString(body.title, 4, 40, 'patch.title')
  }
  if (body.rule !== undefined && body.rule !== null) {
    validateSizedString(body.rule, 20, 300, 'patch.rule')
  }
  if (body.avoid !== undefined && body.avoid !== null) {
    boundedString(body.avoid, 400, 'patch.avoid')
  }
  if (body.scope !== undefined && body.scope !== null) {
    validateMemoryScope(body.scope)
  }
  if (body.exceptions !== undefined && body.exceptions !== null) {
    validateExceptions(body.exceptions)
  }
}

function validateMemoryScope(value: unknown): void {
  const body = record(value, 'MemoryScope')
  exactKeys(body, [
    'level',
    'domain',
    'task_type',
    'artifact_type',
    'audience',
    'project_key',
    'language',
    'framework',
    'concepts',
  ])
  enumValue(
    body.level,
    ['session', 'task_family', 'project', 'global'] as const,
    'scope.level',
  )
  enumValue(
    body.domain,
    [
      'programming_learning',
      'software_development',
      'general_text',
      'other',
      'any',
    ] as const,
    'scope.domain',
  )
  if (body.task_type !== null) {
    enumValue(
      body.task_type,
      [
        'debugging_guidance',
        'code_review',
        'code_explanation',
        'code_generation',
        'environment_configuration',
        'general_question',
        'other',
        'any',
      ] as const,
      'scope.task_type',
    )
  }
  if (body.artifact_type !== null) {
    enumValue(
      body.artifact_type,
      ['source_code', 'configuration', 'text', 'none', 'other', 'any'] as const,
      'scope.artifact_type',
    )
  }
  if (body.audience !== null) {
    enumValue(
      body.audience,
      ['beginner', 'intermediate', 'advanced', 'unknown', 'any'] as const,
      'scope.audience',
    )
  }
  nullableBoundedString(body.project_key, 128, 'scope.project_key')
  if (body.language !== null) {
    enumValue(
      body.language,
      [
        'python', 'javascript', 'typescript', 'java', 'c', 'cpp', 'rust', 'go',
        'other', 'unknown', 'any',
      ] as const,
      'scope.language',
    )
  }
  nullableBoundedString(body.framework, 64, 'scope.framework')
  const concepts = arrayValue(body.concepts, 'scope.concepts')
  if (concepts.length > 12) throw new ContractError('scope.concepts exceeds 12')
  concepts.forEach((item) => nonEmptyBoundedString(item, 64, 'scope.concept'))
}

function validateExceptions(value: unknown): void {
  const entries = arrayValue(value, 'exceptions')
  if (entries.length > 8) throw new ContractError('exceptions exceeds 8')
  entries.forEach((entry) =>
    enumValue(
      entry,
      ['response_policy:direct_fix', 'urgency:urgent'] as const,
      'exception',
    ),
  )
  if (new Set(entries).size !== entries.length) {
    throw new ContractError('exceptions contains duplicates')
  }
}

function validateMemoryEvidence(value: unknown): void {
  const body = record(value, 'MemoryEvidenceProjection')
  exactKeys(body, [
    'evidence_id',
    'source_type',
    'feedback_id',
    'task_id',
    'run_id',
    'evidence_quote',
    'diff_summary',
    'normalized_edit_cost',
    'created_at',
  ])
  patternString(body.evidence_id, evidenceIdPattern, 'evidence_id')
  enumValue(
    body.source_type,
    [
      'explicit_feedback',
      'explicit_correction',
      'edit_diff',
      'accept',
      'reject',
      'rating',
      'outcome',
      'import',
    ] as const,
    'source_type',
  )
  nullablePattern(body.feedback_id, feedbackIdPattern, 'feedback_id')
  nullablePattern(body.task_id, taskIdPattern, 'task_id')
  nullablePattern(body.run_id, runIdPattern, 'run_id')
  nonEmptyBoundedString(body.evidence_quote, 2_000, 'evidence_quote')
  nullableBoundedString(body.diff_summary, 2_000, 'diff_summary')
  validateUnitInterval(
    body.normalized_edit_cost,
    'normalized_edit_cost',
    true,
  )
  timestamp(body.created_at, 'created_at')
}

function validateMemoryVersion(value: unknown): void {
  const body = record(value, 'MemoryVersionProjection')
  exactKeys(body, [
    'memory_version_id',
    'version',
    'title',
    'rule',
    'avoid',
    'trigger_text',
    'scope',
    'exceptions',
    'created_by_action',
    'created_at',
  ])
  patternString(body.memory_version_id, memoryVersionIdPattern, 'memory_version_id')
  positiveInteger(body.version, 'version')
  validateSizedString(body.title, 4, 40, 'title')
  validateSizedString(body.rule, 20, 300, 'rule')
  boundedString(body.avoid, 400, 'avoid')
  boundedString(body.trigger_text, 240, 'trigger_text')
  validateMemoryScope(body.scope)
  validateExceptions(body.exceptions)
  enumValue(
    body.created_by_action,
    ['accept', 'edit_accept', 'edit'] as const,
    'created_by_action',
  )
  timestamp(body.created_at, 'created_at')
}

function validateMemoryCardStatus(value: unknown, label: string) {
  return enumValue(
    value,
    [
      'candidate',
      'active',
      'rejected',
      'conflicted',
      'paused',
      'superseded',
      'merged',
      'archived',
      'deleted',
    ] as const,
    label,
  )
}

function validateDisposition(value: unknown, label: string) {
  return enumValue(
    value,
    [
      'candidate_created',
      'episode_only',
      'reinforce_usage_only',
      'no_memory',
      'failed',
    ] as const,
    label,
  )
}

function validateSizedString(
  value: unknown,
  min: number,
  max: number,
  label: string,
): void {
  const result = boundedString(value, max, label)
  if ([...result].length < min) {
    throw new ContractError(`${label} is too short`)
  }
}

function validateUnitInterval(
  value: unknown,
  label: string,
  nullable: boolean,
): void {
  if (nullable && value === null) return
  const result = nonNegativeNumber(value, label)
  if (result > 1) throw new ContractError(`${label} exceeds 1`)
}

export function parseTaskSnapshot(value: unknown): TaskSnapshot {
  const body = record(value, 'TaskSnapshot')
  exactKeys(body, [
    'request_id',
    'task_id',
    'run_id',
    'task_text',
    'scenario',
    'task_status',
    'run_status',
    'provider_mode',
    'effective_memory_mode',
    'fingerprint',
    'public_plan',
    'tool_decision',
    'tool_calls',
    'partial_output',
    'end_offset',
    'offset_unit',
    'messages',
    'final_message',
    'feedback_events',
    'retrieval_trace',
    'memory_usages',
    'error',
    'terminal',
    'last_persistent_event_seq',
    'updated_at',
  ])
  patternString(body.request_id, requestIdPattern, 'request_id')
  patternString(body.task_id, taskIdPattern, 'task_id')
  patternString(body.run_id, runIdPattern, 'run_id')
  nonEmptyBoundedString(body.task_text, 20000, 'task_text')
  enumValue(
    body.scenario,
    [
      'programming_learning',
      'software_development',
      'general_text',
      'other',
    ] as const,
    'scenario',
  )
  constant(body.task_status, 'active', 'task_status')
  const runStatus = enumValue(
    body.run_status,
    [
      'queued',
      'fingerprinting',
      'retrieving',
      'planning',
      'tool_running',
      'generating',
      'succeeded',
      'failed',
    ] as const,
    'run_status',
  )
  enumValue(body.provider_mode, ['mock', 'real'] as const, 'provider_mode')
  enumValue(
    body.effective_memory_mode,
    ['on', 'off'] as const,
    'effective_memory_mode',
  )
  validateFingerprint(body.fingerprint)
  validatePublicPlan(body.public_plan)
  validateToolDecision(body.tool_decision)
  const toolCalls = arrayValue(body.tool_calls, 'tool_calls')
  if (toolCalls.length > 1) {
    throw new ContractError('tool_calls exceeds G0 cardinality')
  }
  toolCalls.forEach(validateToolCall)
  const partialOutput = boundedString(body.partial_output, 262144, 'partial_output')
  const endOffset = boundedInteger(body.end_offset, 0, 262144, 'end_offset')
  constant(body.offset_unit, 'utf8_bytes', 'offset_unit')
  if (utf8ByteLength(partialOutput) !== endOffset) {
    throw new ContractError('partial_output does not match UTF-8 end_offset')
  }
  const messages = arrayValue(body.messages, 'messages')
  messages.forEach(validateTaskMessageRecord)
  validateMessage(body.final_message)
  const feedbackEvents = arrayValue(body.feedback_events, 'feedback_events')
  feedbackEvents.forEach(validateFeedbackEventRecord)
  validateRetrievalTrace(body.retrieval_trace)
  arrayValue(body.memory_usages, 'memory_usages').forEach(validateMemoryUsage)
  validateRunError(body.error)
  const terminal = booleanValue(body.terminal, 'terminal')
  nonNegativeInteger(
    body.last_persistent_event_seq,
    'last_persistent_event_seq',
  )
  timestamp(body.updated_at, 'updated_at')

  if (runStatus === 'succeeded') {
    if (!terminal || body.final_message === null || body.error !== null) {
      throw new ContractError('Succeeded snapshot violates terminal invariants')
    }
    const finalMessage = record(body.final_message, 'final_message')
    if (finalMessage.content !== partialOutput) {
      throw new ContractError('final_message differs from partial_output')
    }
  } else if (runStatus === 'failed') {
    if (!terminal || body.error === null || body.final_message !== null) {
      throw new ContractError('Failed snapshot violates terminal invariants')
    }
  } else if (terminal || body.final_message !== null || body.error !== null) {
    throw new ContractError('Non-terminal snapshot contains terminal fields')
  }
  return body as unknown as TaskSnapshot
}

export function parseErrorResponse(value: unknown): ErrorResponse | null {
  try {
    const body = record(value, 'ErrorResponse')
    exactKeys(body, ['error'])
    const error = record(body.error, 'error')
    exactKeys(error, ['code', 'message', 'request_id', 'retryable', 'details'])
    enumValue(
      error.code,
      [
        'VALIDATION_ERROR',
        'TASK_NOT_FOUND',
        'PROVIDER_CONFIG_MISSING',
        'PROVIDER_TIMEOUT',
        'PROVIDER_ERROR',
        'TOOL_NOT_FOUND',
        'TOOL_INPUT_INVALID',
        'STREAM_INTERRUPTED',
        'INTERNAL_ERROR',
        'SESSION_REQUIRED',
        'IDEMPOTENCY_CONFLICT',
        'FEEDBACK_NO_CHANGES',
        'TASK_NOT_READY_FOR_FEEDBACK',
        'MEMORY_NOT_FOUND',
        'MEMORY_ALREADY_RESOLVED',
        'MEMORY_JOB_NOT_RETRYABLE',
      ] satisfies readonly ErrorCode[],
      'error.code',
    )
    nonEmptyBoundedString(error.message, 240, 'error.message')
    patternString(error.request_id, requestIdPattern, 'error.request_id')
    booleanValue(error.retryable, 'error.retryable')
    validateErrorDetails(error.details)
    return body as unknown as ErrorResponse
  } catch {
    return null
  }
}

function validateEventPayload(
  eventType: G0EventType,
  value: unknown,
  envelopeRunId: string,
): void {
  const data = record(value, `${eventType}.data`)
  switch (eventType) {
    case 'task.created':
      exactKeys(data, ['task_status', 'run_status'])
      constant(data.task_status, 'active', 'task_status')
      constant(data.run_status, 'queued', 'run_status')
      return
    case 'task.stage':
      exactKeys(data, ['stage', 'progress_label'])
      enumValue(
        data.stage,
        [
          'fingerprinting',
          'retrieving',
          'planning',
          'tool_running',
          'generating',
          'failed',
        ] as const,
        'stage',
      )
      enumValue(
        data.progress_label,
        [
          'fingerprinting_task',
          'retrieving_memory',
          'publishing_plan',
          'running_static_tool',
          'generating_answer',
          'run_failed',
        ] as const,
        'progress_label',
      )
      return
    case 'task.fingerprinted':
      exactKeys(data, [
        'fingerprint_id',
        'domain',
        'classification_source',
        'classification_confidence',
        'classification_reasons',
        'task_type',
        'artifact_type',
        'language',
      ])
      patternString(data.fingerprint_id, fingerprintIdPattern, 'fingerprint_id')
      enumValue(
        data.domain,
        [
          'programming_learning',
          'software_development',
          'general_text',
          'other',
        ] as const,
        'domain',
      )
      constant(data.classification_source, 'auto_rule_v1', 'classification_source')
      validateClassificationConfidence(
        data.classification_confidence,
        'classification_confidence',
      )
      validateClassificationReasons(
        data.classification_reasons,
        'classification_reasons',
      )
      enumValue(
        data.task_type,
        [
          'debugging_guidance',
          'code_review',
          'code_explanation',
          'code_generation',
          'environment_configuration',
          'general_question',
          'other',
        ] as const,
        'task_type',
      )
      enumValue(
        data.artifact_type,
        ['source_code', 'configuration', 'text', 'none', 'other'] as const,
        'artifact_type',
      )
      validateLanguage(data.language)
      return
    case 'memory.retrieval.started':
      exactKeys(data, ['retrieval_mode'])
      constant(data.retrieval_mode, 'tfidf', 'retrieval_mode')
      return
    case 'memory.retrieval.completed':
      exactKeys(data, [
        'trace_id', 'mode', 'algorithm_version', 'candidate_count',
        'retrieved_count', 'selected_count', 'injected_count', 'threshold',
        'top_k', 'retrieval_ms', 'memory_chars', 'estimated_tokens',
        'prompt_section_hash',
      ])
      patternString(data.trace_id, retrievalTraceIdPattern, 'trace_id')
      enumValue(data.mode, ['tfidf', 'tfidf_degraded'] as const, 'mode')
      constant(data.algorithm_version, 'char_tfidf_v1', 'algorithm_version')
      for (const key of ['candidate_count', 'retrieved_count', 'selected_count', 'injected_count', 'retrieval_ms', 'memory_chars', 'estimated_tokens']) {
        nonNegativeInteger(data[key], key)
      }
      validateUnitInterval(data.threshold, 'threshold', false)
      positiveInteger(data.top_k, 'top_k')
      if (data.prompt_section_hash !== null) {
        patternString(data.prompt_section_hash, /^[a-f0-9]{64}$/, 'prompt_section_hash')
      }
      return
    case 'memory.injected':
      exactKeys(data, ['usage_id', 'trace_id', 'memory_id', 'memory_version_id', 'rank', 'estimated_tokens', 'prompt_section_hash'])
      patternString(data.usage_id, usageIdPattern, 'usage_id')
      patternString(data.trace_id, retrievalTraceIdPattern, 'trace_id')
      patternString(data.memory_id, memoryIdPattern, 'memory_id')
      patternString(data.memory_version_id, memoryVersionIdPattern, 'memory_version_id')
      positiveInteger(data.rank, 'rank')
      nonNegativeInteger(data.estimated_tokens, 'estimated_tokens')
      if (data.prompt_section_hash !== null) {
        patternString(data.prompt_section_hash, /^[a-f0-9]{64}$/, 'prompt_section_hash')
      }
      return
    case 'memory.usage.verified':
      exactKeys(data, ['usage_id', 'memory_id', 'memory_version_id', 'verification_status', 'verification_method', 'evidence_present'])
      patternString(data.usage_id, usageIdPattern, 'usage_id')
      patternString(data.memory_id, memoryIdPattern, 'memory_id')
      patternString(data.memory_version_id, memoryVersionIdPattern, 'memory_version_id')
      enumValue(data.verification_status, ['pending', 'applied', 'violated', 'not_observable', 'unknown'] as const, 'verification_status')
      if (data.verification_method !== null) {
        enumValue(data.verification_method, ['exact_substring', 'structured_provider'] as const, 'verification_method')
      }
      booleanValue(data.evidence_present, 'evidence_present')
      return
    case 'memory.usage.feedback.recorded':
      exactKeys(data, ['usage_id', 'memory_id', 'user_effect'])
      patternString(data.usage_id, usageIdPattern, 'usage_id')
      patternString(data.memory_id, memoryIdPattern, 'memory_id')
      enumValue(data.user_effect, ['helpful', 'harmful', 'stale'] as const, 'user_effect')
      return
    case 'agent.plan.published':
      exactKeys(data, [
        'plan_id',
        'goal_code',
        'memory_summary_code',
        'next_action_code',
      ])
      patternString(data.plan_id, planIdPattern, 'plan_id')
      enumValue(
        data.goal_code,
        ['analyze_code', 'answer_question', 'explain_concept', 'other'] as const,
        'goal_code',
      )
      enumValue(
        data.memory_summary_code,
        ['no_memory_selected', 'memory_selected'] as const,
        'memory_summary_code',
      )
      enumValue(
        data.next_action_code,
        ['python_ast_check', 'generate_directly'] as const,
        'next_action_code',
      )
      return
    case 'tool.called':
      exactKeys(data, [
        'tool_call_id',
        'tool_name',
        'reason_code',
        'args_summary',
      ])
      patternString(data.tool_call_id, toolCallIdPattern, 'tool_call_id')
      constant(data.tool_name, 'python_ast_check', 'tool_name')
      constant(data.reason_code, 'python_code_detected', 'reason_code')
      validateArgsSummary(data.args_summary)
      return
    case 'tool.result':
      exactKeys(data, [
        'tool_call_id',
        'tool_name',
        'status',
        'latency_ms',
        'result_ref',
      ])
      patternString(data.tool_call_id, toolCallIdPattern, 'tool_call_id')
      constant(data.tool_name, 'python_ast_check', 'tool_name')
      enumValue(data.status, ['succeeded', 'failed'] as const, 'status')
      nonNegativeNumber(data.latency_ms, 'latency_ms')
      nullablePattern(data.result_ref, toolResultIdPattern, 'result_ref')
      return
    case 'agent.chunk': {
      exactKeys(data, [
        'run_id',
        'chunk_seq',
        'start_offset',
        'end_offset',
        'offset_unit',
        'delta',
      ])
      const dataRunId = patternString(data.run_id, runIdPattern, 'data.run_id')
      if (dataRunId !== envelopeRunId) {
        throw new ContractError('Chunk data.run_id differs from envelope run_id')
      }
      positiveInteger(data.chunk_seq, 'chunk_seq')
      const start = boundedInteger(data.start_offset, 0, 262144, 'start_offset')
      const end = boundedInteger(data.end_offset, 1, 262144, 'end_offset')
      constant(data.offset_unit, 'utf8_bytes', 'offset_unit')
      const delta = boundedString(data.delta, 32768, 'delta')
      if (delta.length === 0 || end !== start + utf8ByteLength(delta)) {
        throw new ContractError('Chunk offsets do not match UTF-8 delta bytes')
      }
      return
    }
    case 'run.metrics': {
      exactKeys(data, [
        'provider',
        'model',
        'provider_mode',
        'first_token_ms',
        'total_ms',
        'prompt_tokens',
        'output_tokens',
        'token_source',
      ])
      nonEmptyBoundedString(data.provider, 64, 'provider')
      nonEmptyBoundedString(data.model, 128, 'model')
      enumValue(data.provider_mode, ['mock', 'real'] as const, 'provider_mode')
      nullableNonNegativeNumber(data.first_token_ms, 'first_token_ms')
      nullableNonNegativeNumber(data.total_ms, 'total_ms')
      const source = enumValue(
        data.token_source,
        ['actual', 'unavailable', 'mock'] as const,
        'token_source',
      )
      if (source === 'unavailable') {
        if (data.prompt_tokens !== null || data.output_tokens !== null) {
          throw new ContractError('Unavailable token source must use null counts')
        }
      } else {
        nonNegativeInteger(data.prompt_tokens, 'prompt_tokens')
        nonNegativeInteger(data.output_tokens, 'output_tokens')
      }
      return
    }
    case 'run.completed':
      exactKeys(data, ['status', 'message_id', 'end_offset', 'offset_unit'])
      constant(data.status, 'succeeded', 'status')
      patternString(data.message_id, messageIdPattern, 'message_id')
      boundedInteger(data.end_offset, 0, 262144, 'end_offset')
      constant(data.offset_unit, 'utf8_bytes', 'offset_unit')
      return
    case 'run.failed':
      exactKeys(data, [
        'status',
        'error_code',
        'retryable',
        'partial_message_id',
        'end_offset',
        'offset_unit',
      ])
      constant(data.status, 'failed', 'status')
      validateAsyncError(data.error_code)
      booleanValue(data.retryable, 'retryable')
      nullablePattern(data.partial_message_id, messageIdPattern, 'partial_message_id')
      boundedInteger(data.end_offset, 0, 262144, 'end_offset')
      constant(data.offset_unit, 'utf8_bytes', 'offset_unit')
      return
    case 'error':
      exactKeys(data, ['error_id', 'code', 'message', 'retryable'])
      patternString(data.error_id, errorIdPattern, 'error_id')
      validateAsyncError(data.code)
      nonEmptyBoundedString(data.message, 240, 'message')
      booleanValue(data.retryable, 'retryable')
      return
    case 'stream.done':
      exactKeys(data, ['status', 'final_snapshot_required'])
      enumValue(data.status, ['succeeded', 'failed'] as const, 'status')
      constant(data.final_snapshot_required, true, 'final_snapshot_required')
      return
    case 'feedback.recorded':
      exactKeys(data, ['feedback_id', 'memory_job_id', 'feedback_type'])
      patternString(data.feedback_id, feedbackIdPattern, 'feedback_id')
      patternString(data.memory_job_id, memoryJobIdPattern, 'memory_job_id')
      enumValue(
        data.feedback_type,
        [
          'explicit_text',
          'edited_output',
          'rating',
          'accepted',
          'rejected',
          'composite',
        ] as const,
        'feedback_type',
      )
      return
    case 'memory.extraction.stage':
      exactKeys(data, ['memory_job_id', 'stage'])
      patternString(data.memory_job_id, memoryJobIdPattern, 'memory_job_id')
      enumValue(
        data.stage,
        [
          'queued',
          'diffing',
          'classifying_durability',
          'extracting',
          'validating',
          'admitting',
          'done',
          'failed',
        ] as const,
        'stage',
      )
      return
    case 'memory.candidate.created':
      exactKeys(data, ['memory_job_id', 'memory_id', 'evidence_id', 'ordinal'])
      patternString(data.memory_job_id, memoryJobIdPattern, 'memory_job_id')
      patternString(data.memory_id, memoryIdPattern, 'memory_id')
      patternString(data.evidence_id, evidenceIdPattern, 'evidence_id')
      boundedInteger(data.ordinal, 0, 2, 'ordinal')
      return
    case 'memory.admission.resolved':
      exactKeys(data, [
        'memory_id',
        'old_status',
        'new_status',
        'memory_version_id',
        'disposition',
      ])
      patternString(data.memory_id, memoryIdPattern, 'memory_id')
      enumValue(
        data.old_status,
        [
          'candidate',
          'active',
          'rejected',
          'conflicted',
          'paused',
          'superseded',
          'merged',
          'archived',
          'deleted',
        ] as const,
        'old_status',
      )
      enumValue(
        data.new_status,
        [
          'candidate',
          'active',
          'rejected',
          'conflicted',
          'paused',
          'superseded',
          'merged',
          'archived',
          'deleted',
        ] as const,
        'new_status',
      )
      nullablePattern(data.memory_version_id, memoryVersionIdPattern, 'memory_version_id')
      enumValue(
        data.disposition,
        [
          'candidate_created',
          'episode_only',
          'reinforce_usage_only',
          'no_memory',
          'failed',
        ] as const,
        'disposition',
      )
      return
    case 'memory.job.failed':
      exactKeys(data, ['memory_job_id', 'stage', 'error_code', 'retryable'])
      patternString(data.memory_job_id, memoryJobIdPattern, 'memory_job_id')
      enumValue(
        data.stage,
        [
          'queued',
          'diffing',
          'classifying_durability',
          'extracting',
          'validating',
          'admitting',
          'done',
          'failed',
        ] as const,
        'stage',
      )
      enumValue(
        data.error_code,
        [
          'MEMORY_JOB_INTERRUPTED',
          'MEMORY_JSON_INVALID',
          'MEMORY_SCHEMA_INVALID',
          'MEMORY_REPAIR_FAILED',
          'MEMORY_PROVIDER_ERROR',
          'MEMORY_PROVIDER_TIMEOUT',
          'MEMORY_EVIDENCE_NOT_FOUND',
          'MEMORY_NO_REUSABLE_CONTENT',
          'MEMORY_SCOPE_TOO_BROAD',
        ] as const,
        'error_code',
      )
      booleanValue(data.retryable, 'retryable')
      return
  }
}

function validateFingerprint(value: unknown): void {
  if (value === null) return
  const data = record(value, 'fingerprint')
  exactKeys(data, [
    'id',
    'schema_version',
    'domain',
    'classification_source',
    'classification_confidence',
    'classification_reasons',
    'task_type',
    'artifact_type',
    'audience',
    'project_key',
    'language',
    'framework',
    'concepts',
    'tool_context',
    'current_constraints',
    'semantic_query',
  ])
  patternString(data.id, fingerprintIdPattern, 'fingerprint.id')
  constant(data.schema_version, '1.1', 'fingerprint.schema_version')
  enumValue(
    data.domain,
    ['programming_learning', 'software_development', 'general_text', 'other'] as const,
    'fingerprint.domain',
  )
  constant(
    data.classification_source,
    'auto_rule_v1',
    'fingerprint.classification_source',
  )
  validateClassificationConfidence(
    data.classification_confidence,
    'fingerprint.classification_confidence',
  )
  validateClassificationReasons(
    data.classification_reasons,
    'fingerprint.classification_reasons',
  )
  enumValue(
    data.task_type,
    [
      'debugging_guidance',
      'code_review',
      'code_explanation',
      'code_generation',
      'environment_configuration',
      'general_question',
      'other',
    ] as const,
    'fingerprint.task_type',
  )
  enumValue(
    data.artifact_type,
    ['source_code', 'configuration', 'text', 'none', 'other'] as const,
    'fingerprint.artifact_type',
  )
  enumValue(
    data.audience,
    ['beginner', 'intermediate', 'advanced', 'unknown'] as const,
    'fingerprint.audience',
  )
  nullableBoundedString(data.project_key, 128, 'fingerprint.project_key')
  validateLanguage(data.language)
  nullableBoundedString(data.framework, 64, 'fingerprint.framework')
  const concepts = arrayValue(data.concepts, 'fingerprint.concepts')
  if (concepts.length > 12) throw new ContractError('Too many concepts')
  concepts.forEach((concept) =>
    patternString(concept, /^[a-z0-9][a-z0-9_-]{0,63}$/, 'concept'),
  )
  if (new Set(concepts).size !== concepts.length) {
    throw new ContractError('fingerprint.concepts contains duplicates')
  }
  const tools = arrayValue(data.tool_context, 'fingerprint.tool_context')
  if (tools.length > 1) throw new ContractError('Too many tool_context values')
  tools.forEach((tool) => constant(tool, 'python_ast_check', 'tool_context'))
  if (new Set(tools).size !== tools.length) {
    throw new ContractError('fingerprint.tool_context contains duplicates')
  }
  validateCurrentConstraints(data.current_constraints)
  const semanticQuery = boundedString(
    data.semantic_query,
    512,
    'fingerprint.semantic_query',
  )
  if (semanticQuery.length === 0) throw new ContractError('semantic_query is empty')
}

function validateClassificationConfidence(value: unknown, label: string): void {
  const confidence = nonNegativeNumber(value, label)
  if (confidence > 1) throw new ContractError(`${label} exceeds 1`)
}

function validateClassificationReasons(value: unknown, label: string): void {
  const reasons = arrayValue(value, label)
  if (reasons.length > 5) throw new ContractError(`${label} exceeds 5 entries`)
  reasons.forEach((reason) =>
    enumValue(
      reason,
      [
        'code_present',
        'technical_context',
        'debugging_cue',
        'learning_cue',
        'explanation_intent',
        'development_action',
        'deployment_cue',
        'text_task',
        'ambiguous',
      ] as const,
      label,
    ),
  )
  if (new Set(reasons).size !== reasons.length) {
    throw new ContractError(`${label} contains duplicates`)
  }
}

function validatePublicPlan(value: unknown): void {
  if (value === null) return
  const data = record(value, 'public_plan')
  exactKeys(data, ['id', 'goal', 'memory_summary', 'next_action'])
  patternString(data.id, planIdPattern, 'public_plan.id')
  nonEmptyBoundedString(data.goal, 240, 'public_plan.goal')
  nonEmptyBoundedString(data.memory_summary, 160, 'public_plan.memory_summary')
  nonEmptyBoundedString(data.next_action, 240, 'public_plan.next_action')
}

function validateToolDecision(value: unknown): void {
  if (value === null) return
  const data = record(value, 'tool_decision')
  exactKeys(data, ['action', 'tool_name', 'reason_code', 'reason'])
  const action = enumValue(data.action, ['call', 'skip'] as const, 'action')
  const reasonCode = enumValue(
    data.reason_code,
    [
      'python_code_detected',
      'non_python_task',
      'no_extractable_python',
      'unsupported_artifact',
    ] as const,
    'reason_code',
  )
  nonEmptyBoundedString(data.reason, 240, 'reason')
  if (action === 'call') {
    constant(data.tool_name, 'python_ast_check', 'tool_name')
    constant(reasonCode, 'python_code_detected', 'reason_code')
  } else {
    constant(data.tool_name, null, 'tool_name')
    if (reasonCode === 'python_code_detected') {
      throw new ContractError('Skip decision has call reason')
    }
  }
}

function validateToolCall(value: unknown): void {
  const data = record(value, 'tool_call')
  exactKeys(data, [
    'tool_call_id',
    'tool_name',
    'reason',
    'args_summary',
    'status',
    'latency_ms',
    'result_ref',
    'result',
  ])
  patternString(data.tool_call_id, toolCallIdPattern, 'tool_call_id')
  constant(data.tool_name, 'python_ast_check', 'tool_name')
  nonEmptyBoundedString(data.reason, 240, 'reason')
  validateArgsSummary(data.args_summary)
  enumValue(data.status, ['running', 'succeeded', 'failed'] as const, 'status')
  nullableNonNegativeNumber(data.latency_ms, 'latency_ms')
  nullablePattern(data.result_ref, toolResultIdPattern, 'result_ref')
  if (data.result !== null) validateAstResult(data.result)
}

function validateArgsSummary(value: unknown): void {
  const data = record(value, 'args_summary')
  exactKeys(data, ['language', 'code_source', 'code_bytes'])
  constant(data.language, 'python', 'language')
  enumValue(
    data.code_source,
    ['fenced_python', 'whole_task_valid_python'] as const,
    'code_source',
  )
  boundedInteger(data.code_bytes, 1, 102400, 'code_bytes')
}

function validateAstResult(value: unknown): void {
  const data = record(value, 'AST result')
  exactKeys(data, ['valid', 'syntax_error'])
  const valid = booleanValue(data.valid, 'valid')
  if (valid) {
    constant(data.syntax_error, null, 'syntax_error')
    return
  }
  const error = record(data.syntax_error, 'syntax_error')
  exactKeys(error, ['message', 'line', 'column', 'end_line', 'end_column'])
  nonEmptyBoundedString(error.message, 200, 'syntax_error.message')
  nullablePositiveInteger(error.line, 'syntax_error.line')
  nullablePositiveInteger(error.column, 'syntax_error.column')
  nullablePositiveInteger(error.end_line, 'syntax_error.end_line')
  nullablePositiveInteger(error.end_column, 'syntax_error.end_column')
}

function validateTaskMessageRecord(value: unknown): void {
  const data = record(value, 'message record')
  exactKeys(data, ['message_id', 'run_id', 'role', 'content', 'created_at'])
  patternString(data.message_id, messageIdPattern, 'message_id')
  if (data.run_id !== null) {
    patternString(data.run_id, runIdPattern, 'run_id')
  }
  enumValue(data.role, ['user', 'assistant'] as const, 'role')
  boundedString(data.content, 262144, 'content')
  timestamp(data.created_at, 'created_at')
}

function validateFeedbackEventRecord(value: unknown): void {
  const data = record(value, 'feedback event record')
  exactKeys(data, [
    'feedback_id',
    'run_id',
    'feedback_type',
    'explicit_text',
    'edited_output',
    'rating',
    'accepted',
    'memory_job_id',
    'created_at',
  ])
  patternString(data.feedback_id, feedbackIdPattern, 'feedback_id')
  patternString(data.run_id, runIdPattern, 'run_id')
  enumValue(
    data.feedback_type,
    [
      'explicit_text',
      'edited_output',
      'rating',
      'accepted',
      'rejected',
      'composite',
    ] as const,
    'feedback_type',
  )
  if (data.explicit_text !== null) {
    nonEmptyBoundedString(data.explicit_text, 4000, 'explicit_text')
  }
  if (data.edited_output !== null) {
    nonEmptyBoundedString(data.edited_output, 100000, 'edited_output')
  }
  if (data.rating !== null) {
    boundedInteger(data.rating, 1, 5, 'rating')
  }
  if (data.accepted !== null) {
    booleanValue(data.accepted, 'accepted')
  }
  patternString(data.memory_job_id, memoryJobIdPattern, 'memory_job_id')
  timestamp(data.created_at, 'created_at')
}

function validateMessage(value: unknown): void {
  if (value === null) return
  const data = record(value, 'final_message')
  exactKeys(data, ['id', 'role', 'content', 'created_at'])
  patternString(data.id, messageIdPattern, 'final_message.id')
  constant(data.role, 'assistant', 'final_message.role')
  boundedString(data.content, 262144, 'final_message.content')
  timestamp(data.created_at, 'final_message.created_at')
}

function validateRunError(value: unknown): void {
  if (value === null) return
  const data = record(value, 'run error')
  exactKeys(data, ['error_id', 'code', 'message', 'retryable'])
  patternString(data.error_id, errorIdPattern, 'error_id')
  validateAsyncError(data.code)
  nonEmptyBoundedString(data.message, 240, 'error.message')
  booleanValue(data.retryable, 'error.retryable')
}

function validateRetrievalReason(value: unknown, label: string): void {
  enumValue(
    value,
    [
      'selected_above_threshold', 'memory_mode_off', 'status_not_active',
      'not_yet_valid', 'expired', 'scope_domain_mismatch',
      'scope_task_type_mismatch', 'scope_artifact_mismatch',
      'scope_audience_mismatch', 'scope_project_mismatch',
      'scope_language_mismatch', 'scope_framework_mismatch',
      'current_constraint_override', 'active_conflict', 'invalid_active_card',
      'empty_vector', 'below_threshold', 'top_k_exceeded',
      'prompt_budget_exceeded',
    ] as const,
    label,
  )
}

function validateRetrievalTrace(value: unknown): void {
  if (value === null) return
  const body = record(value, 'retrieval_trace')
  exactKeys(body, [
    'request_id', 'retrieval_trace_id', 'task_id', 'run_id', 'retrieval_mode',
    'algorithm_version', 'threshold', 'top_k', 'candidate_count',
    'retrieved_count', 'selected_count', 'injected_count', 'decisions',
    'retrieval_ms', 'memory_chars', 'memory_tokens_estimated',
    'provider_prompt_tokens_actual', 'prompt_section_hash', 'reason_codes',
    'created_at', 'updated_at',
  ])
  patternString(body.request_id, requestIdPattern, 'trace.request_id')
  patternString(body.retrieval_trace_id, retrievalTraceIdPattern, 'retrieval_trace_id')
  patternString(body.task_id, taskIdPattern, 'trace.task_id')
  patternString(body.run_id, runIdPattern, 'trace.run_id')
  enumValue(body.retrieval_mode, ['tfidf', 'tfidf_degraded'] as const, 'retrieval_mode')
  constant(body.algorithm_version, 'char_tfidf_v1', 'algorithm_version')
  validateUnitInterval(body.threshold, 'threshold', false)
  positiveInteger(body.top_k, 'top_k')
  for (const key of ['candidate_count', 'retrieved_count', 'selected_count', 'injected_count', 'retrieval_ms', 'memory_chars', 'memory_tokens_estimated']) {
    nonNegativeInteger(body[key], key)
  }
  const decisions = arrayValue(body.decisions, 'decisions')
  decisions.forEach(validateRetrievalDecision)
  nullableNonNegativeNumber(body.provider_prompt_tokens_actual, 'provider_prompt_tokens_actual')
  if (body.prompt_section_hash !== null) {
    patternString(body.prompt_section_hash, /^[a-f0-9]{64}$/, 'prompt_section_hash')
  }
  arrayValue(body.reason_codes, 'reason_codes').forEach((reason) =>
    validateRetrievalReason(reason, 'reason_code'),
  )
  timestamp(body.created_at, 'trace.created_at')
  timestamp(body.updated_at, 'trace.updated_at')
}

function validateRetrievalDecision(value: unknown): void {
  const body = record(value, 'retrieval_decision')
  exactKeys(body, [
    'memory_id', 'memory_version_id', 'memory_status', 'retrieved', 'selected',
    'injected', 'rank', 'scope_match', 'semantic_similarity',
    'provenance_confidence', 'verified_effect', 'recency', 'final_score',
    'reason_codes',
  ])
  patternString(body.memory_id, memoryIdPattern, 'decision.memory_id')
  nullablePattern(body.memory_version_id, memoryVersionIdPattern, 'decision.memory_version_id')
  validateMemoryCardStatus(body.memory_status, 'decision.memory_status')
  booleanValue(body.retrieved, 'decision.retrieved')
  booleanValue(body.selected, 'decision.selected')
  booleanValue(body.injected, 'decision.injected')
  nullablePositiveInteger(body.rank, 'decision.rank')
  for (const key of ['scope_match', 'semantic_similarity', 'provenance_confidence', 'verified_effect', 'recency', 'final_score']) {
    validateUnitInterval(body[key], `decision.${key}`, true)
  }
  arrayValue(body.reason_codes, 'decision.reason_codes').forEach((reason) =>
    validateRetrievalReason(reason, 'decision.reason_code'),
  )
}

function validateMemoryUsage(value: unknown): void {
  const body = record(value, 'memory_usage')
  exactKeys(body, [
    'request_id', 'usage_id', 'retrieval_trace_id', 'task_id', 'run_id',
    'memory_id', 'memory_version_id', 'rank', 'retrieved', 'selected',
    'injected', 'estimated_tokens', 'verification_status',
    'verification_method', 'evidence_excerpt', 'user_effect', 'created_at',
    'updated_at',
  ])
  patternString(body.request_id, requestIdPattern, 'usage.request_id')
  patternString(body.usage_id, usageIdPattern, 'usage_id')
  patternString(body.retrieval_trace_id, retrievalTraceIdPattern, 'usage.retrieval_trace_id')
  patternString(body.task_id, taskIdPattern, 'usage.task_id')
  patternString(body.run_id, runIdPattern, 'usage.run_id')
  patternString(body.memory_id, memoryIdPattern, 'usage.memory_id')
  patternString(body.memory_version_id, memoryVersionIdPattern, 'usage.memory_version_id')
  positiveInteger(body.rank, 'usage.rank')
  booleanValue(body.retrieved, 'usage.retrieved')
  booleanValue(body.selected, 'usage.selected')
  booleanValue(body.injected, 'usage.injected')
  nonNegativeInteger(body.estimated_tokens, 'usage.estimated_tokens')
  enumValue(body.verification_status, ['pending', 'applied', 'violated', 'not_observable', 'unknown'] as const, 'verification_status')
  if (body.verification_method !== null) {
    enumValue(body.verification_method, ['exact_substring', 'structured_provider'] as const, 'verification_method')
  }
  nullableBoundedString(body.evidence_excerpt, 120, 'evidence_excerpt')
  if (body.user_effect !== null) {
    enumValue(body.user_effect, ['helpful', 'harmful', 'stale'] as const, 'user_effect')
  }
  timestamp(body.created_at, 'usage.created_at')
  timestamp(body.updated_at, 'usage.updated_at')
}

function validateCurrentConstraints(value: unknown): void {
  const data = record(value, 'current_constraints')
  exactKeys(data, ['response_policy', 'urgency', 'memory_disabled', 'source'])
  enumValue(
    data.response_policy,
    ['default', 'guided_hint', 'direct_fix'] as const,
    'response_policy',
  )
  enumValue(data.urgency, ['normal', 'urgent'] as const, 'urgency')
  booleanValue(data.memory_disabled, 'memory_disabled')
  constant(data.source, 'ui', 'source')
}

function validateErrorDetails(value: unknown): void {
  const details = record(value, 'error.details')
  const allowedKeys = [
    'field_errors',
    'task_id',
    'run_id',
    'provider_status',
    'check',
    'http_status',
  ]
  for (const key of Object.keys(details)) {
    if (!allowedKeys.includes(key)) {
      throw new ContractError(`error.details contains unsupported key ${key}`)
    }
  }
  if ('task_id' in details) nullablePattern(details.task_id, taskIdPattern, 'details.task_id')
  if ('run_id' in details) nullablePattern(details.run_id, runIdPattern, 'details.run_id')
  if ('provider_status' in details && details.provider_status !== null) {
    boundedInteger(details.provider_status, 400, 599, 'details.provider_status')
  }
  if ('http_status' in details) {
    boundedInteger(details.http_status, 400, 599, 'details.http_status')
  }
  if ('check' in details) {
    enumValue(
      details.check,
      ['provider_configuration', 'data_directory'] as const,
      'details.check',
    )
  }
  if ('field_errors' in details) {
    const fieldErrors = arrayValue(details.field_errors, 'details.field_errors')
    if (fieldErrors.length > 50) throw new ContractError('Too many field errors')
    fieldErrors.forEach((item) => {
      const fieldError = record(item, 'field error')
      exactKeys(fieldError, ['loc', 'message', 'type'])
      const location = arrayValue(fieldError.loc, 'field_error.loc')
      if (location.length === 0) throw new ContractError('field_error.loc is empty')
      location.forEach((part) => {
        if (typeof part !== 'string' && !Number.isInteger(part)) {
          throw new ContractError('field_error.loc contains an invalid value')
        }
      })
      nonEmptyBoundedString(fieldError.message, 240, 'field_error.message')
      nonEmptyBoundedString(fieldError.type, 120, 'field_error.type')
    })
  }
}

function validateLanguage(value: unknown): void {
  enumValue(
    value,
    [
      'python',
      'javascript',
      'typescript',
      'java',
      'c',
      'cpp',
      'rust',
      'go',
      'other',
      'unknown',
    ] as const,
    'language',
  )
}

function validateAsyncError(value: unknown): void {
  enumValue(
    value,
    [
      'PROVIDER_TIMEOUT',
      'PROVIDER_ERROR',
      'TOOL_NOT_FOUND',
      'TOOL_INPUT_INVALID',
      'STREAM_INTERRUPTED',
    ] as const,
    'async error code',
  )
}

function parseJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch {
    throw new ContractError(`${label} is not valid JSON`)
  }
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ContractError(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function exactKeys(value: Record<string, unknown>, expected: string[]): void {
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  if (
    actual.length !== wanted.length ||
    actual.some((key, index) => key !== wanted[index])
  ) {
    throw new ContractError(
      `Unexpected object keys: ${actual.filter((key) => !wanted.includes(key)).join(', ') || 'missing required key'}`,
    )
  }
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new ContractError(`${label} must be a string`)
  return value
}

function boundedString(value: unknown, max: number, label: string): string {
  const result = stringValue(value, label)
  if ([...result].length > max) throw new ContractError(`${label} is too long`)
  return result
}

function nonEmptyBoundedString(
  value: unknown,
  max: number,
  label: string,
): string {
  const result = boundedString(value, max, label)
  if (result.length === 0) throw new ContractError(`${label} is empty`)
  return result
}

function nullableBoundedString(
  value: unknown,
  max: number,
  label: string,
): void {
  if (value !== null) nonEmptyBoundedString(value, max, label)
}

function patternString(
  value: unknown,
  pattern: RegExp,
  label: string,
): string {
  const result = stringValue(value, label)
  if (!pattern.test(result)) throw new ContractError(`${label} has an invalid format`)
  return result
}

function nullablePattern(value: unknown, pattern: RegExp, label: string): void {
  if (value !== null) patternString(value, pattern, label)
}

function enumValue<const T extends readonly unknown[]>(
  value: unknown,
  options: T,
  label: string,
): T[number] {
  if (!options.includes(value)) {
    throw new ContractError(`${label} has an unsupported value`)
  }
  return value as T[number]
}

function constant<T>(value: unknown, expected: T, label: string): T {
  if (value !== expected) throw new ContractError(`${label} has an invalid value`)
  return expected
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw new ContractError(`${label} must be boolean`)
  return value
}

function nonNegativeNumber(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new ContractError(`${label} must be a non-negative number`)
  }
  return value
}

function nullableNonNegativeNumber(value: unknown, label: string): void {
  if (value !== null) nonNegativeNumber(value, label)
}

function boundedInteger(
  value: unknown,
  min: number,
  max: number,
  label: string,
): number {
  if (!Number.isInteger(value) || (value as number) < min || (value as number) > max) {
    throw new ContractError(`${label} must be an integer in range`)
  }
  return value as number
}

function positiveInteger(value: unknown, label: string): number {
  return boundedInteger(value, 1, Number.MAX_SAFE_INTEGER, label)
}

function nonNegativeInteger(value: unknown, label: string): number {
  return boundedInteger(value, 0, Number.MAX_SAFE_INTEGER, label)
}

function nullablePositiveInteger(value: unknown, label: string): void {
  if (value !== null) positiveInteger(value, label)
}

function arrayValue(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new ContractError(`${label} must be an array`)
  return value
}

function timestamp(value: unknown, label: string): void {
  const result = stringValue(value, label)
  if (!result.endsWith('Z') || Number.isNaN(Date.parse(result))) {
    throw new ContractError(`${label} must be a UTC ISO-8601 timestamp`)
  }
}

function nullableTimestamp(value: unknown, label: string): void {
  if (value !== null) timestamp(value, label)
}
