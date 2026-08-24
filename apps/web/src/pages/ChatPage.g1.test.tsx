import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { G0ApiError, type G0Api } from '../g0/api'
import type {
  EventSourceFactory,
  EventStreamConnection,
  EventStreamHandlers,
} from '../g0/eventStream'
import type {
  DemoAlias,
  FeedbackCreateAccepted,
  FeedbackRecordedEvent,
  G0SseEvent,
  MemoryJobResponse,
  TaskSnapshot,
} from '../g0/types'
import {
  AT,
  RUN_ID,
  TASK_ID,
  makeAccepted,
  makeSnapshot,
} from '../test/g0Fixtures'
import { ChatPage } from './ChatPage'

const FEEDBACK_ID = 'feedback_01J00000000000000000000001' as const
const JOB_ID = 'job_01J00000000000000000000001' as const

class MockEventConnection implements EventStreamConnection {
  closed = false
  private lastEventId = ''

  constructor(
    readonly url: string,
    private readonly handlers: EventStreamHandlers,
  ) {}

  close() {
    this.closed = true
  }

  emit(event: G0SseEvent) {
    if (event.event_seq !== null) this.lastEventId = String(event.event_seq)
    this.handlers.onEvent(
      event.event_type,
      JSON.stringify(event),
      this.lastEventId,
    )
  }
}

function createEventHarness() {
  const connections: MockEventConnection[] = []
  const factory: EventSourceFactory = (url, handlers) => {
    const connection = new MockEventConnection(url, handlers)
    connections.push(connection)
    return connection
  }
  return { connections, factory }
}

function createG1MockApi(snapshot: TaskSnapshot = terminalSnapshot()) {
  const createTask = vi.fn<G0Api['createTask']>()
  const getTask = vi.fn<G0Api['getTask']>()
  const getSession = vi.fn<NonNullable<G0Api['getSession']>>()
  const createDemoSession = vi.fn<NonNullable<G0Api['createDemoSession']>>()
  const createFeedback = vi.fn<NonNullable<G0Api['createFeedback']>>()
  const getMemoryJob = vi.fn<NonNullable<G0Api['getMemoryJob']>>()

  createTask.mockResolvedValue(makeAccepted())
  getTask.mockResolvedValue(snapshot)
  getSession.mockResolvedValue(sessionResponse('blank_demo'))
  createDemoSession.mockImplementation(async (alias) => sessionResponse(alias))
  createFeedback.mockResolvedValue(feedbackAccepted())
  getMemoryJob.mockResolvedValue(memoryJob())

  const api: G0Api = {
    createTask,
    getTask,
    getSession,
    createDemoSession,
    createFeedback,
    getMemoryJob,
  }
  return {
    api,
    createTask,
    getTask,
    getSession,
    createDemoSession,
    createFeedback,
    getMemoryJob,
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('Day 2 G1 owner flow', () => {
  it('creates blank_demo when no cookie exists, then switches users and clears live state', async () => {
    const user = userEvent.setup()
    const { api, createTask, getSession, createDemoSession } = createG1MockApi()
    const { connections, factory } = createEventHarness()
    getSession.mockRejectedValueOnce(
      new G0ApiError('需要有效会话。', {
        code: 'SESSION_REQUIRED',
        retryable: false,
        status: 401,
      }),
    )

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        idempotencyKeyFactory={() => 'task-write-key-0001'}
      />,
    )

    await waitFor(() =>
      expect(screen.getByRole('button', { name: '空白用户' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    expect(createDemoSession).toHaveBeenCalledWith(
      'blank_demo',
      expect.any(AbortSignal),
    )

    await user.type(screen.getByLabelText('编程任务'), '解释数组越界')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    expect(createTask.mock.calls[0]?.[2]).toBe('task-write-key-0001')
    expect(new URL(window.location.href).searchParams.get('task_id')).toBe(TASK_ID)

    await user.click(screen.getByRole('button', { name: '种子用户' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '种子用户' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    expect(connections[0]?.closed).toBe(true)
    expect(screen.getByLabelText('编程任务')).toHaveValue('')
    expect(new URL(window.location.href).searchParams.has('task_id')).toBe(false)
    expect(window.sessionStorage.getItem('memtrace.currentTask.blank_demo')).toBe(
      TASK_ID,
    )
  })

  it('restores a running task from URL before reconnecting at durable cursors', async () => {
    const snapshot = makeSnapshot({
      run_status: 'generating',
      partial_output: '你好',
      end_offset: 6,
      last_persistent_event_seq: 9,
      terminal: false,
      final_message: null,
    })
    const { api, getTask } = createG1MockApi(snapshot)
    const { connections, factory } = createEventHarness()
    window.history.replaceState(null, '', `/?task_id=${TASK_ID}`)

    render(<ChatPage api={api} eventSourceFactory={factory} />)

    await waitFor(() => expect(connections).toHaveLength(1))
    expect(getTask).toHaveBeenCalledWith(TASK_ID, expect.any(AbortSignal))
    expect(connections[0]?.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=9&after_offset=6`,
    )
    expect(screen.getByLabelText('编程任务')).toHaveValue(snapshot.task_text)
    expect(screen.getByLabelText('原始输出')).toHaveTextContent('你好')
  })

  it('renders an ambiguous automatic classification without a manual category control', async () => {
    const { api } = createG1MockApi(lowConfidenceSnapshot())
    window.history.replaceState(null, '', `/?task_id=${TASK_ID}`)

    render(<ChatPage api={api} />)

    expect(await screen.findByText('暂未明确识别')).toBeInTheDocument()
    expect(screen.getByText(/低置信提示/)).toBeInTheDocument()
    expect(screen.getByText(/确定性规则分数，不是统计概率/)).toBeInTheDocument()
    expect(screen.queryByText(/选择场景|使用场景/)).not.toBeInTheDocument()
  })

  it('keeps the original readonly, submits explicit edited feedback, and confirms catch-up', async () => {
    const user = userEvent.setup()
    const { api, createFeedback, getMemoryJob, getTask } = createG1MockApi()
    const { connections, factory } = createEventHarness()
    window.history.replaceState(null, '', `/?task_id=${TASK_ID}`)

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        feedbackCatchupTimeoutMs={5_000}
        idempotencyKeyFactory={() => 'feedback-write-key-0001'}
      />,
    )

    const draft = await screen.findByLabelText('修改稿')
    expect(screen.getByLabelText('原始输出')).toHaveTextContent('你好，世界')
    await user.clear(draft)
    await user.type(draft, '你好，修订版')
    await user.type(screen.getByLabelText('自然语言反馈'), '以后先说明边界条件')
    await user.selectOptions(screen.getByLabelText('评分'), '5')
    await user.click(screen.getByRole('button', { name: '拒绝' }))
    await user.click(screen.getByRole('button', { name: '提交反馈' }))

    await waitFor(() => expect(connections).toHaveLength(1))
    expect(connections[0]?.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=13&after_offset=15`,
    )
    act(() => connections[0]?.emit(feedbackRecorded(14)))

    expect(
      await screen.findByText('反馈已记录，等待 Day 3 处理'),
    ).toBeInTheDocument()
    expect(createFeedback).toHaveBeenCalledWith(
      TASK_ID,
      {
        explicit_text: '以后先说明边界条件',
        edited_output: '你好，修订版',
        rating: 5,
        accepted: false,
      },
      'feedback-write-key-0001',
      expect.any(AbortSignal),
    )
    expect(connections[0]?.closed).toBe(true)
    expect(getTask).toHaveBeenCalledTimes(1)
    expect(getMemoryJob).toHaveBeenCalledWith(JOB_ID, expect.any(AbortSignal))
    expect(screen.getByLabelText('原始输出')).toHaveTextContent('你好，世界')
    expect(screen.getByLabelText('修改稿')).toHaveValue('你好，修订版')
    expect(screen.queryByText(/已经学习|已经记住/)).not.toBeInTheDocument()
  })

  it('preserves failed feedback input and reuses its idempotency key on retry', async () => {
    const user = userEvent.setup()
    const { api, createFeedback, getTask } = createG1MockApi()
    const { factory } = createEventHarness()
    const keyFactory = vi.fn(() => 'feedback-retry-key-0001')
    createFeedback
      .mockRejectedValueOnce(
        new G0ApiError('网络暂时不可用。', {
          code: 'NETWORK_ERROR',
          retryable: true,
          status: null,
        }),
      )
      .mockResolvedValueOnce(feedbackAccepted())
    window.history.replaceState(null, '', `/?task_id=${TASK_ID}`)

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        feedbackCatchupTimeoutMs={0}
        idempotencyKeyFactory={keyFactory}
      />,
    )

    const feedback = await screen.findByLabelText('自然语言反馈')
    await user.type(feedback, '这段输入失败后必须保留')
    await user.click(screen.getByRole('button', { name: '提交反馈' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络暂时不可用。')
    expect(feedback).toHaveValue('这段输入失败后必须保留')

    await user.click(screen.getByRole('button', { name: '提交反馈' }))
    expect(
      await screen.findByText('反馈已记录，等待 Day 3 处理'),
    ).toBeInTheDocument()
    expect(createFeedback).toHaveBeenCalledTimes(2)
    expect(createFeedback.mock.calls[0]?.[2]).toBe('feedback-retry-key-0001')
    expect(createFeedback.mock.calls[1]?.[2]).toBe('feedback-retry-key-0001')
    expect(keyFactory).toHaveBeenCalledTimes(1)
    expect(getTask).toHaveBeenCalledTimes(2)
  })
})

function sessionResponse(alias: DemoAlias) {
  return {
    request_id: 'req_01J00000000000000000000001' as const,
    demo_alias: alias,
    expires_at: '2026-08-23T12:00:00Z',
  }
}

function terminalSnapshot(): TaskSnapshot {
  return makeSnapshot({
    run_status: 'succeeded',
    partial_output: '你好，世界',
    end_offset: 15,
    final_message: {
      id: 'msg_01J00000000000000000000001',
      role: 'assistant',
      content: '你好，世界',
      created_at: AT,
    },
    terminal: true,
    last_persistent_event_seq: 13,
  })
}

function lowConfidenceSnapshot(): TaskSnapshot {
  return makeSnapshot({
    ...terminalSnapshot(),
    scenario: 'other',
    fingerprint: {
      id: 'fp_01J00000000000000000000001',
      schema_version: '1.1',
      domain: 'other',
      classification_source: 'auto_rule_v1',
      classification_confidence: 0.2,
      classification_reasons: ['ambiguous'],
      task_type: 'other',
      artifact_type: 'none',
      audience: 'unknown',
      project_key: null,
      language: 'unknown',
      framework: null,
      concepts: [],
      tool_context: [],
      current_constraints: {
        response_policy: 'default',
        urgency: 'normal',
        memory_disabled: false,
        source: 'ui',
      },
      semantic_query: '帮我处理一下',
    },
  })
}

function feedbackAccepted(): FeedbackCreateAccepted {
  return {
    request_id: 'req_01J00000000000000000000002',
    feedback_id: FEEDBACK_ID,
    memory_job_id: JOB_ID,
    feedback_type: 'composite',
    job_status: 'pending',
  }
}

function memoryJob(): MemoryJobResponse {
  return {
    request_id: 'req_01J00000000000000000000003',
    memory_job_id: JOB_ID,
    feedback_id: FEEDBACK_ID,
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
}

function feedbackRecorded(eventSeq: number): FeedbackRecordedEvent {
  return {
    event_version: '1.0',
    event_type: 'feedback.recorded',
    event_seq: eventSeq,
    task_id: TASK_ID,
    run_id: RUN_ID,
    at: AT,
    data: {
      feedback_id: FEEDBACK_ID,
      memory_job_id: JOB_ID,
      feedback_type: 'composite',
    },
  }
}
