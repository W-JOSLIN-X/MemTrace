import { utf8ByteLength } from './runtime'
import type {
  AgentPlanPublishedEvent,
  G0SseEvent,
  EvidenceId,
  Disposition,
  FeedbackId,
  MemoryDetailResponse,
  MemoryId,
  MemoryJobId,
  MemoryJobResponse,
  MemoryJobStage,
  ResolveAction,
  ResolveResponse,
  ProviderMode,
  RunMetricsEvent,
  RunStatus,
  Scenario,
  Stage,
  TaskCreateAccepted,
  TaskFingerprintedEvent,
  TaskId,
  TaskSnapshot,
  ToolCalledEvent,
  ToolResultEvent,
} from './types'

export type G0Phase =
  | 'idle'
  | 'submitting'
  | 'connecting'
  | 'streaming'
  | 'reconnecting'
  | 'finalizing'
  | 'succeeded'
  | 'failed'
  | 'connection_failed'

export type RecoveryReason =
  | 'chunk_gap'
  | 'unsafe_overlap'
  | 'persistent_gap'
  | 'protocol_error'
  | null

export interface StageRecord {
  stage: Stage
  progressLabel: string
  eventSeq: number
  at: string
}

export interface ToolActivity {
  toolCallId: string
  toolName: 'python_ast_check'
  status: 'running' | 'succeeded' | 'failed'
  reasonCode: 'python_code_detected'
  argsSummary: ToolCalledEvent['data']['args_summary']
  latencyMs: number | null
  resultRef: string | null
}

export interface PublicUiError {
  code: string
  message: string
  retryable: boolean
}

export interface G0State {
  phase: G0Phase
  taskId: TaskId | null
  runId: string | null
  eventsUrl: string | null
  taskText: string
  scenario: Scenario | null
  providerMode: ProviderMode | null
  effectiveMemoryMode: 'on' | 'off' | null
  runStatus: RunStatus | null
  stages: StageRecord[]
  fingerprintSummary: TaskFingerprintedEvent['data'] | null
  publicPlan: TaskSnapshot['public_plan']
  planCodes: AgentPlanPublishedEvent['data'] | null
  toolDecision: TaskSnapshot['tool_decision']
  toolCalls: TaskSnapshot['tool_calls']
  toolActivity: ToolActivity | null
  memoryObserved: boolean
  output: string
  endOffset: number
  lastPersistentEventSeq: number
  metrics: RunMetricsEvent['data'] | null
  messages: TaskSnapshot['messages']
  feedbackEvents: TaskSnapshot['feedback_events']
  feedbackJobIds: Partial<Record<FeedbackId, MemoryJobId>>
  memoryJobs: Partial<Record<MemoryJobId, MemoryJobResponse>>
  memoryJobStages: Partial<Record<MemoryJobId, MemoryJobStage>>
  memoryJobFailures: Partial<
    Record<MemoryJobId, Extract<G0SseEvent, { event_type: 'memory.job.failed' }>['data']>
  >
  memoryCandidateIds: Partial<Record<MemoryJobId, MemoryId[]>>
  memoryEvidenceIds: Partial<Record<MemoryId, EvidenceId[]>>
  memoryDetails: Partial<Record<MemoryId, MemoryDetailResponse>>
  memoryResolvePending: Partial<Record<MemoryId, boolean>>
  memoryResolveErrors: Partial<Record<MemoryId, PublicUiError>>
  memoryResolveActions: Partial<Record<MemoryId, ResolveAction>>
  memoryDispositions: Partial<Record<MemoryId, Disposition>>
  openEvidenceMemoryId: MemoryId | null
  lastFeedbackRecorded: Extract<
    G0SseEvent,
    { event_type: 'feedback.recorded' }
  >['data'] | null
  error: PublicUiError | null
  terminal: boolean
  reconnectAttempt: number
  recoveryReason: RecoveryReason
}

export type G0Action =
  | { type: 'owner_reset' }
  | { type: 'submit_started' }
  | { type: 'submit_failed'; error: PublicUiError }
  | { type: 'task_accepted'; accepted: TaskCreateAccepted; taskText: string }
  | { type: 'task_restored'; snapshot: TaskSnapshot }
  | { type: 'connection_opened' }
  | { type: 'connection_recovering'; attempt: number; reason: RecoveryReason }
  | { type: 'connection_exhausted'; error: PublicUiError }
  | { type: 'protocol_error' }
  | { type: 'sse_event'; event: G0SseEvent }
  | { type: 'memory_job_received'; job: MemoryJobResponse }
  | { type: 'memory_detail_received'; detail: MemoryDetailResponse }
  | { type: 'memory_resolve_started'; memoryId: MemoryId }
  | {
      type: 'memory_resolve_failed'
      memoryId: MemoryId
      error: PublicUiError
    }
  | {
      type: 'memory_resolved'
      detail: MemoryDetailResponse
      resolution: ResolveResponse
    }
  | { type: 'memory_evidence_toggled'; memoryId: MemoryId }
  | {
      type: 'snapshot_received'
      snapshot: TaskSnapshot
      mode: 'enrichment' | 'recovery' | 'final' | 'restore'
    }

export function createInitialG0State(): G0State {
  return {
    phase: 'idle',
    taskId: null,
    runId: null,
    eventsUrl: null,
    taskText: '',
    scenario: null,
    providerMode: null,
    effectiveMemoryMode: null,
    runStatus: null,
    stages: [],
    fingerprintSummary: null,
    publicPlan: null,
    planCodes: null,
    toolDecision: null,
    toolCalls: [],
    toolActivity: null,
    memoryObserved: false,
    output: '',
    endOffset: 0,
    lastPersistentEventSeq: 0,
    metrics: null,
    messages: [],
    feedbackEvents: [],
    feedbackJobIds: {},
    memoryJobs: {},
    memoryJobStages: {},
    memoryJobFailures: {},
    memoryCandidateIds: {},
    memoryEvidenceIds: {},
    memoryDetails: {},
    memoryResolvePending: {},
    memoryResolveErrors: {},
    memoryResolveActions: {},
    memoryDispositions: {},
    openEvidenceMemoryId: null,
    lastFeedbackRecorded: null,
    error: null,
    terminal: false,
    reconnectAttempt: 0,
    recoveryReason: null,
  }
}

export function g0Reducer(state: G0State, action: G0Action): G0State {
  switch (action.type) {
    case 'owner_reset':
      return createInitialG0State()
    case 'submit_started':
      return { ...createInitialG0State(), phase: 'submitting' }
    case 'submit_failed':
      return {
        ...createInitialG0State(),
        phase: 'failed',
        error: action.error,
      }
    case 'task_accepted':
      return {
        ...createInitialG0State(),
        phase: 'connecting',
        taskId: action.accepted.task_id,
        runId: action.accepted.run_id,
        eventsUrl: action.accepted.events_url,
        taskText: action.taskText,
        providerMode: action.accepted.provider_mode,
        effectiveMemoryMode: action.accepted.effective_memory_mode,
        runStatus: 'queued',
      }
    case 'task_restored': {
      const snapshot = action.snapshot
      const base: G0State = {
        ...createInitialG0State(),
        phase: snapshot.terminal ? 'finalizing' : 'reconnecting',
        taskId: snapshot.task_id,
        runId: snapshot.run_id,
        eventsUrl: `/api/v1/tasks/${snapshot.task_id}/events`,
        taskText: snapshot.task_text,
        scenario: snapshot.scenario,
        providerMode: snapshot.provider_mode,
        effectiveMemoryMode: snapshot.effective_memory_mode,
        runStatus: snapshot.run_status,
      }
      return mergeSnapshot(
        base,
        snapshot,
        snapshot.terminal ? 'final' : 'restore',
      )
    }
    case 'connection_opened':
      if (state.terminal) return state
      return {
        ...state,
        phase: 'streaming',
        reconnectAttempt: 0,
        recoveryReason: null,
      }
    case 'connection_recovering':
      if (state.terminal) return state
      return {
        ...state,
        phase: 'reconnecting',
        reconnectAttempt: action.attempt,
        recoveryReason: action.reason,
      }
    case 'connection_exhausted':
      return {
        ...state,
        phase: 'connection_failed',
        error: action.error,
        recoveryReason: null,
      }
    case 'protocol_error':
      if (state.terminal) return state
      return {
        ...state,
        phase: 'reconnecting',
        recoveryReason: 'protocol_error',
        error: {
          code: 'INVALID_STREAM_EVENT',
          message: '收到不符合 G1 契约的流事件，正在通过任务快照恢复。',
          retryable: true,
        },
      }
    case 'snapshot_received':
      return mergeSnapshot(state, action.snapshot, action.mode)
    case 'memory_job_received':
      return {
        ...state,
        feedbackJobIds: {
          ...state.feedbackJobIds,
          [action.job.feedback_id]: action.job.memory_job_id,
        },
        memoryJobs: {
          ...state.memoryJobs,
          [action.job.memory_job_id]: action.job,
        },
        memoryJobStages: {
          ...state.memoryJobStages,
          [action.job.memory_job_id]: action.job.stage,
        },
        memoryCandidateIds: {
          ...state.memoryCandidateIds,
          [action.job.memory_job_id]: action.job.candidate_ids,
        },
      }
    case 'memory_detail_received': {
      const memoryId = action.detail.card.memory_id
      return {
        ...state,
        memoryDetails: {
          ...state.memoryDetails,
          [memoryId]: action.detail,
        },
        memoryResolvePending: {
          ...state.memoryResolvePending,
          [memoryId]: false,
        },
        memoryResolveErrors: withoutKey(state.memoryResolveErrors, memoryId),
      }
    }
    case 'memory_resolved': {
      const memoryId = action.detail.card.memory_id
      return {
        ...state,
        memoryDetails: {
          ...state.memoryDetails,
          [memoryId]: action.detail,
        },
        memoryResolvePending: {
          ...state.memoryResolvePending,
          [memoryId]: false,
        },
        memoryResolveErrors: withoutKey(state.memoryResolveErrors, memoryId),
        memoryResolveActions: {
          ...state.memoryResolveActions,
          [memoryId]: action.resolution.action,
        },
        memoryDispositions: {
          ...state.memoryDispositions,
          [memoryId]: action.resolution.disposition,
        },
      }
    }
    case 'memory_resolve_started':
      return {
        ...state,
        memoryResolvePending: {
          ...state.memoryResolvePending,
          [action.memoryId]: true,
        },
        memoryResolveErrors: withoutKey(
          state.memoryResolveErrors,
          action.memoryId,
        ),
      }
    case 'memory_resolve_failed':
      return {
        ...state,
        memoryResolvePending: {
          ...state.memoryResolvePending,
          [action.memoryId]: false,
        },
        memoryResolveErrors: {
          ...state.memoryResolveErrors,
          [action.memoryId]: action.error,
        },
      }
    case 'memory_evidence_toggled':
      return {
        ...state,
        openEvidenceMemoryId:
          state.openEvidenceMemoryId === action.memoryId
            ? null
            : action.memoryId,
      }
    case 'sse_event':
      return reduceSseEvent(state, action.event)
  }
}

function reduceSseEvent(state: G0State, event: G0SseEvent): G0State {
  if (event.task_id !== state.taskId || event.run_id !== state.runId) return state

  let next = state
  if (event.event_seq !== null) {
    if (event.event_seq <= state.lastPersistentEventSeq) return state
    if (event.event_seq !== state.lastPersistentEventSeq + 1) {
      return {
        ...state,
        phase: 'reconnecting',
        recoveryReason: 'persistent_gap',
      }
    }
    next = { ...state, lastPersistentEventSeq: event.event_seq }
  }

  switch (event.event_type) {
    case 'task.created':
      return { ...next, runStatus: 'queued' }
    case 'task.stage':
      return {
        ...next,
        phase: event.data.stage === 'failed' ? 'finalizing' : 'streaming',
        runStatus: event.data.stage,
        stages: [
          ...next.stages,
          {
            stage: event.data.stage,
            progressLabel: event.data.progress_label,
            eventSeq: event.event_seq,
            at: event.at,
          },
        ],
      }
    case 'task.fingerprinted':
      return {
        ...next,
        scenario: event.data.domain,
        fingerprintSummary: event.data,
      }
    case 'memory.retrieval.started':
      return { ...next, memoryObserved: true }
    case 'agent.plan.published':
      return { ...next, planCodes: event.data }
    case 'tool.called':
      return {
        ...next,
        toolActivity: {
          toolCallId: event.data.tool_call_id,
          toolName: event.data.tool_name,
          status: 'running',
          reasonCode: event.data.reason_code,
          argsSummary: event.data.args_summary,
          latencyMs: null,
          resultRef: null,
        },
      }
    case 'tool.result':
      return {
        ...next,
        toolActivity: updateToolActivity(next.toolActivity, event),
      }
    case 'agent.chunk': {
      const merged = mergeChunk(next.output, next.endOffset, event.data)
      if (merged.status === 'duplicate') return next
      if (merged.status === 'gap') {
        return {
          ...next,
          phase: 'reconnecting',
          recoveryReason: merged.reason,
        }
      }
      return {
        ...next,
        phase: 'streaming',
        runStatus: 'generating',
        output: merged.output,
        endOffset: merged.endOffset,
      }
    }
    case 'run.metrics':
      return {
        ...next,
        metrics: event.data,
        providerMode: event.data.provider_mode,
      }
    case 'run.completed':
      return { ...next, phase: 'finalizing', runStatus: 'succeeded' }
    case 'run.failed':
      return {
        ...next,
        phase: 'finalizing',
        runStatus: 'failed',
        error: {
          code: event.data.error_code,
          message: 'Agent 运行失败，正在获取最终任务快照。',
          retryable: event.data.retryable,
        },
      }
    case 'error':
      return {
        ...next,
        error: {
          code: event.data.code,
          message: event.data.message,
          retryable: event.data.retryable,
        },
      }
    case 'stream.done':
      return { ...next, phase: 'finalizing' }
    case 'feedback.recorded':
      return {
        ...next,
        lastFeedbackRecorded: event.data,
        feedbackJobIds: {
          ...next.feedbackJobIds,
          [event.data.feedback_id]: event.data.memory_job_id,
        },
      }
    case 'memory.extraction.stage':
      return {
        ...next,
        memoryJobStages: {
          ...next.memoryJobStages,
          [event.data.memory_job_id]: event.data.stage,
        },
      }
    case 'memory.candidate.created': {
      const current = next.memoryCandidateIds[event.data.memory_job_id] ?? []
      const evidence = next.memoryEvidenceIds[event.data.memory_id] ?? []
      return {
        ...next,
        memoryCandidateIds: {
          ...next.memoryCandidateIds,
          [event.data.memory_job_id]: appendUnique(
            current,
            event.data.memory_id,
          ),
        },
        memoryEvidenceIds: {
          ...next.memoryEvidenceIds,
          [event.data.memory_id]: appendUnique(
            evidence,
            event.data.evidence_id,
          ),
        },
      }
    }
    case 'memory.admission.resolved': {
      const detail = next.memoryDetails[event.data.memory_id]
      return {
        ...next,
        memoryDetails: detail
          ? {
              ...next.memoryDetails,
              [event.data.memory_id]: {
                ...detail,
                card: {
                  ...detail.card,
                  status: event.data.new_status,
                  current_version_id: event.data.memory_version_id,
                  version:
                    event.data.memory_version_id === null
                      ? detail.card.version
                      : Math.max(1, detail.card.version),
                },
              },
            }
          : next.memoryDetails,
        memoryDispositions: {
          ...next.memoryDispositions,
          [event.data.memory_id]: event.data.disposition,
        },
      }
    }
    case 'memory.job.failed':
      return {
        ...next,
        memoryJobStages: {
          ...next.memoryJobStages,
          [event.data.memory_job_id]: 'failed',
        },
        memoryJobFailures: {
          ...next.memoryJobFailures,
          [event.data.memory_job_id]: event.data,
        },
      }
  }
}

function mergeSnapshot(
  state: G0State,
  snapshot: TaskSnapshot,
  mode: 'enrichment' | 'recovery' | 'final' | 'restore',
): G0State {
  if (snapshot.task_id !== state.taskId || snapshot.run_id !== state.runId) {
    return state
  }
  const shared = {
    ...state,
    providerMode: snapshot.provider_mode,
    effectiveMemoryMode: snapshot.effective_memory_mode,
    taskText: snapshot.task_text,
    scenario: snapshot.scenario,
    fingerprintSummary: snapshot.fingerprint
      ? {
          fingerprint_id: snapshot.fingerprint.id,
          domain: snapshot.fingerprint.domain,
          classification_source: snapshot.fingerprint.classification_source,
          classification_confidence: snapshot.fingerprint.classification_confidence,
          classification_reasons: snapshot.fingerprint.classification_reasons,
          task_type: snapshot.fingerprint.task_type,
          artifact_type: snapshot.fingerprint.artifact_type,
          language: snapshot.fingerprint.language,
        }
      : state.fingerprintSummary,
    publicPlan: snapshot.public_plan ?? state.publicPlan,
    toolDecision: snapshot.tool_decision ?? state.toolDecision,
    toolCalls: mergeToolCalls(state.toolCalls, snapshot.tool_calls),
    messages: snapshot.messages,
    feedbackEvents: snapshot.feedback_events,
    feedbackJobIds: {
      ...state.feedbackJobIds,
      ...Object.fromEntries(
        snapshot.feedback_events.map((feedback) => [
          feedback.feedback_id,
          feedback.memory_job_id,
        ]),
      ),
    },
  }
  if (mode === 'enrichment') return shared

  const canReplaceOutput = snapshot.end_offset >= state.endOffset
  if (mode === 'recovery' || mode === 'restore') {
    return {
      ...shared,
      phase: 'reconnecting',
      runStatus: snapshot.run_status,
      output: canReplaceOutput ? snapshot.partial_output : state.output,
      endOffset: canReplaceOutput ? snapshot.end_offset : state.endOffset,
      // A TaskSnapshot is materialized state, not an event log. Advancing this
      // cursor would skip persistent events (notably metrics and stream.done)
      // that the snapshot cannot reconstruct.
      lastPersistentEventSeq:
        mode === 'restore'
          ? snapshot.last_persistent_event_seq
          : state.lastPersistentEventSeq,
      error: snapshot.error
        ? {
            code: snapshot.error.code,
            message: snapshot.error.message,
            retryable: snapshot.error.retryable,
          }
        : state.error,
      terminal: false,
      recoveryReason: null,
    }
  }

  const terminalPhase = snapshot.terminal
    ? snapshot.run_status === 'succeeded'
      ? 'succeeded'
      : 'failed'
    : state.phase
  return {
    ...shared,
    phase: terminalPhase,
    runStatus: snapshot.run_status,
    output: canReplaceOutput ? snapshot.partial_output : state.output,
    endOffset: canReplaceOutput ? snapshot.end_offset : state.endOffset,
    lastPersistentEventSeq: Math.max(
      state.lastPersistentEventSeq,
      snapshot.last_persistent_event_seq,
    ),
    error: snapshot.error
      ? {
          code: snapshot.error.code,
          message: snapshot.error.message,
          retryable: snapshot.error.retryable,
        }
      : snapshot.terminal
        ? null
        : state.error,
    terminal: snapshot.terminal,
    recoveryReason: null,
  }
}

function mergeToolCalls(
  current: TaskSnapshot['tool_calls'],
  incoming: TaskSnapshot['tool_calls'],
): TaskSnapshot['tool_calls'] {
  if (incoming.length === 0) return current
  if (current.length === 0) return incoming
  const oldCall = current[0]
  const newCall = incoming[0]
  if (!oldCall || !newCall || oldCall.tool_call_id !== newCall.tool_call_id) {
    return incoming
  }
  const statusRank = { running: 0, succeeded: 1, failed: 1 } as const
  if (statusRank[newCall.status] < statusRank[oldCall.status]) return current
  if (
    statusRank[newCall.status] === statusRank[oldCall.status] &&
    oldCall.result !== null &&
    newCall.result === null
  ) {
    return current
  }
  return incoming
}

function updateToolActivity(
  activity: ToolActivity | null,
  event: ToolResultEvent,
): ToolActivity | null {
  if (!activity || activity.toolCallId !== event.data.tool_call_id) return activity
  return {
    ...activity,
    status: event.data.status,
    latencyMs: event.data.latency_ms,
    resultRef: event.data.result_ref,
  }
}

type ChunkMergeResult =
  | { status: 'applied'; output: string; endOffset: number }
  | { status: 'duplicate' }
  | { status: 'gap'; reason: 'chunk_gap' | 'unsafe_overlap' }

export function mergeChunk(
  currentOutput: string,
  currentEndOffset: number,
  chunk: {
    start_offset: number
    end_offset: number
    delta: string
  },
): ChunkMergeResult {
  const currentBytes = new TextEncoder().encode(currentOutput)
  const chunkBytes = new TextEncoder().encode(chunk.delta)
  if (
    currentBytes.byteLength !== currentEndOffset ||
    chunk.start_offset < 0 ||
    chunk.end_offset !== chunk.start_offset + chunkBytes.byteLength
  ) {
    return { status: 'gap', reason: 'unsafe_overlap' }
  }
  if (chunk.start_offset > currentEndOffset) {
    return { status: 'gap', reason: 'chunk_gap' }
  }
  const overlapEnd = Math.min(chunk.end_offset, currentEndOffset)
  const overlapLength = Math.max(0, overlapEnd - chunk.start_offset)
  if (
    overlapLength > 0 &&
    !bytesEqual(
      currentBytes.slice(chunk.start_offset, overlapEnd),
      chunkBytes.slice(0, overlapLength),
    )
  ) {
    return { status: 'gap', reason: 'unsafe_overlap' }
  }
  if (chunk.end_offset <= currentEndOffset) return { status: 'duplicate' }
  if (chunk.start_offset === currentEndOffset) {
    return {
      status: 'applied',
      output: currentOutput + chunk.delta,
      endOffset: chunk.end_offset,
    }
  }

  const overlapBytes = currentEndOffset - chunk.start_offset
  if (overlapBytes >= chunkBytes.byteLength) return { status: 'duplicate' }
  try {
    const suffix = new TextDecoder('utf-8', { fatal: true }).decode(
      chunkBytes.slice(overlapBytes),
    )
    if (utf8ByteLength(suffix) !== chunk.end_offset - currentEndOffset) {
      return { status: 'gap', reason: 'unsafe_overlap' }
    }
    return {
      status: 'applied',
      output: currentOutput + suffix,
      endOffset: chunk.end_offset,
    }
  } catch {
    return { status: 'gap', reason: 'unsafe_overlap' }
  }
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  return (
    left.byteLength === right.byteLength &&
    left.every((value, index) => value === right[index])
  )
}

function appendUnique<T>(items: readonly T[], item: T): T[] {
  return items.includes(item) ? [...items] : [...items, item]
}

function withoutKey<T>(
  record: Partial<Record<string, T>>,
  key: string,
): Partial<Record<string, T>> {
  const next = { ...record }
  delete next[key]
  return next
}
