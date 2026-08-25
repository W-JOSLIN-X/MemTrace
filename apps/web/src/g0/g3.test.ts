import { describe, expect, it } from 'vitest'

import { createInitialG0State, g0Reducer } from './reducer'
import { ContractError, parseMemoryVersionList, parseTaskSnapshot } from './runtime'
import type { MemoryUsage, RetrievalTrace } from './types'
import { AT, RUN_ID, TASK_ID, makeAccepted, makeSnapshot } from '../test/g0Fixtures'
import { makeMemoryDetail } from '../test/day3Fixtures'

const TRACE_ID = 'trace_01J00000000000000000000000' as const
const USAGE_ID = 'usage_01J00000000000000000000000' as const
const MEMORY_ID = 'mem_01J00000000000000000000000' as const
const VERSION_ID = 'memver_01J00000000000000000000000' as const

const trace: RetrievalTrace = {
  request_id: 'req_01J00000000000000000000000',
  retrieval_trace_id: TRACE_ID,
  task_id: TASK_ID,
  run_id: RUN_ID,
  retrieval_mode: 'tfidf',
  algorithm_version: 'char_tfidf_v1',
  threshold: 0.68,
  top_k: 3,
  candidate_count: 1,
  retrieved_count: 1,
  selected_count: 1,
  injected_count: 1,
  decisions: [{
    memory_id: MEMORY_ID,
    memory_version_id: VERSION_ID,
    memory_status: 'active',
    retrieved: true,
    selected: true,
    injected: true,
    rank: 1,
    scope_match: 1,
    semantic_similarity: 0.9,
    provenance_confidence: 1,
    verified_effect: 0.5,
    recency: 1,
    final_score: 0.92,
    reason_codes: ['selected_above_threshold'],
  }],
  retrieval_ms: 2,
  memory_chars: 80,
  memory_tokens_estimated: 30,
  provider_prompt_tokens_actual: null,
  prompt_section_hash: 'a'.repeat(64),
  reason_codes: [],
  created_at: AT,
  updated_at: AT,
}

const usage: MemoryUsage = {
  request_id: 'req_01J00000000000000000000000',
  usage_id: USAGE_ID,
  retrieval_trace_id: TRACE_ID,
  task_id: TASK_ID,
  run_id: RUN_ID,
  memory_id: MEMORY_ID,
  memory_version_id: VERSION_ID,
  rank: 1,
  retrieved: true,
  selected: true,
  injected: true,
  estimated_tokens: 30,
  verification_status: 'applied',
  verification_method: 'exact_substring',
  evidence_excerpt: '先检查终止条件',
  user_effect: null,
  created_at: AT,
  updated_at: AT,
}

describe('Day 4 G3 contract and recovery', () => {
  it('strictly parses trace and receipts while rejecting unknown fields', () => {
    const snapshot = makeSnapshot({ retrieval_trace: trace, memory_usages: [usage] })
    expect(parseTaskSnapshot(snapshot).retrieval_trace?.injected_count).toBe(1)
    expect(() => parseTaskSnapshot({ ...snapshot, leaked_body: 'forbidden' })).toThrow(ContractError)
  })

  it('strictly parses the immutable versions endpoint', () => {
    const card = makeMemoryDetail().card
    const version = {
      memory_version_id: VERSION_ID,
      version: 1,
      title: card.title,
      rule: card.rule,
      avoid: card.avoid,
      trigger_text: card.trigger_text,
      scope: card.scope,
      exceptions: card.exceptions,
      created_by_action: 'accept' as const,
      created_at: AT,
    }
    expect(parseMemoryVersionList({
      request_id: 'req_01J00000000000000000000000',
      items: [version],
      next_cursor: null,
    }).items).toEqual([version])
    expect(() => parseMemoryVersionList({
      request_id: 'req_01J00000000000000000000000',
      items: [version],
      next_cursor: null,
      unknown: true,
    })).toThrow(ContractError)
  })

  it('restores trace and receipt state from the authoritative snapshot', () => {
    const accepted = makeAccepted()
    const active = g0Reducer(createInitialG0State(), {
      type: 'task_accepted', accepted, taskText: 'sample task text',
    })
    const restored = g0Reducer(active, {
      type: 'snapshot_received',
      snapshot: makeSnapshot({ retrieval_trace: trace, memory_usages: [usage] }),
      mode: 'restore',
    })
    expect(restored.retrievalTrace).toEqual(trace)
    expect(restored.memoryUsages).toEqual([usage])
  })

  it('updates verification and user effect from persistent events', () => {
    const base = { ...createInitialG0State(), taskId: TASK_ID, runId: RUN_ID, memoryUsages: [{ ...usage, verification_status: 'pending' as const }] }
    const verified = g0Reducer(base, {
      type: 'sse_event',
      event: {
        event_version: '1.0', event_type: 'memory.usage.verified', event_seq: 1,
        task_id: TASK_ID, run_id: RUN_ID, at: AT,
        data: { usage_id: USAGE_ID, memory_id: MEMORY_ID, memory_version_id: VERSION_ID, verification_status: 'violated', verification_method: 'exact_substring', evidence_present: true },
      },
    })
    const effected = g0Reducer(verified, {
      type: 'sse_event',
      event: {
        event_version: '1.0', event_type: 'memory.usage.feedback.recorded', event_seq: 2,
        task_id: TASK_ID, run_id: RUN_ID, at: AT,
        data: { usage_id: USAGE_ID, memory_id: MEMORY_ID, user_effect: 'harmful' },
      },
    })
    expect(effected.memoryUsages[0]?.verification_status).toBe('violated')
    expect(effected.memoryUsages[0]?.user_effect).toBe('harmful')
  })

  it('represents memory-off as an honest zero-count trace', () => {
    const off = { ...trace, candidate_count: 0, retrieved_count: 0, selected_count: 0, injected_count: 0, decisions: [], memory_chars: 0, memory_tokens_estimated: 0, prompt_section_hash: null, reason_codes: ['memory_mode_off' as const] }
    expect(parseTaskSnapshot(makeSnapshot({ effective_memory_mode: 'off', retrieval_trace: off })).retrieval_trace?.reason_codes).toEqual(['memory_mode_off'])
  })

  it('clears trace, receipts, drafts and pending state on owner reset', () => {
    const state = { ...createInitialG0State(), retrievalTrace: trace, memoryUsages: [usage], memoryResolvePending: { [MEMORY_ID]: true } }
    expect(g0Reducer(state, { type: 'owner_reset' })).toEqual(createInitialG0State())
  })
})
