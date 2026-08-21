import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { G0ApiError, type G0Api } from '../g0/api'
import type {
  EventSourceFactory,
  EventStreamConnection,
  EventStreamHandlers,
} from '../g0/eventStream'
import type {
  AgentChunkEvent,
  AgentPlanPublishedEvent,
  ErrorEvent,
  G0SseEvent,
  MemoryRetrievalStartedEvent,
  RunCompletedEvent,
  RunFailedEvent,
  RunMetricsEvent,
  StreamDoneEvent,
  TaskCreatedEvent,
  TaskFingerprintedEvent,
  TaskStageEvent,
  ToolCalledEvent,
  ToolResultEvent,
} from '../g0/types'
import {
  AT,
  ERROR_ID,
  FINGERPRINT_ID,
  MESSAGE_ID,
  PLAN_ID,
  RUN_ID,
  RUN_ID_2,
  TASK_ID,
  TASK_ID_2,
  TOOL_ID,
  TOOL_RESULT_ID,
  makeAccepted,
  makeSnapshot,
} from '../test/g0Fixtures'
import { ChatPage } from './ChatPage'

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

  open() {
    this.handlers.onOpen()
  }

  fail() {
    this.handlers.onError()
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

function createMockApi() {
  const createTask = vi.fn<G0Api['createTask']>()
  const getTask = vi.fn<G0Api['getTask']>()
  const api: G0Api = { createTask, getTask }
  return { api, createTask, getTask }
}

describe('G0 Chat experience', () => {
  it('submits, renders the named-event trace, and still receives metrics after a fast terminal enrichment snapshot', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    const terminalSnapshot = makeTerminalSnapshot()
    getTask.mockResolvedValue(terminalSnapshot)

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        retryDelaysMs={[0, 0]}
      />,
    )
    await user.type(screen.getByLabelText('编程任务'), ' 解释列表越界 ')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))

    await waitFor(() => expect(connections).toHaveLength(1))
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        task_text: '解释列表越界',
        scenario: 'programming_learning',
        memory_mode: 'on',
      }),
      expect.any(AbortSignal),
    )
    expect(connections[0]?.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=0&after_offset=0`,
    )

    const source = connections[0]
    if (!source) throw new Error('missing event source')
    act(() => {
      source.open()
      source.emit(taskCreated(1))
      source.emit(stage(2, 'fingerprinting', 'fingerprinting_task'))
      source.emit(fingerprinted(3))
      source.emit(stage(4, 'retrieving', 'retrieving_memory'))
      source.emit(memoryStarted())
      source.emit(stage(5, 'planning', 'publishing_plan'))
      source.emit(planPublished(6))
    })

    expect(await screen.findByText('检查语法并解释问题')).toBeInTheDocument()
    expect(screen.getByText('正在发布公开计划')).toBeInTheDocument()
    expect(source.closed).toBe(false)

    act(() => {
      source.emit(stage(7, 'tool_running', 'running_static_tool'))
      source.emit(toolCalled(8))
      source.emit(toolResult(9))
      source.emit(stage(10, 'generating', 'generating_answer'))
      source.emit(chunk(1, 0, 6, '你好'))
      source.emit(chunk(2, 6, 15, '，世界'))
      source.emit(metrics(11))
      source.emit(completed(12, 15))
      source.emit(done(13))
    })

    expect(
      await screen.findByText('任务完成', {
        selector: 'span[aria-live="polite"]',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('你好，世界')).toBeInTheDocument()
    expect(screen.getByText('Python 语法结构有效')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByLabelText('Provider 模式：Mock')).toBeInTheDocument()
    expect(screen.getByText('确定性任务指纹已生成')).toBeInTheDocument()
    expect(screen.getByText('Python AST 静态检查已完成')).toBeInTheDocument()
    expect(screen.getByText('模型回答已接收')).toBeInTheDocument()
    expect(screen.queryByText('正在接收模型回答')).not.toBeInTheDocument()
    expect(source.closed).toBe(true)
    expect(getTask).toHaveBeenCalledTimes(3)
  })

  it('manually closes, snapshots, and reconnects with monotonic cursors', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockResolvedValue(
      makeSnapshot({
        partial_output: '你好',
        end_offset: 6,
        last_persistent_event_seq: 9,
      }),
    )

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        retryDelaysMs={[0, 0]}
      />,
    )
    await user.type(screen.getByLabelText('编程任务'), '解释错误')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    const first = connections[0]
    if (!first) throw new Error('missing first connection')
    act(() => {
      first.open()
      first.emit(taskCreated(1))
      first.emit(stage(2, 'generating', 'generating_answer'))
      first.emit(chunk(1, 0, 6, '你好'))
      first.fail()
    })

    await waitFor(() => expect(connections).toHaveLength(2))
    expect(first.closed).toBe(true)
    const second = connections[1]
    if (!second) throw new Error('missing recovered connection')
    expect(second.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=2&after_offset=6`,
    )

    act(() => {
      second.open()
      first.emit(chunk(2, 6, 9, '旧'))
      second.emit(chunk(2, 3, 12, '好世界'))
      second.emit(chunk(2, 3, 12, '好世界'))
    })
    expect(await screen.findByText('你好世界')).toBeInTheDocument()
    expect(screen.queryByText('你好旧')).not.toBeInTheDocument()
  })

  it('shows the explicit reason when the AST tool is skipped', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockResolvedValue(
      makeSnapshot({
        run_status: 'planning',
        public_plan: {
          id: PLAN_ID,
          goal: '回答非 Python 问题',
          memory_summary: 'Day 1 尚无长期记忆',
          next_action: '不调用 AST，直接生成回答',
        },
        tool_decision: {
          action: 'skip',
          tool_name: null,
          reason_code: 'non_python_task',
          reason: '当前任务不是 Python 代码，不调用 AST 工具。',
        },
        last_persistent_event_seq: 2,
      }),
    )
    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    await user.type(screen.getByLabelText('编程任务'), '解释 TypeScript 类型')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    act(() => {
      connections[0]?.open()
      connections[0]?.emit(taskCreated(1))
      connections[0]?.emit(planPublished(2))
    })

    expect(await screen.findByText('静态工具已跳过')).toBeInTheDocument()
    expect(
      screen.getByText('当前任务不是 Python 代码，不调用 AST 工具。'),
    ).toBeInTheDocument()
  })

  it('replays persistent metadata when recovery finds an already-terminal task', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockResolvedValue(makeTerminalSnapshot())

    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        retryDelaysMs={[0]}
      />,
    )
    await user.type(screen.getByLabelText('编程任务'), '快速任务')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))

    act(() => connections[0]?.fail())
    await waitFor(() => expect(connections).toHaveLength(2))
    const recovered = connections[1]
    if (!recovered) throw new Error('missing recovered connection')
    expect(recovered.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=0&after_offset=15`,
    )

    act(() => {
      recovered.open()
      recovered.emit(taskCreated(1))
      recovered.emit(stage(2, 'fingerprinting', 'fingerprinting_task'))
      recovered.emit(fingerprinted(3))
      recovered.emit(stage(4, 'retrieving', 'retrieving_memory'))
      recovered.emit(stage(5, 'planning', 'publishing_plan'))
      recovered.emit(planPublished(6))
      recovered.emit(stage(7, 'tool_running', 'running_static_tool'))
      recovered.emit(toolCalled(8))
      recovered.emit(toolResult(9))
      recovered.emit(stage(10, 'generating', 'generating_answer'))
      recovered.emit(metrics(11))
      recovered.emit(completed(12, 15))
      recovered.emit(done(13))
    })

    expect(
      await screen.findByText('任务完成', {
        selector: 'span[aria-live="polite"]',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('你好，世界')).toBeInTheDocument()
    expect(screen.getByText('mock-deterministic')).toBeInTheDocument()
    expect(recovered.closed).toBe(true)
  })

  it('recovers stream.done when the connection drops after run.completed', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockResolvedValue(makeTerminalSnapshot())
    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    await user.type(screen.getByLabelText('编程任务'), '终态边界断线')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    const first = connections[0]
    if (!first) throw new Error('missing first connection')
    act(() => {
      first.open()
      first.emit(taskCreated(1))
      first.emit(chunk(1, 0, 15, '你好，世界'))
      first.emit(metrics(2))
      first.emit(completed(3, 15))
      first.fail()
    })

    await waitFor(() => expect(connections).toHaveLength(2))
    const second = connections[1]
    if (!second) throw new Error('missing recovery connection')
    expect(second.url).toBe(
      `/api/v1/tasks/${TASK_ID}/events?after_event_seq=3&after_offset=15`,
    )
    act(() => {
      second.open()
      second.emit(done(4))
    })
    expect(
      await screen.findByText('任务完成', {
        selector: 'span[aria-live="polite"]',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('mock-deterministic')).toBeInTheDocument()
    expect(second.closed).toBe(true)
    expect(getTask).toHaveBeenCalledTimes(2)
  })

  it('closes the previous stream and isolates callbacks when a new task starts', async () => {
    const user = userEvent.setup()
    const { api, createTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask
      .mockResolvedValueOnce(makeAccepted())
      .mockResolvedValueOnce(
        makeAccepted({
          task_id: TASK_ID_2,
          run_id: RUN_ID_2,
          events_url: `/api/v1/tasks/${TASK_ID_2}/events`,
        }),
      )

    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    const input = screen.getByLabelText('编程任务')
    await user.type(input, '第一个任务')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    const first = connections[0]
    if (!first) throw new Error('missing first connection')

    await user.clear(input)
    await user.type(input, '第二个任务')
    await user.click(
      screen.getByRole('button', { name: '关闭当前流并开始新任务' }),
    )
    await waitFor(() => expect(connections).toHaveLength(2))
    const second = connections[1]
    if (!second) throw new Error('missing second connection')
    expect(first.closed).toBe(true)

    const currentChunk: AgentChunkEvent = {
      ...chunk(1, 0, 3, '新'),
      task_id: TASK_ID_2,
      run_id: RUN_ID_2,
      data: {
        ...chunk(1, 0, 3, '新').data,
        run_id: RUN_ID_2,
      },
    }
    act(() => {
      first.emit(chunk(1, 0, 3, '旧'))
      second.open()
      second.emit(currentChunk)
    })
    expect(await screen.findByText('新')).toBeInTheDocument()
    expect(screen.queryByText('旧')).not.toBeInTheDocument()
  })

  it('finishes an asynchronous failed run from the authoritative snapshot', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockResolvedValue(makeFailedSnapshot())
    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    const input = screen.getByLabelText('编程任务')
    await user.type(input, '保留失败任务输入')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    const source = connections[0]
    if (!source) throw new Error('missing event source')

    act(() => {
      source.open()
      source.emit(taskCreated(1))
      source.emit(stage(2, 'generating', 'generating_answer'))
      source.emit(chunk(1, 0, 6, '部分'))
      source.emit(metrics(3))
      source.emit(stage(4, 'failed', 'run_failed'))
      source.emit(runFailed(5, 6))
      source.emit(errorEvent(6))
      source.emit(failedDone(7))
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '模型服务暂不可用。',
    )
    expect(input).toHaveValue('保留失败任务输入')
    expect(screen.getByText('部分')).toBeInTheDocument()
    expect(screen.getByText('运行在此阶段失败')).toBeInTheDocument()
    expect(source.closed).toBe(true)
  })

  it('stops after the configured number of recovery attempts', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask.mockRejectedValue(new Error('offline'))
    render(
      <ChatPage
        api={api}
        eventSourceFactory={factory}
        retryDelaysMs={[0, 0]}
      />,
    )
    await user.type(screen.getByLabelText('编程任务'), '恢复上限')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    act(() => connections[0]?.fail())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '流式连接多次恢复失败',
    )
    expect(getTask).toHaveBeenCalledTimes(2)
    expect(connections).toHaveLength(1)
  })

  it('retries the final snapshot directly after terminal metadata was received', async () => {
    const user = userEvent.setup()
    const { api, createTask, getTask } = createMockApi()
    const { connections, factory } = createEventHarness()
    createTask.mockResolvedValue(makeAccepted())
    getTask
      .mockRejectedValueOnce(new Error('snapshot unavailable'))
      .mockRejectedValueOnce(new Error('snapshot unavailable'))
    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    await user.type(screen.getByLabelText('编程任务'), '最终快照重试')
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))
    await waitFor(() => expect(connections).toHaveLength(1))
    const source = connections[0]
    if (!source) throw new Error('missing event source')
    act(() => {
      source.open()
      source.emit(taskCreated(1))
      source.emit(chunk(1, 0, 15, '你好，世界'))
      source.emit(metrics(2))
      source.emit(completed(3, 15))
      source.emit(done(4))
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '最终任务快照暂时不可用',
    )
    getTask.mockResolvedValue(makeTerminalSnapshot())
    await user.click(
      screen.getByRole('button', { name: '重新获取最终快照' }),
    )
    expect(
      await screen.findByText('任务完成', {
        selector: 'span[aria-live="polite"]',
      }),
    ).toBeInTheDocument()
    expect(getTask).toHaveBeenCalledTimes(3)
    expect(connections).toHaveLength(1)
  })

  it('retains input and shows the safe REST error when submission fails', async () => {
    const user = userEvent.setup()
    const { api, createTask } = createMockApi()
    const { factory } = createEventHarness()
    createTask.mockRejectedValue(
      new G0ApiError('模型凭据未配置。', {
        code: 'PROVIDER_CONFIG_MISSING',
        retryable: false,
        status: 503,
      }),
    )
    render(
      <ChatPage api={api} eventSourceFactory={factory} retryDelaysMs={[0]} />,
    )
    const input = screen.getByLabelText('编程任务')
    fireEvent.change(input, { target: { value: '不要清空这段内容' } })
    await user.click(screen.getByRole('button', { name: '运行 Agent' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('模型凭据未配置。')
    expect(input).toHaveValue('不要清空这段内容')
  })
})

function taskCreated(eventSeq: number): TaskCreatedEvent {
  return envelope('task.created', eventSeq, {
    task_status: 'active',
    run_status: 'queued',
  })
}

function stage(
  eventSeq: number,
  value: TaskStageEvent['data']['stage'],
  label: TaskStageEvent['data']['progress_label'],
): TaskStageEvent {
  return envelope('task.stage', eventSeq, { stage: value, progress_label: label })
}

function fingerprinted(eventSeq: number): TaskFingerprintedEvent {
  return envelope('task.fingerprinted', eventSeq, {
    fingerprint_id: FINGERPRINT_ID,
    domain: 'programming_learning',
    task_type: 'debugging_guidance',
    artifact_type: 'source_code',
    language: 'python',
  })
}

function memoryStarted(): MemoryRetrievalStartedEvent {
  return envelope('memory.retrieval.started', null, {
    memory_count: 0,
    summary: 'no_long_term_memory_day1',
  })
}

function planPublished(eventSeq: number): AgentPlanPublishedEvent {
  return envelope('agent.plan.published', eventSeq, {
    plan_id: PLAN_ID,
    goal_code: 'analyze_code',
    memory_summary_code: 'no_long_term_memory_day1',
    next_action_code: 'python_ast_check',
  })
}

function toolCalled(eventSeq: number): ToolCalledEvent {
  return envelope('tool.called', eventSeq, {
    tool_call_id: TOOL_ID,
    tool_name: 'python_ast_check',
    reason_code: 'python_code_detected',
    args_summary: {
      language: 'python',
      code_source: 'fenced_python',
      code_bytes: 48,
    },
  })
}

function toolResult(eventSeq: number): ToolResultEvent {
  return envelope('tool.result', eventSeq, {
    tool_call_id: TOOL_ID,
    tool_name: 'python_ast_check',
    status: 'succeeded',
    latency_ms: 4,
    result_ref: TOOL_RESULT_ID,
  })
}

function chunk(
  chunkSequence: number,
  startOffset: number,
  endOffset: number,
  delta: string,
): AgentChunkEvent {
  return envelope('agent.chunk', null, {
    run_id: RUN_ID,
    chunk_seq: chunkSequence,
    start_offset: startOffset,
    end_offset: endOffset,
    offset_unit: 'utf8_bytes',
    delta,
  })
}

function metrics(eventSeq: number): RunMetricsEvent {
  return envelope('run.metrics', eventSeq, {
    provider: 'mock',
    model: 'mock-deterministic',
    provider_mode: 'mock',
    first_token_ms: 12,
    total_ms: 48,
    prompt_tokens: 10,
    output_tokens: 5,
    token_source: 'mock',
  })
}

function completed(eventSeq: number, endOffset: number): RunCompletedEvent {
  return envelope('run.completed', eventSeq, {
    status: 'succeeded',
    message_id: MESSAGE_ID,
    end_offset: endOffset,
    offset_unit: 'utf8_bytes',
  })
}

function runFailed(eventSeq: number, endOffset: number): RunFailedEvent {
  return envelope('run.failed', eventSeq, {
    status: 'failed',
    error_code: 'PROVIDER_ERROR',
    retryable: true,
    partial_message_id: null,
    end_offset: endOffset,
    offset_unit: 'utf8_bytes',
  })
}

function errorEvent(eventSeq: number): ErrorEvent {
  return envelope('error', eventSeq, {
    error_id: ERROR_ID,
    code: 'PROVIDER_ERROR',
    message: '模型服务暂不可用。',
    retryable: true,
  })
}

function done(eventSeq: number): StreamDoneEvent {
  return envelope('stream.done', eventSeq, {
    status: 'succeeded',
    final_snapshot_required: true,
  })
}

function failedDone(eventSeq: number): StreamDoneEvent {
  return envelope('stream.done', eventSeq, {
    status: 'failed',
    final_snapshot_required: true,
  })
}

function envelope<T extends G0SseEvent>(
  eventType: T['event_type'],
  eventSeq: T['event_seq'],
  data: T['data'],
): T {
  return {
    event_version: '1.0',
    event_type: eventType,
    event_seq: eventSeq,
    task_id: TASK_ID,
    run_id: RUN_ID,
    at: AT,
    data,
  } as unknown as T
}

function makeTerminalSnapshot() {
  return makeSnapshot({
    run_status: 'succeeded',
    fingerprint: {
      id: FINGERPRINT_ID,
      schema_version: '1.0',
      domain: 'programming_learning',
      task_type: 'debugging_guidance',
      artifact_type: 'source_code',
      audience: 'beginner',
      project_key: null,
      language: 'python',
      framework: null,
      concepts: ['list_index'],
      tool_context: ['python_ast_check'],
      current_constraints: {
        response_policy: 'default',
        urgency: 'normal',
        memory_disabled: false,
        source: 'ui',
      },
      semantic_query: 'debug list bounds',
    },
    public_plan: {
      id: PLAN_ID,
      goal: '检查语法并解释问题',
      memory_summary: 'Day 1 尚无长期记忆',
      next_action: '运行 Python AST 静态检查后生成回答',
    },
    tool_decision: {
      action: 'call',
      tool_name: 'python_ast_check',
      reason_code: 'python_code_detected',
      reason: '检测到 Python 代码，仅进行静态语法解析。',
    },
    tool_calls: [
      {
        tool_call_id: TOOL_ID,
        tool_name: 'python_ast_check',
        reason: '检测到 Python 代码，仅进行静态语法解析。',
        args_summary: {
          language: 'python',
          code_source: 'fenced_python',
          code_bytes: 48,
        },
        status: 'succeeded',
        latency_ms: 4,
        result_ref: TOOL_RESULT_ID,
        result: { valid: true, syntax_error: null },
      },
    ],
    partial_output: '你好，世界',
    end_offset: 15,
    final_message: {
      id: MESSAGE_ID,
      role: 'assistant',
      content: '你好，世界',
      created_at: AT,
    },
    terminal: true,
    last_persistent_event_seq: 13,
  })
}

function makeFailedSnapshot() {
  return makeSnapshot({
    run_status: 'failed',
    partial_output: '部分',
    end_offset: 6,
    final_message: null,
    error: {
      error_id: ERROR_ID,
      code: 'PROVIDER_ERROR',
      message: '模型服务暂不可用。',
      retryable: true,
    },
    terminal: true,
    last_persistent_event_seq: 7,
  })
}
