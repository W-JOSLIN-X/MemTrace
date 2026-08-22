import { describe, expect, it } from 'vitest'

import {
  ContractError,
  parseErrorResponse,
  parseSseEvent,
  parseTaskSnapshot,
} from './runtime'
import type {
  AgentChunkEvent,
  RunMetricsEvent,
  TaskCreatedEvent,
} from './types'
import {
  AT,
  REQUEST_ID,
  RUN_ID,
  TASK_ID,
  makeSnapshot,
} from '../test/g0Fixtures'

describe('G0 runtime contract parser', () => {
  it('requires a persistent wire id equal to data.event_seq', () => {
    const event: TaskCreatedEvent = {
      event_version: '1.0',
      event_type: 'task.created',
      event_seq: 1,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: { task_status: 'active', run_status: 'queued' },
    }

    expect(parseSseEvent('task.created', JSON.stringify(event), '1')).toEqual(
      event,
    )
    expect(() =>
      parseSseEvent('task.created', JSON.stringify(event), '2'),
    ).toThrow(ContractError)
  })

  it('rejects extra reasoning fields instead of exposing them', () => {
    const raw = JSON.stringify({
      event_version: '1.0',
      event_type: 'task.created',
      event_seq: 1,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: {
        task_status: 'active',
        run_status: 'queued',
        reasoning_content: 'private',
      },
    })

    expect(() => parseSseEvent('task.created', raw, '1')).toThrow(
      ContractError,
    )
  })

  it('validates UTF-8 byte offsets while allowing inherited transient ids', () => {
    const event: AgentChunkEvent = {
      event_version: '1.0',
      event_type: 'agent.chunk',
      event_seq: null,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: {
        run_id: RUN_ID,
        chunk_seq: 1,
        start_offset: 0,
        end_offset: 6,
        offset_unit: 'utf8_bytes',
        delta: '你好',
      },
    }
    expect(parseSseEvent('agent.chunk', JSON.stringify(event), '7')).toEqual(
      event,
    )
    event.data.end_offset = 2
    expect(() =>
      parseSseEvent('agent.chunk', JSON.stringify(event), '7'),
    ).toThrow(ContractError)
  })

  it('rejects duplicate fingerprint collection values', () => {
    const snapshot = makeSnapshot({
      fingerprint: {
        id: 'fp_01J00000000000000000000000',
        schema_version: '1.0',
        domain: 'programming_learning',
        task_type: 'debugging_guidance',
        artifact_type: 'source_code',
        audience: 'beginner',
        project_key: null,
        language: 'python',
        framework: null,
        concepts: ['loop', 'loop'],
        tool_context: ['python_ast_check'],
        current_constraints: {
          response_policy: 'default',
          urgency: 'normal',
          memory_disabled: false,
          source: 'ui',
        },
        semantic_query: 'debug a loop',
      },
    })

    expect(() => parseTaskSnapshot(snapshot)).toThrow(ContractError)
  })

  it('rejects a failed terminal snapshot carrying a final message', () => {
    const snapshot = makeSnapshot({
      run_status: 'failed',
      terminal: true,
      final_message: {
        id: 'msg_01J00000000000000000000000',
        role: 'assistant',
        content: '',
        created_at: AT,
      },
      error: {
        error_id: 'err_01J00000000000000000000000',
        code: 'PROVIDER_ERROR',
        message: 'Provider failed.',
        retryable: false,
      },
    })

    expect(() => parseTaskSnapshot(snapshot)).toThrow(ContractError)
  })

  it('enforces schema minLength for public provider and REST error text', () => {
    const metrics: RunMetricsEvent = {
      event_version: '1.0',
      event_type: 'run.metrics',
      event_seq: 1,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: {
        provider: '',
        model: 'mock-deterministic',
        provider_mode: 'mock',
        first_token_ms: 0,
        total_ms: 0,
        prompt_tokens: 0,
        output_tokens: 0,
        token_source: 'mock',
      },
    }
    expect(() =>
      parseSseEvent('run.metrics', JSON.stringify(metrics), '1'),
    ).toThrow(ContractError)

    expect(
      parseErrorResponse({
        error: {
          code: 'INTERNAL_ERROR',
          message: '',
          request_id: REQUEST_ID,
          retryable: false,
          details: {},
        },
      }),
    ).toBeNull()
  })

  it('accepts G1 TaskSnapshot fields and rejects unknown extra fields', () => {
    const validSnapshot = makeSnapshot({
      task_text: 'sample task text',
      scenario: 'programming_learning',
      messages: [
        {
          message_id: 'msg_01J00000000000000000000001',
          run_id: RUN_ID,
          role: 'user',
          content: 'sample task text',
          created_at: AT,
        },
      ],
      feedback_events: [
        {
          feedback_id: 'feedback_01J00000000000000000000001',
          run_id: RUN_ID,
          feedback_type: 'rating',
          explicit_text: null,
          edited_output: null,
          rating: 4,
          accepted: null,
          memory_job_id: 'job_01J00000000000000000000001',
          created_at: AT,
        },
      ],
    })
    const parsed = parseTaskSnapshot(validSnapshot)
    expect(parsed.task_text).toBe('sample task text')
    expect(parsed.messages?.length).toBe(1)
    expect(parsed.feedback_events?.length).toBe(1)

    const withExtra = {
      ...validSnapshot,
      unexpected_field: 'forbidden',
    }
    expect(() => parseTaskSnapshot(withExtra)).toThrow(ContractError)
  })

  it('parses feedback.recorded SSE event correctly', () => {
    const raw = JSON.stringify({
      event_version: '1.0',
      event_type: 'feedback.recorded',
      event_seq: 14,
      task_id: TASK_ID,
      run_id: RUN_ID,
      at: AT,
      data: {
        feedback_id: 'feedback_01J00000000000000000000001',
        memory_job_id: 'job_01J00000000000000000000001',
        feedback_type: 'composite',
      },
    })
    const event = parseSseEvent('feedback.recorded', raw, '14')
    expect(event.event_type).toBe('feedback.recorded')
    expect(event.event_seq).toBe(14)
  })
})
