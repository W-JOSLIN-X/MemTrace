import { afterEach, describe, expect, it, vi } from 'vitest'

import { browserG0Api } from './api'
import type { FeedbackCreateAccepted, MemoryJobResponse, MemoryUsage } from './types'
import { AT, TASK_ID, makeAccepted, makeSnapshot } from '../test/g0Fixtures'
import {
  MEMORY_ID,
  makeMemoryDetail,
  makeResolveResponse,
} from '../test/day3Fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('browser G1 API', () => {
  it('sends same-origin credentials on every fetch and distinct write keys', async () => {
    const feedback: FeedbackCreateAccepted = {
      request_id: 'req_01J00000000000000000000002',
      feedback_id: 'feedback_01J00000000000000000000001',
      memory_job_id: 'job_01J00000000000000000000001',
      feedback_type: 'explicit_text',
      job_status: 'pending',
    }
    const job: MemoryJobResponse = {
      request_id: 'req_01J00000000000000000000003',
      memory_job_id: feedback.memory_job_id,
      feedback_id: feedback.feedback_id,
      job_type: 'extract_feedback',
      status: 'pending',
      stage: 'queued',
      attempt: 0,
      candidate_ids: [],
      disposition: null,
      error_code: null,
      retryable: false,
      created_at: AT,
      updated_at: AT,
    }
    const responses = [
      {
        request_id: 'req_01J00000000000000000000001',
        demo_alias: 'blank_demo',
        expires_at: '2026-08-23T12:00:00Z',
      },
      {
        request_id: 'req_01J00000000000000000000004',
        demo_alias: 'seeded_demo',
        expires_at: '2026-08-23T12:00:00Z',
      },
      makeAccepted(),
      makeSnapshot(),
      feedback,
      job,
      job,
      makeResolveResponse(),
      {
        request_id: 'req_01J00000000000000000000000',
        items: [makeMemoryDetail().card],
        next_cursor: null,
      },
      makeMemoryDetail(),
    ]
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse(responses.shift()))
    vi.stubGlobal('fetch', fetchMock)

    await browserG0Api.getSession?.()
    await browserG0Api.createDemoSession?.('seeded_demo')
    await browserG0Api.createTask(
      {
        task_text: '解释列表越界',
        memory_mode: 'on',
        current_constraints: {
          response_policy: 'default',
          urgency: 'normal',
          memory_disabled: false,
          source: 'ui',
        },
      },
      undefined,
      'task-idempotency-key-0001',
    )
    await browserG0Api.getTask(TASK_ID)
    await browserG0Api.createFeedback?.(
      TASK_ID,
      { explicit_text: '以后先说明边界' },
      'feedback-idempotency-key-0001',
    )
    await browserG0Api.getMemoryJob?.(feedback.memory_job_id)
    await browserG0Api.retryMemoryJob?.(
      feedback.memory_job_id,
      'retry-idempotency-key-0001',
    )
    await browserG0Api.resolveMemoryCandidate?.(
      MEMORY_ID,
      { action: 'accept' },
      'resolve-idempotency-key-0001',
    )
    await browserG0Api.listMemories?.({ status: 'candidate' })
    await browserG0Api.getMemory?.(MEMORY_ID)

    expect(fetchMock).toHaveBeenCalledTimes(10)
    for (const call of fetchMock.mock.calls) {
      expect(call[1]?.credentials).toBe('same-origin')
    }
    expect(fetchMock.mock.calls[2]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'task-idempotency-key-0001',
    })
    expect(fetchMock.mock.calls[4]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'feedback-idempotency-key-0001',
    })
    expect(fetchMock.mock.calls[6]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'retry-idempotency-key-0001',
    })
    expect(fetchMock.mock.calls[7]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'resolve-idempotency-key-0001',
    })
    expect(fetchMock.mock.calls[7]?.[1]?.body).toBe(
      JSON.stringify({ action: 'accept', patch: null }),
    )
    expect(String(fetchMock.mock.calls[8]?.[0])).toContain(
      '/api/v1/memories?status=candidate',
    )
  })

  it('reuses the caller-owned idempotency key for a user-effect retry', async () => {
    const usage: MemoryUsage = {
      request_id: 'req_01J00000000000000000000000',
      usage_id: 'usage_01J00000000000000000000000',
      retrieval_trace_id: 'trace_01J00000000000000000000000',
      task_id: TASK_ID,
      run_id: 'run_01J00000000000000000000001',
      memory_id: MEMORY_ID,
      memory_version_id: 'memver_01J00000000000000000000000',
      rank: 1,
      retrieved: true,
      selected: true,
      injected: true,
      estimated_tokens: 30,
      verification_status: 'applied',
      verification_method: 'exact_substring',
      evidence_excerpt: '合成证据',
      user_effect: 'helpful',
      created_at: AT,
      updated_at: AT,
    }
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse(usage))
    vi.stubGlobal('fetch', fetchMock)

    const key = 'effect-idempotency-key-0001'
    await browserG0Api.recordMemoryEffect?.(TASK_ID, MEMORY_ID, 'helpful', key)
    await browserG0Api.recordMemoryEffect?.(TASK_ID, MEMORY_ID, 'helpful', key)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    for (const call of fetchMock.mock.calls) {
      expect(call[1]?.credentials).toBe('same-origin')
      expect(call[1]?.headers).toMatchObject({ 'Idempotency-Key': key })
      expect(call[1]?.body).toBe(JSON.stringify({ effect: 'helpful' }))
    }
  })
})

describe('browser G4 API', () => {
  it('projects lifecycle, deletion, Diff and conflict routes with caller-owned keys', async () => {
    const active = makeMemoryDetail().card
    const relation = {
      relation_id: 'rel_01J00000000000000000000000', from_memory_id: MEMORY_ID,
      to_memory_id: 'mem_01J00000000000000000000002' as const, relation_type: 'conflicts_with',
      status: 'unresolved', resolution_action: null, resolution_memory_id: null,
      created_at: AT, resolved_at: null,
    }
    const responses = [
      makeMemoryDetail(), makeMemoryDetail(), makeMemoryDetail(), makeMemoryDetail(),
      { request_id: 'req_01J00000000000000000000000', memory_id: MEMORY_ID, status: 'deleted', deleted_at: AT },
      { request_id: 'req_01J00000000000000000000000', task_id: TASK_ID, status: 'deleted', memory_policy: 'preserve_and_mark_evidence_missing', affected_card_count: 1 },
      { request_id: 'req_01J00000000000000000000000', items: [relation], next_cursor: null },
      { request_id: 'req_01J00000000000000000000000', relation_id: relation.relation_id, left_memory_id: relation.from_memory_id, right_memory_id: relation.to_memory_id, relation_type: 'conflicts_with', status: 'unresolved' },
      { request_id: 'req_01J00000000000000000000000', relation_id: relation.relation_id, action: 'pause_both', status: 'resolved' },
    ]
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => jsonResponse(responses.shift()))
    vi.stubGlobal('fetch', fetchMock)
    const version = active.current_version_id!
    await browserG0Api.editMemory?.(MEMORY_ID, { expected_current_version_id: version, patch: { rule: 'new' } }, 'g4-edit-key')
    await browserG0Api.pauseMemory?.(MEMORY_ID, version, 'g4-pause-key')
    await browserG0Api.archiveMemory?.(MEMORY_ID, version, 'g4-archive-key')
    await browserG0Api.restoreMemory?.(MEMORY_ID, version, 'g4-restore-key')
    await browserG0Api.deleteMemory?.(MEMORY_ID, version, active.title, 'g4-delete-key')
    await browserG0Api.deleteSourceTask?.(TASK_ID, 'g4-task-delete-key')
    await browserG0Api.listMemoryConflicts?.('unresolved')
    await browserG0Api.detectMemoryConflict?.({ left_memory_id: relation.from_memory_id, left_expected_current_version_id: version, right_memory_id: relation.to_memory_id, right_expected_current_version_id: version }, 'g4-detect-key')
    await browserG0Api.resolveMemoryConflict?.(relation.relation_id, { expected_relation_status: 'unresolved', left_expected_current_version_id: version, right_expected_current_version_id: version, action: 'pause_both' }, 'g4-resolve-key')

    expect(fetchMock).toHaveBeenCalledTimes(9)
    for (const call of fetchMock.mock.calls) expect(call[1]?.credentials).toBe('same-origin')
    expect(fetchMock.mock.calls[4][1]?.method).toBe('DELETE')
    expect(fetchMock.mock.calls[5][1]?.body).toContain('preserve_and_mark_evidence_missing')
    expect(String(fetchMock.mock.calls[6][0])).toContain('status=unresolved')
    expect(fetchMock.mock.calls[8][1]?.headers).toMatchObject({ 'Idempotency-Key': 'g4-resolve-key' })
  })
})

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
