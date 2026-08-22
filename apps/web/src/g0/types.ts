export type TaskId = `task_${string}`
export type RunId = `run_${string}`
export type RequestId = `req_${string}`
export type MessageId = `msg_${string}`
export type FingerprintId = `fp_${string}`
export type PlanId = `plan_${string}`
export type ToolCallId = `tool_${string}`
export type ToolResultId = `toolres_${string}`
export type ErrorId = `err_${string}`
export type FeedbackId = `feedback_${string}`
export type MemoryJobId = `job_${string}`
export type SessionId = `sess_${string}`
export type UserId = `usr_${string}`

export type DemoAlias = 'blank_demo' | 'seeded_demo'
export type ProviderMode = 'mock' | 'real'
export type EffectiveMemoryMode = 'on' | 'off'
export type Scenario =
  | 'programming_learning'
  | 'software_development'
  | 'general_text'
  | 'other'
export type ClassificationReasonCode =
  | 'code_present'
  | 'technical_context'
  | 'debugging_cue'
  | 'learning_cue'
  | 'explanation_intent'
  | 'development_action'
  | 'deployment_cue'
  | 'text_task'
  | 'ambiguous'
export type ResponsePolicy = 'default' | 'guided_hint' | 'direct_fix'
export type RunStatus =
  | 'queued'
  | 'fingerprinting'
  | 'retrieving'
  | 'planning'
  | 'tool_running'
  | 'generating'
  | 'succeeded'
  | 'failed'
export type Stage =
  | 'fingerprinting'
  | 'retrieving'
  | 'planning'
  | 'tool_running'
  | 'generating'
  | 'failed'
export type ProgressLabel =
  | 'fingerprinting_task'
  | 'retrieving_memory'
  | 'publishing_plan'
  | 'running_static_tool'
  | 'generating_answer'
  | 'run_failed'
export type AsyncErrorCode =
  | 'PROVIDER_TIMEOUT'
  | 'PROVIDER_ERROR'
  | 'TOOL_NOT_FOUND'
  | 'TOOL_INPUT_INVALID'
  | 'STREAM_INTERRUPTED'
  | 'RUN_INTERRUPTED'
export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'TASK_NOT_FOUND'
  | 'PROVIDER_CONFIG_MISSING'
  | 'PROVIDER_TIMEOUT'
  | 'PROVIDER_ERROR'
  | 'TOOL_NOT_FOUND'
  | 'TOOL_INPUT_INVALID'
  | 'STREAM_INTERRUPTED'
  | 'INTERNAL_ERROR'
  | 'SESSION_REQUIRED'
  | 'IDEMPOTENCY_CONFLICT'
  | 'FEEDBACK_NO_CHANGES'
  | 'TASK_NOT_READY_FOR_FEEDBACK'

export interface CurrentConstraints {
  response_policy: ResponsePolicy
  urgency: 'normal' | 'urgent'
  memory_disabled: boolean
  source: 'ui'
}

export interface TaskCreateRequest {
  task_text: string
  memory_mode: 'on' | 'off'
  current_constraints: CurrentConstraints
}

export interface TaskCreateAccepted {
  request_id: RequestId
  task_id: TaskId
  run_id: RunId
  events_url: string
  provider_mode: ProviderMode
  effective_memory_mode: EffectiveMemoryMode
}

export interface DemoSessionResponse {
  request_id: RequestId
  demo_alias: DemoAlias
  expires_at: string
}

export interface TaskFingerprint {
  id: FingerprintId
  schema_version: '1.1'
  domain: Scenario
  classification_source: 'auto_rule_v1'
  classification_confidence: number
  classification_reasons: ClassificationReasonCode[]
  task_type:
    | 'debugging_guidance'
    | 'code_review'
    | 'code_explanation'
    | 'code_generation'
    | 'environment_configuration'
    | 'general_question'
    | 'other'
  artifact_type: 'source_code' | 'configuration' | 'text' | 'none' | 'other'
  audience: 'beginner' | 'intermediate' | 'advanced' | 'unknown'
  project_key: string | null
  language:
    | 'python'
    | 'javascript'
    | 'typescript'
    | 'java'
    | 'c'
    | 'cpp'
    | 'rust'
    | 'go'
    | 'other'
    | 'unknown'
  framework: string | null
  concepts: string[]
  tool_context: Array<'python_ast_check'>
  current_constraints: CurrentConstraints
  semantic_query: string
}

export interface PublicPlan {
  id: PlanId
  goal: string
  memory_summary: string
  next_action: string
}

export interface ToolDecision {
  action: 'call' | 'skip'
  tool_name: 'python_ast_check' | null
  reason_code:
    | 'python_code_detected'
    | 'non_python_task'
    | 'no_extractable_python'
    | 'unsupported_artifact'
  reason: string
}

export interface ToolArgsSummary {
  language: 'python'
  code_source: 'fenced_python' | 'whole_task_valid_python'
  code_bytes: number
}

export interface AstSyntaxError {
  message: string
  line: number | null
  column: number | null
  end_line: number | null
  end_column: number | null
}

export interface PythonAstResult {
  valid: boolean
  syntax_error: AstSyntaxError | null
}

export interface ToolCallSnapshot {
  tool_call_id: ToolCallId
  tool_name: 'python_ast_check'
  reason: string
  args_summary: ToolArgsSummary
  status: 'running' | 'succeeded' | 'failed'
  latency_ms: number | null
  result_ref: ToolResultId | null
  result: PythonAstResult | null
}

export interface MessageSnapshot {
  id: MessageId
  role: 'assistant'
  content: string
  created_at: string
}

export interface TaskMessageRecord {
  message_id: MessageId
  run_id: RunId | null
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type FeedbackType =
  | 'explicit_text'
  | 'edited_output'
  | 'rating'
  | 'accepted'
  | 'rejected'
  | 'composite'

export interface FeedbackCreateRequest {
  explicit_text?: string | null
  edited_output?: string | null
  rating?: number | null
  accepted?: boolean | null
}

export interface FeedbackCreateAccepted {
  request_id: RequestId
  feedback_id: FeedbackId
  memory_job_id: MemoryJobId
  feedback_type: FeedbackType
  job_status: 'pending'
}

export interface MemoryJobResponse {
  request_id: RequestId
  memory_job_id: MemoryJobId
  job_type: 'extract_feedback'
  status: 'pending' | 'running' | 'completed' | 'failed'
  stage: 'queued' | 'extracting' | 'done' | 'failed'
  attempt: number
  error: string | null
  created_at: string
  updated_at: string
}

export interface FeedbackEventRecord {
  feedback_id: FeedbackId
  run_id: RunId
  feedback_type: FeedbackType
  explicit_text: string | null
  edited_output: string | null
  rating: number | null
  accepted: boolean | null
  memory_job_id: MemoryJobId
  created_at: string
}

export interface RunErrorSnapshot {
  error_id: ErrorId
  code: AsyncErrorCode
  message: string
  retryable: boolean
}

export interface TaskSnapshot {
  request_id: RequestId
  task_id: TaskId
  run_id: RunId
  task_text: string
  scenario: Scenario
  task_status: 'active'
  run_status: RunStatus
  provider_mode: ProviderMode
  effective_memory_mode: EffectiveMemoryMode
  fingerprint: TaskFingerprint | null
  public_plan: PublicPlan | null
  tool_decision: ToolDecision | null
  tool_calls: ToolCallSnapshot[]
  partial_output: string
  end_offset: number
  offset_unit: 'utf8_bytes'
  messages: TaskMessageRecord[]
  final_message: MessageSnapshot | null
  feedback_events: FeedbackEventRecord[]
  error: RunErrorSnapshot | null
  terminal: boolean
  last_persistent_event_seq: number
  updated_at: string
}

export interface ErrorResponse {
  error: {
    code: ErrorCode
    message: string
    request_id: RequestId
    retryable: boolean
    details: Record<string, unknown>
  }
}

interface EventEnvelope<TType extends string, TData, TSequence> {
  event_version: '1.0'
  event_type: TType
  event_seq: TSequence
  task_id: TaskId
  run_id: RunId
  at: string
  data: TData
}

export type TaskCreatedEvent = EventEnvelope<
  'task.created',
  { task_status: 'active'; run_status: 'queued' },
  number
>
export type TaskStageEvent = EventEnvelope<
  'task.stage',
  { stage: Stage; progress_label: ProgressLabel },
  number
>
export type TaskFingerprintedEvent = EventEnvelope<
  'task.fingerprinted',
  {
    fingerprint_id: FingerprintId
    domain: Scenario
    classification_source: 'auto_rule_v1'
    classification_confidence: number
    classification_reasons: ClassificationReasonCode[]
    task_type: TaskFingerprint['task_type']
    artifact_type: TaskFingerprint['artifact_type']
    language: TaskFingerprint['language']
  },
  number
>
export type MemoryRetrievalStartedEvent = EventEnvelope<
  'memory.retrieval.started',
  { memory_count: 0; summary: 'no_long_term_memory_day1' },
  null
>
export type AgentPlanPublishedEvent = EventEnvelope<
  'agent.plan.published',
  {
    plan_id: PlanId
    goal_code: 'analyze_code' | 'answer_question' | 'explain_concept' | 'other'
    memory_summary_code: 'no_long_term_memory_day1'
    next_action_code: 'python_ast_check' | 'generate_directly'
  },
  number
>
export type ToolCalledEvent = EventEnvelope<
  'tool.called',
  {
    tool_call_id: ToolCallId
    tool_name: 'python_ast_check'
    reason_code: 'python_code_detected'
    args_summary: ToolArgsSummary
  },
  number
>
export type ToolResultEvent = EventEnvelope<
  'tool.result',
  {
    tool_call_id: ToolCallId
    tool_name: 'python_ast_check'
    status: 'succeeded' | 'failed'
    latency_ms: number
    result_ref: ToolResultId | null
  },
  number
>
export type AgentChunkEvent = EventEnvelope<
  'agent.chunk',
  {
    run_id: RunId
    chunk_seq: number
    start_offset: number
    end_offset: number
    offset_unit: 'utf8_bytes'
    delta: string
  },
  null
>
export type RunMetricsEvent = EventEnvelope<
  'run.metrics',
  {
    provider: string
    model: string
    provider_mode: ProviderMode
    first_token_ms: number | null
    total_ms: number | null
    prompt_tokens: number | null
    output_tokens: number | null
    token_source: 'actual' | 'unavailable' | 'mock'
  },
  number
>
export type RunCompletedEvent = EventEnvelope<
  'run.completed',
  {
    status: 'succeeded'
    message_id: MessageId
    end_offset: number
    offset_unit: 'utf8_bytes'
  },
  number
>
export type RunFailedEvent = EventEnvelope<
  'run.failed',
  {
    status: 'failed'
    error_code: AsyncErrorCode
    retryable: boolean
    partial_message_id: MessageId | null
    end_offset: number
    offset_unit: 'utf8_bytes'
  },
  number
>
export type ErrorEvent = EventEnvelope<
  'error',
  {
    error_id: ErrorId
    code: AsyncErrorCode
    message: string
    retryable: boolean
  },
  number
>
export type StreamDoneEvent = EventEnvelope<
  'stream.done',
  { status: 'succeeded' | 'failed'; final_snapshot_required: true },
  number
>
export type FeedbackRecordedEvent = EventEnvelope<
  'feedback.recorded',
  {
    feedback_id: FeedbackId
    memory_job_id: MemoryJobId
    feedback_type: FeedbackType
  },
  number
>

export type G0SseEvent =
  | TaskCreatedEvent
  | TaskStageEvent
  | TaskFingerprintedEvent
  | MemoryRetrievalStartedEvent
  | AgentPlanPublishedEvent
  | ToolCalledEvent
  | ToolResultEvent
  | AgentChunkEvent
  | RunMetricsEvent
  | RunCompletedEvent
  | RunFailedEvent
  | ErrorEvent
  | StreamDoneEvent
  | FeedbackRecordedEvent

export type G0EventType = G0SseEvent['event_type']

export const G0_EVENT_TYPES: readonly G0EventType[] = [
  'task.created',
  'task.stage',
  'task.fingerprinted',
  'memory.retrieval.started',
  'agent.plan.published',
  'tool.called',
  'tool.result',
  'agent.chunk',
  'run.metrics',
  'run.completed',
  'run.failed',
  'error',
  'stream.done',
  'feedback.recorded',
]
