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
export type MemoryId = `mem_${string}`
export type MemoryVersionId = `memver_${string}`
export type EvidenceId = `evidence_${string}`
export type SessionId = `sess_${string}`
export type UserId = `usr_${string}`
export type RetrievalTraceId = `trace_${string}`
export type UsageId = `usage_${string}`
export type RelationId = `rel_${string}`
export type ImportBatchId = `batch_${string}`
export type PackId = `pack_${string}`

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
  | 'MEMORY_NOT_FOUND'
  | 'MEMORY_ALREADY_RESOLVED'
  | 'MEMORY_JOB_NOT_RETRYABLE'
  | 'MEMORY_STATE_CONFLICT'
  | 'MEMORY_VERSION_CONFLICT'
  | 'INVALID_CURSOR'
  | 'MEMORY_RELATION_NOT_FOUND'
  | 'MEMORY_CONFLICT_ALREADY_RESOLVED'
  | 'MEMORY_MERGE_CONFLICT'
  | 'CONFIRMATION_MISMATCH'
  | 'MEMORY_PACK_TOO_LARGE'
  | 'MEMORY_PACK_INVALID'
  | 'MEMORY_PACK_UNSUPPORTED_VERSION'
  | 'MEMORY_PACK_INTEGRITY_MISMATCH'
  | 'IMPORT_BATCH_NOT_FOUND'
  | 'IMPORT_BATCH_EXPIRED'
  | 'IMPORT_PREVIEW_TOKEN_INVALID'
  | 'IMPORT_BATCH_STATE_CONFLICT'

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

export type MemoryJobStage =
  | 'queued'
  | 'diffing'
  | 'classifying_durability'
  | 'extracting'
  | 'validating'
  | 'admitting'
  | 'done'
  | 'failed'

export type Disposition =
  | 'candidate_created'
  | 'episode_only'
  | 'reinforce_usage_only'
  | 'no_memory'
  | 'failed'

export type MemoryJobErrorCode =
  | 'MEMORY_JOB_INTERRUPTED'
  | 'MEMORY_JSON_INVALID'
  | 'MEMORY_SCHEMA_INVALID'
  | 'MEMORY_REPAIR_FAILED'
  | 'MEMORY_PROVIDER_ERROR'
  | 'MEMORY_PROVIDER_TIMEOUT'
  | 'MEMORY_EVIDENCE_NOT_FOUND'
  | 'MEMORY_NO_REUSABLE_CONTENT'
  | 'MEMORY_SCOPE_TOO_BROAD'

export interface MemoryJobResponse {
  request_id: RequestId
  memory_job_id: MemoryJobId
  feedback_id: FeedbackId
  job_type: 'extract_feedback'
  status: 'pending' | 'running' | 'completed' | 'failed'
  stage: MemoryJobStage
  attempt: number
  candidate_ids: MemoryId[]
  disposition: Disposition | null
  error_code: MemoryJobErrorCode | null
  retryable: boolean
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
  retrieval_trace: RetrievalTrace | null
  memory_usages: MemoryUsage[]
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
  { retrieval_mode: 'tfidf' },
  null
>
export type MemoryRetrievalCompletedEvent = EventEnvelope<
  'memory.retrieval.completed',
  {
    trace_id: RetrievalTraceId
    mode: 'tfidf' | 'tfidf_degraded'
    algorithm_version: 'char_tfidf_v1'
    candidate_count: number
    retrieved_count: number
    selected_count: number
    injected_count: number
    threshold: number
    top_k: number
    retrieval_ms: number
    memory_chars: number
    estimated_tokens: number
    prompt_section_hash: string | null
  },
  number
>
export type MemoryInjectedEvent = EventEnvelope<
  'memory.injected',
  {
    usage_id: UsageId
    trace_id: RetrievalTraceId
    memory_id: MemoryId
    memory_version_id: MemoryVersionId
    rank: number
    estimated_tokens: number
    prompt_section_hash: string | null
  },
  number
>
export type MemoryUsageVerifiedEvent = EventEnvelope<
  'memory.usage.verified',
  {
    usage_id: UsageId
    memory_id: MemoryId
    memory_version_id: MemoryVersionId
    verification_status: VerificationStatus
    verification_method: 'exact_substring' | 'structured_provider' | null
    evidence_present: boolean
  },
  number
>
export type MemoryUsageFeedbackRecordedEvent = EventEnvelope<
  'memory.usage.feedback.recorded',
  { usage_id: UsageId; memory_id: MemoryId; user_effect: UserEffect },
  number
>
export type AgentPlanPublishedEvent = EventEnvelope<
  'agent.plan.published',
  {
    plan_id: PlanId
    goal_code: 'analyze_code' | 'answer_question' | 'explain_concept' | 'other'
    memory_summary_code: 'no_memory_selected' | 'memory_selected'
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

export type MemoryExtractionStageEvent = EventEnvelope<
  'memory.extraction.stage',
  { memory_job_id: MemoryJobId; stage: MemoryJobStage },
  number
>
export type MemoryCandidateCreatedEvent = EventEnvelope<
  'memory.candidate.created',
  {
    memory_job_id: MemoryJobId
    memory_id: MemoryId
    evidence_id: EvidenceId
    ordinal: number
  },
  number
>
export type MemoryAdmissionResolvedEvent = EventEnvelope<
  'memory.admission.resolved',
  {
    memory_id: MemoryId
    old_status: MemoryCardStatus
    new_status: MemoryCardStatus
    memory_version_id: MemoryVersionId | null
    disposition: Disposition
  },
  number
>
export type MemoryJobFailedEvent = EventEnvelope<
  'memory.job.failed',
  {
    memory_job_id: MemoryJobId
    stage: MemoryJobStage
    error_code: MemoryJobErrorCode
    retryable: boolean
  },
  number
>

export type MemoryCardStatus =
  | 'candidate'
  | 'active'
  | 'rejected'
  | 'conflicted'
  | 'paused'
  | 'superseded'
  | 'merged'
  | 'archived'
  | 'deleted'

export type MemoryRejectionReason = 'user_rejected' | 'episode_only'

export type MemoryKind =
  | 'preference'
  | 'constraint'
  | 'procedure'
  | 'experience'
  | 'environment'
  | 'learning_checkpoint'

export type MemorySourceType =
  | 'explicit_feedback'
  | 'explicit_correction'
  | 'edit_diff'
  | 'accept'
  | 'reject'
  | 'rating'
  | 'outcome'
  | 'import'

export type MemoryScopeLevel =
  | 'session'
  | 'task_family'
  | 'project'
  | 'global'

export type MemoryScopeDomain = Scenario | 'any'

export type AllowedMemoryException =
  | 'response_policy:direct_fix'
  | 'urgency:urgent'

export interface MemoryScope {
  level: MemoryScopeLevel
  domain: MemoryScopeDomain
  task_type: TaskFingerprint['task_type'] | 'any' | null
  artifact_type: TaskFingerprint['artifact_type'] | 'any' | null
  audience: TaskFingerprint['audience'] | 'any' | null
  project_key: string | null
  language: TaskFingerprint['language'] | 'any' | null
  framework: string | null
  concepts: string[]
}

export interface MemoryCard {
  memory_id: MemoryId
  schema_version: '1.0'
  kind: MemoryKind
  title: string
  rule: string
  avoid: string
  trigger_text: string
  scope: MemoryScope
  exceptions: AllowedMemoryException[]
  status: MemoryCardStatus
  rejection_reason: MemoryRejectionReason | null
  source_type: MemorySourceType
  save_preselected: boolean
  source_trust: number
  rule_confidence: number | null
  scope_confidence: number | null
  evidence_count: number
  version: number
  current_version_id: MemoryVersionId | null
  valid_from: string | null
  valid_to: string | null
  retrieved_count: number
  injected_count: number
  verified_applied_count: number
  helpful_count: number
  harmful_count: number
  stale_count: number
  last_used_at: string | null
  evidence_missing: boolean
  import_batch_id: ImportBatchId | null
  import_source_version: number | null
  created_at: string
  updated_at: string
}

export interface MemoryCardPatch {
  title?: string | null
  rule?: string | null
  avoid?: string | null
  trigger_text?: string | null
  scope?: MemoryScope | null
  exceptions?: AllowedMemoryException[] | null
}

export type ResolveAction = 'accept' | 'edit_accept' | 'reject' | 'one_shot'

export interface ResolveRequest {
  action: ResolveAction
  patch?: MemoryCardPatch | null
}

export interface ResolveResponse {
  request_id: RequestId
  memory_id: MemoryId
  action: ResolveAction
  old_status: MemoryCardStatus
  new_status: MemoryCardStatus
  disposition: Disposition
  memory_version_id: MemoryVersionId | null
  card: MemoryCard
}

export interface MemoryListResponse {
  request_id: RequestId
  items: MemoryCard[]
  next_cursor: string | null
}

export interface MemoryEvidenceProjection {
  evidence_id: EvidenceId
  source_type: MemorySourceType
  feedback_id: FeedbackId | null
  task_id: TaskId | null
  run_id: RunId | null
  evidence_quote: string
  diff_summary: string | null
  normalized_edit_cost: number | null
  created_at: string
}

export interface MemoryVersionProjection {
  memory_version_id: MemoryVersionId
  version: number
  title: string
  rule: string
  avoid: string
  trigger_text: string
  scope: MemoryScope
  exceptions: AllowedMemoryException[]
  created_by_action:
    | 'accept'
    | 'edit_accept'
    | 'edit'
    | 'import'
    | 'merge'
    | 'scope_resolution'
  created_at: string
}

export type RetrievalReasonCode =
  | 'selected_above_threshold'
  | 'memory_mode_off'
  | 'status_not_active'
  | 'not_yet_valid'
  | 'expired'
  | 'scope_domain_mismatch'
  | 'scope_task_type_mismatch'
  | 'scope_artifact_mismatch'
  | 'scope_audience_mismatch'
  | 'scope_project_mismatch'
  | 'scope_language_mismatch'
  | 'scope_framework_mismatch'
  | 'current_constraint_override'
  | 'active_conflict'
  | 'invalid_active_card'
  | 'empty_vector'
  | 'below_threshold'
  | 'top_k_exceeded'
  | 'prompt_budget_exceeded'

export type VerificationStatus =
  | 'pending'
  | 'applied'
  | 'violated'
  | 'not_observable'
  | 'unknown'
export type UserEffect = 'helpful' | 'harmful' | 'stale'

export interface RetrievalDecision {
  memory_id: MemoryId
  memory_version_id: MemoryVersionId | null
  memory_status: MemoryCardStatus
  retrieved: boolean
  selected: boolean
  injected: boolean
  rank: number | null
  scope_match: number | null
  semantic_similarity: number | null
  provenance_confidence: number | null
  verified_effect: number | null
  recency: number | null
  final_score: number | null
  reason_codes: RetrievalReasonCode[]
}

export interface RetrievalTrace {
  request_id: RequestId
  retrieval_trace_id: RetrievalTraceId
  task_id: TaskId
  run_id: RunId
  retrieval_mode: 'tfidf' | 'tfidf_degraded'
  algorithm_version: 'char_tfidf_v1'
  threshold: number
  top_k: number
  candidate_count: number
  retrieved_count: number
  selected_count: number
  injected_count: number
  decisions: RetrievalDecision[]
  retrieval_ms: number
  memory_chars: number
  memory_tokens_estimated: number
  provider_prompt_tokens_actual: number | null
  prompt_section_hash: string | null
  reason_codes: RetrievalReasonCode[]
  created_at: string
  updated_at: string
}

export interface MemoryUsage {
  request_id: RequestId
  usage_id: UsageId
  retrieval_trace_id: RetrievalTraceId
  task_id: TaskId
  run_id: RunId
  memory_id: MemoryId
  memory_version_id: MemoryVersionId
  rank: number
  retrieved: boolean
  selected: boolean
  injected: boolean
  estimated_tokens: number
  verification_status: VerificationStatus
  verification_method: 'exact_substring' | 'structured_provider' | null
  evidence_excerpt: string | null
  user_effect: UserEffect | null
  created_at: string
  updated_at: string
}

export interface MemoryUsageListResponse {
  request_id: RequestId
  items: MemoryUsage[]
  next_cursor: string | null
}

export interface MemoryVersionListResponse {
  request_id: RequestId
  items: MemoryVersionProjection[]
  next_cursor: string | null
}

export interface ActiveMemoryEditRequest {
  expected_current_version_id: MemoryVersionId
  patch: MemoryCardPatch
}

export interface MemoryDetailResponse {
  request_id: RequestId
  card: MemoryCard
  evidence: MemoryEvidenceProjection[]
  versions: MemoryVersionProjection[]
  relations: MemoryRelation[]
}

export type MemoryRelationType =
  | 'duplicate_of'
  | 'reinforces'
  | 'conflicts_with'
  | 'supersedes'
  | 'merged_into'
  | 'related_to'

export interface MemoryRelation {
  relation_id: RelationId
  from_memory_id: MemoryId
  to_memory_id: MemoryId
  relation_type: MemoryRelationType
  status: 'unresolved' | 'resolved'
  resolution_action: 'prefer' | 'separate_scopes' | 'merge' | 'pause_both' | null
  resolution_memory_id: MemoryId | null
  created_at: string
  resolved_at: string | null
}

export interface MemoryRelationListResponse {
  request_id: RequestId
  items: MemoryRelation[]
  next_cursor: string | null
}

export interface MemoryVersionDiffResponse {
  request_id: RequestId
  from_version: MemoryVersionProjection
  to_version: MemoryVersionProjection
  changed_fields: Array<'title' | 'rule' | 'avoid' | 'trigger_text' | 'scope' | 'exceptions'>
}

export type G0SseEvent =
  | TaskCreatedEvent
  | TaskStageEvent
  | TaskFingerprintedEvent
  | MemoryRetrievalStartedEvent
  | MemoryRetrievalCompletedEvent
  | MemoryInjectedEvent
  | MemoryUsageVerifiedEvent
  | MemoryUsageFeedbackRecordedEvent
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
  | MemoryExtractionStageEvent
  | MemoryCandidateCreatedEvent
  | MemoryAdmissionResolvedEvent
  | MemoryJobFailedEvent

export type G0EventType = G0SseEvent['event_type']

export const G0_EVENT_TYPES: readonly G0EventType[] = [
  'task.created',
  'task.stage',
  'task.fingerprinted',
  'memory.retrieval.started',
  'memory.retrieval.completed',
  'memory.injected',
  'memory.usage.verified',
  'memory.usage.feedback.recorded',
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
  'memory.extraction.stage',
  'memory.candidate.created',
  'memory.admission.resolved',
  'memory.job.failed',
]
