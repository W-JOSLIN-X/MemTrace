import { describe, expect, it } from 'vitest'

import { createInitialG0State, g0Reducer, mergeChunk } from './reducer'
import type { AgentChunkEvent, TaskCreatedEvent, TaskStageEvent } from './types'
import {
  AT,
  RUN_ID,
  RUN_ID_2,
  TASK_ID,
  TASK_ID_2,
  makeAccepted,
  makeSnapshot,
} from '../test/g0Fixtures'

function acceptedState() {
  return g0Reducer(createInitialG0State(), {
    type: 'task_accepted',
    accepted: makeAccepted(),
  })
}

describe('G0 reducer idempotency and byte offsets', () => {
  it('deduplicates persistent event_seq and detects gaps', () => {
    const created: TaskCreatedEvent = {
      event_version: '1.0',
      event_type: 'task.created',
      event_seq: 1,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: { task_status: 'active', run_status: 'queued' },
    }
    const first = g0Reducer(acceptedState(), { type: 'sse_event', event: created })
    expect(first.lastPersistentEventSeq).toBe(1)
    expect(g0Reducer(first, { type: 'sse_event', event: created })).toBe(first)

    const gap: TaskStageEvent = {
      event_version: '1.0',
      event_type: 'task.stage',
      event_seq: 3,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: { stage: 'generating', progress_label: 'generating_answer' },
    }
    const gapState = g0Reducer(first, { type: 'sse_event', event: gap })
    expect(gapState.recoveryReason).toBe('persistent_gap')
    expect(gapState.lastPersistentEventSeq).toBe(1)
  })

  it('merges UTF-8 chunks only when continuous or safely overlapping', () => {
    expect(mergeChunk('', 0, { start_offset: 0, end_offset: 6, delta: '你好' })).toEqual({
      status: 'applied',
      output: '你好',
      endOffset: 6,
    })
    expect(
      mergeChunk('你好', 6, {
        start_offset: 3,
        end_offset: 12,
        delta: '好世界',
      }),
    ).toEqual({ status: 'applied', output: '你好世界', endOffset: 12 })
    expect(
      mergeChunk('你好', 6, { start_offset: 0, end_offset: 6, delta: '你好' }),
    ).toEqual({ status: 'duplicate' })
    expect(
      mergeChunk('你好', 6, { start_offset: 7, end_offset: 10, delta: '界' }),
    ).toEqual({ status: 'gap', reason: 'chunk_gap' })
    expect(
      mergeChunk('你', 3, { start_offset: 2, end_offset: 6, delta: '好a' }),
    ).toEqual({ status: 'gap', reason: 'unsafe_overlap' })
    expect(
      mergeChunk('你好', 6, { start_offset: 0, end_offset: 3, delta: '坏' }),
    ).toEqual({ status: 'gap', reason: 'unsafe_overlap' })
    expect(
      mergeChunk('你好', 6, {
        start_offset: 3,
        end_offset: 12,
        delta: '坏世界',
      }),
    ).toEqual({ status: 'gap', reason: 'unsafe_overlap' })
    expect(
      mergeChunk('😀', 4, { start_offset: 0, end_offset: 7, delta: '😀好' }),
    ).toEqual({ status: 'applied', output: '😀好', endOffset: 7 })
    expect(
      mergeChunk('😀', 4, { start_offset: 1, end_offset: 4, delta: '好' }),
    ).toEqual({ status: 'gap', reason: 'unsafe_overlap' })
  })

  it('ignores events from an old task or run', () => {
    const event: AgentChunkEvent = {
      event_version: '1.0',
      event_type: 'agent.chunk',
      event_seq: null,
      task_id: TASK_ID_2,
      run_id: RUN_ID_2,
      at: AT,
      data: {
        run_id: RUN_ID_2,
        chunk_seq: 1,
        start_offset: 0,
        end_offset: 3,
        offset_unit: 'utf8_bytes',
        delta: '旧',
      },
    }
    const state = acceptedState()
    expect(g0Reducer(state, { type: 'sse_event', event })).toBe(state)
  })

  it('uses monotonic snapshots and keeps enrichment from consuming SSE cursors', () => {
    const state = {
      ...acceptedState(),
      output: '你好',
      endOffset: 6,
      lastPersistentEventSeq: 4,
    }
    const stale = makeSnapshot({
      partial_output: '你',
      end_offset: 3,
      last_persistent_event_seq: 3,
    })
    const recovered = g0Reducer(state, {
      type: 'snapshot_received',
      snapshot: stale,
      mode: 'recovery',
    })
    expect(recovered.output).toBe('你好')
    expect(recovered.endOffset).toBe(6)
    expect(recovered.lastPersistentEventSeq).toBe(4)

    const caughtUp = g0Reducer(state, {
      type: 'snapshot_received',
      snapshot: makeSnapshot({
        run_status: 'succeeded',
        partial_output: '你好世界',
        end_offset: 12,
        final_message: {
          id: 'msg_01J00000000000000000000000',
          role: 'assistant',
          content: '你好世界',
          created_at: AT,
        },
        terminal: true,
        last_persistent_event_seq: 13,
      }),
      mode: 'recovery',
    })
    expect(caughtUp.output).toBe('你好世界')
    expect(caughtUp.endOffset).toBe(12)
    expect(caughtUp.lastPersistentEventSeq).toBe(4)
    expect(caughtUp.terminal).toBe(false)
    expect(caughtUp.phase).toBe('reconnecting')

    const fastTerminal = makeSnapshot({
      run_status: 'succeeded',
      partial_output: '你好世界',
      end_offset: 12,
      final_message: {
        id: 'msg_01J00000000000000000000000',
        role: 'assistant',
        content: '你好世界',
        created_at: AT,
      },
      terminal: true,
      last_persistent_event_seq: 13,
    })
    const enriched = g0Reducer(state, {
      type: 'snapshot_received',
      snapshot: fastTerminal,
      mode: 'enrichment',
    })
    expect(enriched.terminal).toBe(false)
    expect(enriched.lastPersistentEventSeq).toBe(4)
    expect(enriched.output).toBe('你好')
  })
})
