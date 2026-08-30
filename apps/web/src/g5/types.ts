export type TaskId = `task_${string}`
export type RunId = `run_${string}`
export type MessageId = `msg_${string}`
export type MemoryId = `mem_${string}`
export type MemoryVersionId = `memver_${string}`
export type ReflectionJobId = `job_${string}`
export type ToolCallId = `tool_${string}`
export type ToolResultId = `toolres_${string}`

export type ProviderMode = 'real' | 'mock'
export type MemoryMode = 'on' | 'off'
export type MemoryKind = 'preference' | 'rule' | 'experience'
export type ReviewStatus =
  | 'pending'
  | 'active'
  | 'paused'
  | 'archived'
  | 'superseded'

export type ConversationMessage = {
  message_id: MessageId
  run_id: RunId | null
  role: 'user' | 'assistant'
  content: string
  turn_index: number
  created_at: string
}

export type StageUsage = {
  stage:
    | 'summary'
    | 'applicability'
    | 'tool_planning'
    | 'chat'
    | 'reflection'
    | 'consolidation'
    | 'effect'
  provider_mode: ProviderMode
  model: string
  prompt_hash: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  reasoning_tokens: number | null
  latency_ms: number
  first_token_ms: number | null
}

export type ToolCall = {
  tool_call_id: ToolCallId
  tool_name: 'python_ast_check'
  reason: string
  args_summary: {
    language: 'python'
    code_source: 'fenced_python' | 'whole_task_valid_python'
    code_bytes: number
  }
  status: 'running' | 'succeeded' | 'failed'
  latency_ms: number | null
  result_ref: ToolResultId | null
  result: {
    valid: boolean
    syntax_error: {
      message: string
      line: number | null
      column: number | null
      end_line: number | null
      end_column: number | null
    } | null
  } | null
}

export type MemoryDecision = {
  memory_id: MemoryId
  applicability:
    | 'applicable'
    | 'current_instruction_override'
    | 'conflict'
    | 'irrelevant'
  reason_code:
    | 'semantic_match'
    | 'current_instruction_override'
    | 'memory_conflict'
    | 'scope_mismatch'
    | 'outdated'
    | 'irrelevant'
    | 'ambiguous'
  confidence: number
  injected: boolean
  estimated_tokens: number
  effect: 'applied' | 'violated' | 'not_observable' | 'unknown' | null
}

export type ConversationCreateResponse = {
  schema_version: '2.1.0'
  request_id: string
  task_id: TaskId
  provider_mode: ProviderMode
  model: string
  memory_mode: MemoryMode
  created_at: string
}

export type ConversationTurnResponse = {
  schema_version: '2.1.0'
  request_id: string
  task_id: TaskId
  run_id: RunId
  turn_index: number
  user_message: ConversationMessage
  assistant_message: ConversationMessage
  reflection_job_id: ReflectionJobId | null
  memory_mode: MemoryMode
  memory_decisions: MemoryDecision[]
  tool_calls: ToolCall[]
  usage: StageUsage[]
}

export type ConversationTurnState = {
  run_id: RunId
  turn_index: number
  reflection_job_id: ReflectionJobId | null
  memory_decisions: MemoryDecision[]
  tool_calls: ToolCall[]
  usage: StageUsage[]
}

export type ConversationSnapshot = {
  schema_version: '2.1.0'
  request_id: string
  task_id: TaskId
  memory_mode: MemoryMode
  provider_mode: ProviderMode
  model: string
  messages: ConversationMessage[]
  last_turn: ConversationTurnState | null
  last_event_seq: number
  created_at: string
  updated_at: string
}

export type ConversationListItem = {
  task_id: TaskId
  title: string
  memory_mode: MemoryMode
  message_count: number
  created_at: string
  updated_at: string
}

export type ConversationListResponse = {
  schema_version: '2.1.0'
  request_id: string
  items: ConversationListItem[]
  next_cursor: TaskId | null
}

export type MemoryProjection = {
  memory_id: MemoryId
  kind: MemoryKind
  content: string
  applies_when: string
  review_status: ReviewStatus
  confidence: number
  current_version_id: MemoryVersionId
  version: number
  source_type: 'conversation_turn' | 'user_edit' | 'import'
  retrieved_count: number
  injected_count: number
  verified_applied_count: number
  helpful_count: number
  harmful_count: number
  stale_count: number
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export type MemoryListResponse = {
  schema_version: '2.1.0'
  request_id: string
  items: MemoryProjection[]
  next_cursor: MemoryId | null
}

export type MemoryVersionProjection = {
  version_id: MemoryVersionId
  version: number
  kind: MemoryKind
  content: string
  applies_when: string
  review_status: ReviewStatus
  confidence: number
  created_by_action:
    | 'accept'
    | 'edit_accept'
    | 'edit'
    | 'import'
    | 'merge'
    | 'scope_resolution'
    | 'llm_extract'
    | 'llm_update'
    | 'llm_supersede'
    | 'llm_coexist'
    | 'user_edit'
    | 'user_restore'
  created_at: string
}

export type MemoryEvidenceProjection = {
  evidence_id: `evidence_${string}`
  message_id: MessageId
  task_id: TaskId
  turn_index: number
  source_type: 'conversation_turn' | 'user_edit'
  is_primary: boolean
  created_at: string
}

export type MemoryDetailResponse = {
  schema_version: '2.1.0'
  request_id: string
  memory: MemoryProjection
  versions: MemoryVersionProjection[]
  evidence: MemoryEvidenceProjection[]
}

export type MemoryVersionDiffResponse = {
  schema_version: '2.1.0'
  request_id: string
  from_version: MemoryVersionProjection
  to_version: MemoryVersionProjection
  changed_fields: Array<'kind' | 'content' | 'applies_when' | 'review_status' | 'confidence'>
}

export type MemoryUsage = {
  usage_id: `usage_${string}`
  task_id: TaskId
  run_id: RunId
  memory_id: MemoryId
  memory_version_id: MemoryVersionId
  injected: boolean
  estimated_tokens: number
  verification_status: 'pending' | 'applied' | 'violated' | 'not_observable' | 'unknown'
  user_effect: UserEffect | null
  created_at: string
  updated_at: string
}

export type MemoryUsageListResponse = {
  schema_version: '2.1.0'
  request_id: string
  items: MemoryUsage[]
  next_cursor: `usage_${string}` | null
}

export type MemoryRelation = {
  relation_id: `rel_${string}`
  from_memory_id: MemoryId
  to_memory_id: MemoryId
  relation_type:
    | 'duplicate_of'
    | 'conflicts_with'
    | 'supersedes'
    | 'reinforces'
    | 'merged_into'
    | 'related_to'
  status: 'unresolved' | 'resolved'
  resolution_action: 'prefer' | 'separate_scopes' | 'merge' | 'pause_both' | null
  resolution_memory_id: MemoryId | null
  created_at: string
}

export type MemoryRelationListResponse = {
  schema_version: '2.1.0'
  request_id: string
  items: MemoryRelation[]
  next_cursor: `rel_${string}` | null
}

export type MemoryConflictDetail = {
  schema_version: '2.1.0'
  request_id: string
  relation: MemoryRelation
  left: MemoryProjection
  right: MemoryProjection
}

export type MemoryConflictResolveRequest = {
  expected_relation_status: 'unresolved'
  left_expected_current_version_id: MemoryVersionId
  right_expected_current_version_id: MemoryVersionId
  action: 'prefer' | 'separate_scopes' | 'merge' | 'pause_both'
  preferred_memory_id?: MemoryId
  left_applies_when?: string
  right_applies_when?: string
  merged_memory?: { kind: MemoryKind; content: string; applies_when: string }
}

export type MemoryConflictResolveResponse = {
  schema_version: '2.1.0'
  request_id: string
  relation_id: `rel_${string}`
  action: 'prefer' | 'separate_scopes' | 'merge' | 'pause_both'
  status: 'resolved'
  resolution_memory_id: MemoryId | null
}

export type MemoryDeleteResponse = {
  schema_version: '2.1.0'
  request_id: string
  memory_id: MemoryId
  status: 'deleted'
  deleted_at: string
}

export type SourceTaskDeleteResponse = {
  schema_version: '2.1.0'
  request_id: string
  task_id: TaskId
  status: 'deleted'
  memory_policy: 'preserve_and_mark_evidence_missing'
  affected_memory_count: number
}

export type MemoryPackDocument = {
  schema_ref: 'memtrace-memory-pack@2.0.0'
  format: 'memtrace-memory-pack'
  format_version: '2.0.0'
  pack_id: `pack_${string}`
  name: string
  description: string
  created_at: string
  producer: { name: string; version: string }
  source: { kind: 'user_export' | 'external_import'; trust: 'self_asserted' | 'unverified' }
  privacy: { contains_raw_evidence: false; anonymized: true }
  cards: Array<{
    external_id: `card_${string}`
    schema_version: '2.0'
    kind: MemoryKind
    content: string
    applies_when: string
    claimed_origin: {
      source_type: 'conversation_turn' | 'user_edit' | 'import'
      trust_level: 'user_confirmed' | 'self_asserted' | 'imported_unverified'
      created_at: string
      source_version: number
    }
    version: number
    updated_at: string
  }>
  relations: Array<{
    from_external_id: `card_${string}`
    to_external_id: `card_${string}`
    relation_type:
      | 'duplicate_of'
      | 'reinforces'
      | 'conflicts_with'
      | 'supersedes'
      | 'merged_into'
      | 'related_to'
  }>
  integrity: { algorithm: 'sha256'; canonical_payload_sha256: string }
}

export type PackPreview = {
  schema_version: '2.1.0'
  request_id: string
  batch_id: `batch_${string}`
  name: string
  description: string
  format_version: '2.0.0'
  legal_new_count: number
  duplicate_count: number
  potential_conflict_count: number
  suspicious_count: number
  items: Array<{
    external_id: `card_${string}`
    kind: MemoryKind
    content: string
    applies_when: string
    classification: 'legal_new' | 'duplicate' | 'potential_conflict' | 'suspicious'
    reason: 'exact_duplicate' | 'declared_conflict' | 'suspicious_text' | null
  }>
  preview_token: string
  expires_at: string
}

export type PackCommitResponse = {
  schema_version: '2.1.0'
  request_id: string
  batch_id: `batch_${string}`
  inserted_count: number
  skipped_count: number
  warning_count: number
}

export type MemoryEditRequest = {
  kind?: MemoryKind
  content?: string
  applies_when?: string
  expected_current_version_id: MemoryVersionId
}

export type ReflectionJob = {
  request_id: string
  job_id: ReflectionJobId
  task_id: TaskId
  run_id: RunId
  turn_index: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  attempt: number
  mutation_decision: 'mutate' | 'noop' | 'needs_review' | null
  provider_model: string
  schema_version: '2.0'
  error_code: string | null
  created_at: string
  updated_at: string
}

export type MemoryEvent = {
  event_id: string
  event_seq: number
  event_type: string
  memory_id: MemoryId | null
  version_id: MemoryVersionId | null
  old_status: ReviewStatus | null
  new_status: ReviewStatus | null
  reason_code: string | null
  job_id: ReflectionJobId | null
  created_at: string | null
}

export type MemoryEventList = {
  schema_version: '2.1.0'
  request_id: string
  items: MemoryEvent[]
  next_seq: number | null
}

export type MemoryLifecycleResponse = {
  schema_version: '2.1.0'
  request_id: string
  memory_id: MemoryId
  old_status: ReviewStatus
  new_status: ReviewStatus
  updated_at: string
}

export type UserEffect = 'helpful' | 'harmful' | 'stale'

export type MemoryFeedbackResponse = {
  schema_version: '2.1.0'
  request_id: string
  task_id: TaskId
  memory_id: MemoryId
  effect: UserEffect
  updated_at: string
}
