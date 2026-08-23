import { afterEach, describe, expect, it, vi } from 'vitest'

import { browserG0Api } from './api'
import type { FeedbackCreateAccepted, MemoryJobResponse } from './types'
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
})

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
