import { utf8ByteLength } from '../g0/runtime'
import type {
  TaskCreateAccepted,
  TaskSnapshot,
} from '../g0/types'

export const TASK_ID = 'task_01J00000000000000000000000' as const
export const TASK_ID_2 = 'task_01J00000000000000000000001' as const
export const RUN_ID = 'run_01J00000000000000000000000' as const
export const RUN_ID_2 = 'run_01J00000000000000000000001' as const
export const REQUEST_ID = 'req_01J00000000000000000000000' as const
export const MESSAGE_ID = 'msg_01J00000000000000000000000' as const
export const FINGERPRINT_ID = 'fp_01J00000000000000000000000' as const
export const PLAN_ID = 'plan_01J00000000000000000000000' as const
export const TOOL_ID = 'tool_01J00000000000000000000000' as const
export const TOOL_RESULT_ID = 'toolres_01J00000000000000000000000' as const
export const ERROR_ID = 'err_01J00000000000000000000000' as const
export const AT = '2026-08-21T10:00:00Z'

export function makeAccepted(
  overrides: Partial<TaskCreateAccepted> = {},
): TaskCreateAccepted {
  const taskId = overrides.task_id ?? TASK_ID
  return {
    request_id: REQUEST_ID,
    task_id: taskId,
    run_id: RUN_ID,
    events_url: `/api/v1/tasks/${taskId}/events`,
    provider_mode: 'mock',
    effective_memory_mode: 'on',
    ...overrides,
  }
}

export function makeSnapshot(
  overrides: Partial<TaskSnapshot> = {},
): TaskSnapshot {
  const partialOutput = overrides.partial_output ?? ''
  return {
    request_id: REQUEST_ID,
    task_id: TASK_ID,
    run_id: RUN_ID,
    task_text: 'sample task text',
    scenario: 'programming_learning',
    task_status: 'active',
    run_status: 'generating',
    provider_mode: 'mock',
    effective_memory_mode: 'on',
    fingerprint: null,
    public_plan: null,
    tool_decision: null,
    tool_calls: [],
    partial_output: partialOutput,
    end_offset: utf8ByteLength(partialOutput),
    offset_unit: 'utf8_bytes',
    messages: [],
    final_message: null,
    feedback_events: [],
    retrieval_trace: null,
    memory_usages: [],
    error: null,
    terminal: false,
    last_persistent_event_seq: 0,
    updated_at: AT,
    ...overrides,
  }
}
