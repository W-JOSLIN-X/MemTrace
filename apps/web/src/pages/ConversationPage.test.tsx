import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { G0Api } from '../g0/api'
import type { DemoSessionResponse } from '../g0/types'
import { G5ApiError } from '../g5/api'
import type { G5Api } from '../g5/api'
import type {
  ConversationTurnResponse,
  MemoryProjection,
  ReflectionJob,
  ReflectionJobId,
  TaskId,
} from '../g5/types'
import { ConversationPage } from './ConversationPage'

const ID = '01J00000000000000000000001'
const TASK_ID = `task_${ID}` as TaskId
const JOB_ID = `job_${ID}` as ReflectionJobId
const AT = '2026-08-30T12:00:00Z'

afterEach(() => localStorage.clear())

describe('Day 6 conversation-first UI', () => {
  it('runs normal chat, shows background memory as plain text, edits it, and clears old owner state', async () => {
    const user = userEvent.setup()
    let activeAlias: 'blank_demo' | 'seeded_demo' = 'blank_demo'
    let memoryVisible = false
    let memory = makeMemory()
    const api = makeApi({
      listMemories: vi.fn(async () => ({
        schema_version: '2.1.0' as const,
        request_id: 'req-list',
        items: activeAlias === 'blank_demo' && memoryVisible ? [memory] : [],
        next_cursor: null,
      })),
      getReflectionJob: vi.fn(async () => {
        memoryVisible = true
        return makeJob()
      }),
      editMemory: vi.fn(async (_memoryId, request) => {
        memory = {
          ...memory,
          kind: request.kind ?? memory.kind,
          content: request.content ?? memory.content,
          applies_when: request.applies_when ?? memory.applies_when,
          current_version_id: 'memver_01J00000000000000000000002',
          version: 2,
        }
        return memory
      }),
    })
    const sessionApi = makeSessionApi((alias) => {
      activeAlias = alias
    })

    render(
      <ConversationPage api={api} pollIntervalMs={60_000} sessionApi={sessionApi} />,
    )

    const input = await screen.findByLabelText('对话内容')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, '以后请优先用中文回答。')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('好的，我会优先使用中文。')).toBeInTheDocument()
    const literalMemory = await screen.findByText('<img src=x onerror=alert(1)>偏好中文')
    expect(literalMemory).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText('本轮实际 token: 30')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑' }))
    const contentEditor = screen.getByLabelText('内容')
    await user.clear(contentEditor)
    await user.type(contentEditor, '回答时优先使用简体中文')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('回答时优先使用简体中文')).toBeInTheDocument()
    expect(api.editMemory).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: '种子用户' }))
    await waitFor(() => expect(screen.queryByText('好的，我会优先使用中文。')).not.toBeInTheDocument())
    expect(screen.queryByText('回答时优先使用简体中文')).not.toBeInTheDocument()
    expect(screen.getByText(/还没有被持久化的记忆/)).toBeInTheDocument()
  })

  it('keeps the draft and reuses the same turn idempotency key after a network failure', async () => {
    const user = userEvent.setup()
    const keys: string[] = []
    let attempt = 0
    const api = makeApi({
      createTurn: vi.fn(async (_taskId, _content, _mode, key) => {
        keys.push(key)
        attempt += 1
        if (attempt === 1) {
          throw new G5ApiError('网络暂时不可用。', {
            code: 'NETWORK_ERROR',
            retryable: true,
            status: null,
          })
        }
        return makeTurn(null)
      }),
    })

    render(
      <ConversationPage api={api} pollIntervalMs={60_000} sessionApi={makeSessionApi()} />,
    )
    const input = await screen.findByLabelText('对话内容')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, '请记住我偏好简洁回答。')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByText('网络暂时不可用。')).toBeInTheDocument()
    expect(input).toHaveValue('请记住我偏好简洁回答。')

    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByText('好的，我会优先使用中文。')).toBeInTheDocument()
    expect(keys).toHaveLength(2)
    expect(keys[1]).toBe(keys[0])
  })

  it('drains owner memory event pages before returning to interval polling', async () => {
    const afterSeqs: number[] = []
    const listMemories = vi.fn(async () => ({
      schema_version: '2.1.0' as const,
      request_id: 'req-list',
      items: [],
      next_cursor: null,
    }))
    const api = makeApi({
      listMemories,
      getMemoryEvents: vi.fn(async (afterSeq) => {
        afterSeqs.push(afterSeq)
        if (afterSeq === 0) {
          return {
            schema_version: '2.1.0' as const,
            request_id: 'req-events-1',
            items: Array.from({ length: 100 }, (_, index) => makeEvent(index + 1)),
            next_seq: 100,
          }
        }
        return {
          schema_version: '2.1.0' as const,
          request_id: 'req-events-2',
          items: [makeEvent(101)],
          next_seq: 101,
        }
      }),
    })

    render(
      <ConversationPage api={api} pollIntervalMs={60_000} sessionApi={makeSessionApi()} />,
    )

    await waitFor(() => expect(afterSeqs).toEqual([0, 100]))
    expect(listMemories.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('restores the latest persisted decisions and actual usage from the task snapshot', async () => {
    const user = userEvent.setup()
    const turn = makeTurn(null)
    const decision = {
      memory_id: `mem_${ID}` as const,
      applicability: 'applicable' as const,
      reason_code: 'semantic_match' as const,
      confidence: 0.98,
      injected: true,
      estimated_tokens: 12,
      effect: 'applied' as const,
    }
    localStorage.setItem('memtrace:g5:task:blank_demo', TASK_ID)
    const api = makeApi({
      getTask: vi.fn(async () => ({
        schema_version: '2.1.0' as const,
        request_id: 'req-snapshot',
        task_id: TASK_ID,
        memory_mode: 'on' as const,
        provider_mode: 'real' as const,
        model: 'deepseek-v4-flash',
        messages: [turn.user_message, turn.assistant_message],
        last_turn: {
          run_id: turn.run_id,
          turn_index: turn.turn_index,
          reflection_job_id: null,
          memory_decisions: [decision],
          tool_calls: [],
          usage: turn.usage,
        },
        last_event_seq: 1,
        created_at: AT,
        updated_at: AT,
      })),
    })

    render(
      <ConversationPage api={api} pollIntervalMs={60_000} sessionApi={makeSessionApi()} />,
    )

    expect(await screen.findByText('好的，我会优先使用中文。')).toBeInTheDocument()
    expect(screen.getByText('本轮实际 token: 30')).toBeInTheDocument()
    await user.click(screen.getByText('本轮记忆判定（1）'))
    expect(screen.getByText('本轮适用 · 已注入模型上下文 · 回答已遵守')).toBeInTheDocument()
  })
})

function makeApi(overrides: Partial<G5Api> = {}): G5Api {
  const emptyEvents = {
    schema_version: '2.1.0' as const,
    request_id: 'req-events',
    items: [],
    next_seq: 0,
  }
  const base: G5Api = {
    async listTasks() {
      return {
        schema_version: '2.1.0',
        request_id: 'req-tasks',
        items: [],
        next_cursor: null,
      }
    },
    async createTask() {
      return {
      schema_version: '2.1.0',
      request_id: 'req-task',
      task_id: TASK_ID,
      provider_mode: 'real',
      model: 'deepseek-v4-flash',
      memory_mode: 'on',
      created_at: AT,
      }
    },
    async createTurn() {
      return makeTurn(JOB_ID)
    },
    async getTask() {
      return {
      schema_version: '2.1.0',
      request_id: 'req-snapshot',
      task_id: TASK_ID,
      memory_mode: 'on',
      provider_mode: 'real',
      model: 'deepseek-v4-flash',
      messages: [],
      last_turn: null,
      last_event_seq: 0,
      created_at: AT,
      updated_at: AT,
      }
    },
    async listMemories() {
      return {
        schema_version: '2.1.0',
        request_id: 'req-list',
        items: [],
        next_cursor: null,
      }
    },
    async getMemory(memoryId) {
      return {
        schema_version: '2.1.0',
        request_id: 'req-detail',
        memory: { ...makeMemory(), memory_id: memoryId },
        versions: [],
        evidence: [],
      }
    },
    async getMemoryVersionDiff() {
      throw new Error('not used by conversation compatibility tests')
    },
    async getMemoryUsages() {
      return {
        schema_version: '2.1.0',
        request_id: 'req-usages',
        items: [],
        next_cursor: null,
      }
    },
    async getMemoryRelations() {
      return {
        schema_version: '2.1.0',
        request_id: 'req-relations',
        items: [],
        next_cursor: null,
      }
    },
    async restoreMemoryVersion() {
      return makeMemory()
    },
    async listMemoryConflicts() {
      return {
        schema_version: '2.1.0',
        request_id: 'req-conflicts',
        items: [],
        next_cursor: null,
      }
    },
    async getMemoryConflict() {
      throw new Error('not used by conversation compatibility tests')
    },
    async resolveMemoryConflict(relationId, request) {
      return {
        schema_version: '2.1.0',
        request_id: 'req-resolve',
        relation_id: relationId as `rel_${string}`,
        action: request.action,
        status: 'resolved',
        resolution_memory_id: null,
      }
    },
    async getTaskEvents() {
      return emptyEvents
    },
    async getMemoryEvents() {
      return emptyEvents
    },
    async getReflectionJob() {
      return makeJob()
    },
    async editMemory() {
      return makeMemory()
    },
    async changeMemory(memoryId, action) {
      return {
        schema_version: '2.1.0',
        request_id: 'req-lifecycle',
        memory_id: memoryId,
        old_status: action === 'resume' ? 'paused' : 'active',
        new_status: action === 'pause' ? 'paused' : 'active',
        updated_at: AT,
      }
    },
    async deleteMemory(memoryId) {
      return {
        schema_version: '2.1.0',
        request_id: 'req-delete-memory',
        memory_id: memoryId,
        status: 'deleted',
        deleted_at: AT,
      }
    },
    async deleteSourceTask(taskId) {
      return {
        schema_version: '2.1.0',
        request_id: 'req-delete-task',
        task_id: taskId,
        status: 'deleted',
        memory_policy: 'preserve_and_mark_evidence_missing',
        affected_memory_count: 0,
      }
    },
    async exportMemoryPack() {
      throw new Error('not used by conversation compatibility tests')
    },
    async previewMemoryPack() {
      throw new Error('not used by conversation compatibility tests')
    },
    async commitMemoryPack() {
      throw new Error('not used by conversation compatibility tests')
    },
    async recordMemoryEffect() {
      return undefined
    },
  }
  return {
    ...base,
    ...overrides,
  }
}

function makeSessionApi(onSwitch?: (alias: 'blank_demo' | 'seeded_demo') => void) {
  const response = (alias: 'blank_demo' | 'seeded_demo'): DemoSessionResponse => ({
    request_id: 'req_01J00000000000000000000001',
    demo_alias: alias,
    expires_at: AT,
  })
  return {
    getSession: vi.fn(async () => response('blank_demo')),
    createDemoSession: vi.fn(async (alias: 'blank_demo' | 'seeded_demo') => {
      onSwitch?.(alias)
      return response(alias)
    }),
  } satisfies Pick<G0Api, 'getSession' | 'createDemoSession'>
}

function makeTurn(reflectionJobId: ReflectionJobId | null): ConversationTurnResponse {
  return {
    schema_version: '2.1.0' as const,
    request_id: 'req-turn',
    task_id: TASK_ID,
    run_id: `run_${ID}` as const,
    turn_index: 1,
    user_message: {
      message_id: `msg_${ID}` as const,
      run_id: `run_${ID}` as const,
      role: 'user' as const,
      content: '以后请优先用中文回答。',
      turn_index: 1,
      created_at: AT,
    },
    assistant_message: {
      message_id: 'msg_01J00000000000000000000002' as const,
      run_id: `run_${ID}` as const,
      role: 'assistant' as const,
      content: '好的，我会优先使用中文。',
      turn_index: 1,
      created_at: AT,
    },
    reflection_job_id: reflectionJobId,
    memory_mode: 'on' as const,
    memory_decisions: [],
    tool_calls: [],
    usage: [
      {
        stage: 'chat' as const,
        provider_mode: 'real' as const,
        model: 'deepseek-v4-flash',
        prompt_hash: `sha256:${'a'.repeat(64)}`,
        input_tokens: 20,
        output_tokens: 10,
        total_tokens: 30,
        reasoning_tokens: null,
        latency_ms: 100,
        first_token_ms: 20,
      },
    ],
  }
}

function makeJob(): ReflectionJob {
  return {
    request_id: 'req-job',
    job_id: JOB_ID,
    task_id: TASK_ID,
    run_id: `run_${ID}` as const,
    turn_index: 1,
    status: 'completed' as const,
    attempt: 1,
    mutation_decision: 'mutate' as const,
    provider_model: 'deepseek-v4-flash',
    schema_version: '2.0' as const,
    error_code: null,
    created_at: AT,
    updated_at: AT,
  }
}

function makeMemory(): MemoryProjection {
  return {
    memory_id: `mem_${ID}`,
    kind: 'preference',
    content: '<img src=x onerror=alert(1)>偏好中文',
    applies_when: '回答一般问题时',
    review_status: 'active',
    confidence: 0.96,
    current_version_id: `memver_${ID}`,
    version: 1,
    source_type: 'conversation_turn',
    retrieved_count: 2,
    injected_count: 1,
    verified_applied_count: 1,
    helpful_count: 1,
    harmful_count: 0,
    stale_count: 0,
    last_used_at: AT,
    created_at: AT,
    updated_at: AT,
  }
}

function makeEvent(eventSeq: number) {
  return {
    event_id: `evt-${eventSeq}`,
    event_seq: eventSeq,
    event_type: 'memory.updated',
    memory_id: null,
    version_id: null,
    old_status: null,
    new_status: null,
    reason_code: null,
    job_id: null,
    created_at: AT,
  }
}
