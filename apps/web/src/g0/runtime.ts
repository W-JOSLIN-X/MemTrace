import {
  G0_EVENT_TYPES,
  type ErrorCode,
  type ErrorResponse,
  type G0EventType,
  type G0SseEvent,
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
      exactKeys(data, ['memory_count', 'summary'])
      constant(data.memory_count, 0, 'memory_count')
      constant(data.summary, 'no_long_term_memory_day1', 'summary')
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
      constant(
        data.memory_summary_code,
        'no_long_term_memory_day1',
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
