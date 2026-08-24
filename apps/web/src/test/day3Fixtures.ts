import type {
  MemoryCard,
  MemoryDetailResponse,
  MemoryJobResponse,
  ResolveResponse,
} from '../g0/types'
import { AT, REQUEST_ID } from './g0Fixtures'

export const FEEDBACK_ID = 'feedback_01J00000000000000000000001' as const
export const MEMORY_JOB_ID = 'job_01J00000000000000000000001' as const
export const MEMORY_ID = 'mem_01J00000000000000000000001' as const
export const MEMORY_VERSION_ID = 'memver_01J00000000000000000000001' as const
export const EVIDENCE_ID = 'evidence_01J00000000000000000000001' as const

export function makeMemoryJob(
  overrides: Partial<MemoryJobResponse> = {},
): MemoryJobResponse {
  return {
    request_id: REQUEST_ID,
    memory_job_id: MEMORY_JOB_ID,
    feedback_id: FEEDBACK_ID,
    job_type: 'extract_feedback',
    status: 'completed',
    stage: 'done',
    attempt: 1,
    candidate_ids: [MEMORY_ID],
    disposition: 'candidate_created',
    error_code: null,
    retryable: false,
    created_at: AT,
    updated_at: AT,
    ...overrides,
  }
}

export function makeMemoryCard(
  overrides: Partial<MemoryCard> = {},
): MemoryCard {
  return {
    memory_id: MEMORY_ID,
    schema_version: '1.0',
    kind: 'preference',
    title: '先解释边界条件',
    rule: '回答编程问题时，先明确说明输入边界条件，再给出修复步骤。',
    avoid: '',
    trigger_text: '遇到数组或列表边界问题时',
    scope: {
      level: 'task_family',
      domain: 'programming_learning',
      task_type: 'debugging_guidance',
      artifact_type: 'source_code',
      audience: 'beginner',
      project_key: null,
    },
    exceptions: [],
    status: 'candidate',
    rejection_reason: null,
    source_type: 'explicit_feedback',
    save_preselected: false,
    source_trust: 1,
    rule_confidence: null,
    scope_confidence: null,
    evidence_count: 1,
    version: 0,
    current_version_id: null,
    created_at: AT,
    updated_at: AT,
    ...overrides,
  }
}

export function makeMemoryDetail(
  card: MemoryCard = makeMemoryCard(),
): MemoryDetailResponse {
  return {
    request_id: REQUEST_ID,
    card,
    evidence: [
      {
        evidence_id: EVIDENCE_ID,
        source_type: 'explicit_feedback',
        feedback_id: FEEDBACK_ID,
        task_id: 'task_01J00000000000000000000000',
        run_id: 'run_01J00000000000000000000000',
        evidence_quote: '以后先说明边界条件。',
        diff_summary: 'replace=1; insert=2; delete=0',
        normalized_edit_cost: 0.25,
        created_at: AT,
      },
    ],
    versions: [],
  }
}

export function makeResolveResponse(
  action: ResolveResponse['action'] = 'accept',
): ResolveResponse {
  const active = action === 'accept' || action === 'edit_accept'
  const card = makeMemoryCard(
    active
      ? {
          status: 'active',
          version: 1,
          current_version_id: MEMORY_VERSION_ID,
          rule_confidence: 1,
          scope_confidence: 1,
        }
      : {
          status: 'rejected',
          rejection_reason:
            action === 'one_shot' ? 'episode_only' : 'user_rejected',
        },
  )
  return {
    request_id: REQUEST_ID,
    memory_id: MEMORY_ID,
    action,
    old_status: 'candidate',
    new_status: card.status,
    disposition:
      action === 'one_shot'
        ? 'episode_only'
        : action === 'reject'
          ? 'no_memory'
          : 'candidate_created',
    memory_version_id: active ? MEMORY_VERSION_ID : null,
    card,
  }
}
