export type TaskId = `task_${string}`
export type RunId = `run_${string}`
export type MessageId = `msg_${string}`
export type MemoryId = `mem_${string}`
export type MemoryVersionId = `memver_${string}`
export type ReflectionJobId = `job_${string}`

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
  stage: 'summary' | 'applicability' | 'chat' | 'reflection' | 'consolidation' | 'effect'
  provider_mode: ProviderMode
  model: string
  prompt_hash: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  reasoning_tokens: number | null
  latency_ms: number
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
  schema_version: '2.0.0'
  request_id: string
  task_id: TaskId
  provider_mode: ProviderMode
  model: string
  memory_mode: MemoryMode
  created_at: string
}

export type ConversationTurnResponse = {
  schema_version: '2.0.0'
  request_id: string
  task_id: TaskId
  run_id: RunId
  turn_index: number
  user_message: ConversationMessage
  assistant_message: ConversationMessage
  reflection_job_id: ReflectionJobId | null
  memory_mode: MemoryMode
  memory_decisions: MemoryDecision[]
  usage: StageUsage[]
}

export type ConversationTurnState = {
  run_id: RunId
  turn_index: number
  reflection_job_id: ReflectionJobId | null
  memory_decisions: MemoryDecision[]
  usage: StageUsage[]
}

export type ConversationSnapshot = {
  schema_version: '2.0.0'
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

export type MemoryProjection = {
  memory_id: MemoryId
  kind: MemoryKind
  content: string
  applies_when: string
  review_status: ReviewStatus
  confidence: number
  current_version_id: MemoryVersionId
  version: number
  source_type: 'conversation_turn' | 'user_edit'
  created_at: string
  updated_at: string
}

export type MemoryListResponse = {
  request_id: string
  items: MemoryProjection[]
  next_cursor: MemoryId | null
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
  request_id: string
  items: MemoryEvent[]
  next_seq: number | null
}

export type MemoryLifecycleResponse = {
  request_id: string
  memory_id: MemoryId
  old_status: ReviewStatus
  new_status: ReviewStatus
  updated_at: string
}
