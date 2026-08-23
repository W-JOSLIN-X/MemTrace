import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { browserG0Api, G0ApiError, type G0Api } from '../g0/api'
import type { EventSourceFactory } from '../g0/eventStream'
import type {
  G0Phase,
  G0State,
  PublicUiError,
  StageRecord,
} from '../g0/reducer'
import type {
  ClassificationReasonCode,
  DemoAlias,
  FeedbackCreateRequest,
  AllowedMemoryException,
  MemoryDetailResponse,
  MemoryId,
  MemoryJobId,
  MemoryScope,
  ResolveAction,
  ResolveRequest,
  ResolveResponse,
  ResponsePolicy,
  Scenario,
  TaskId,
  ToolCallSnapshot,
} from '../g0/types'
import {
  useG0Agent,
  type FeedbackSubmissionState,
} from '../g0/useG0Agent'

export interface ChatPageProps {
  api?: G0Api
  eventSourceFactory?: EventSourceFactory
  retryDelaysMs?: readonly number[]
  idempotencyKeyFactory?: () => string
  feedbackCatchupTimeoutMs?: number
  memoryMonitorTimeoutMs?: number
}

type SessionPhase = 'loading' | 'ready' | 'switching' | 'failed'

const TASK_ID_PATTERN = /^task_[0-9A-HJKMNP-TV-Z]{26}$/

const stageDefinitions = [
  { key: 'fingerprinting', label: '任务指纹', detail: '识别任务类型与编程语言' },
  { key: 'retrieving', label: '记忆检索', detail: 'Day 3 尚未接入长期记忆检索' },
  { key: 'planning', label: '公开计划', detail: '展示目标与下一步动作' },
  { key: 'tool_running', label: '静态工具', detail: '只解析 Python AST' },
  { key: 'generating', label: '生成回答', detail: '通过 SSE 接收模型正文' },
] as const

const phaseLabels: Record<G0Phase, string> = {
  idle: '等待任务',
  submitting: '正在提交',
  connecting: '正在连接事件流',
  streaming: 'Agent 正在运行',
  reconnecting: '正在恢复连接',
  finalizing: '正在核对最终快照',
  succeeded: '任务完成',
  failed: '任务失败',
  connection_failed: '连接恢复失败',
}

export function ChatPage({
  api,
  eventSourceFactory,
  retryDelaysMs,
  idempotencyKeyFactory,
  feedbackCatchupTimeoutMs,
  memoryMonitorTimeoutMs,
}: ChatPageProps) {
  const resolvedApi = api ?? browserG0Api
  const sessionFeaturesEnabled = Boolean(
    resolvedApi.getSession && resolvedApi.createDemoSession,
  )
  const [taskText, setTaskText] = useState('')
  const [responsePolicy, setResponsePolicy] =
    useState<ResponsePolicy>('default')
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [demoAlias, setDemoAlias] = useState<DemoAlias | null>(
    sessionFeaturesEnabled ? null : 'blank_demo',
  )
  const [sessionPhase, setSessionPhase] = useState<SessionPhase>(
    sessionFeaturesEnabled ? 'loading' : 'ready',
  )
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [feedbackText, setFeedbackText] = useState('')
  const [editedDraft, setEditedDraft] = useState<{
    taskId: TaskId
    value: string
  } | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [acceptedDecision, setAcceptedDecision] = useState<boolean | null>(null)
  const [feedbackFormError, setFeedbackFormError] = useState<string | null>(null)
  const restoredAliasRef = useRef<DemoAlias | null>(null)
  const {
    state,
    feedbackState,
    submitTask,
    restoreTask,
    resetOwner,
    submitFeedback,
    retryMemoryJob,
    resolveCandidate,
    toggleEvidence,
    resumeMemoryJobMonitor,
    retryConnection,
  } = useG0Agent({
    api: resolvedApi,
    eventSourceFactory,
    retryDelaysMs,
    idempotencyKeyFactory,
    feedbackCatchupTimeoutMs,
    memoryMonitorTimeoutMs,
  })
  const editedOutput =
    state.taskId && editedDraft?.taskId === state.taskId
      ? editedDraft.value
      : state.output
  const trimmedScalarLength = useMemo(
    () => [...taskText.trim()].length,
    [taskText],
  )
  const invalidLength = trimmedScalarLength === 0 || trimmedScalarLength > 20000
  const isSubmitting = state.phase === 'submitting'
  const sessionUnavailable = sessionPhase !== 'ready'
  const hasActiveRun =
    state.taskId !== null && !state.terminal && state.phase !== 'connection_failed'

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (invalidLength || isSubmitting || sessionUnavailable) return
    resetFeedbackForm()
    void submitTask(taskText, {
      memoryMode: memoryEnabled ? 'on' : 'off',
      responsePolicy,
    })
  }

  const resetFeedbackForm = useCallback(() => {
    setFeedbackText('')
    setEditedDraft(null)
    setRating(null)
    setAcceptedDecision(null)
    setFeedbackFormError(null)
  }, [])

  useEffect(() => {
    if (!sessionFeaturesEnabled) return
    const getSession = resolvedApi.getSession
    const createDemoSession = resolvedApi.createDemoSession
    if (!getSession || !createDemoSession) return
    const controller = new AbortController()
    let cancelled = false
    const initialize = async () => {
      setSessionPhase('loading')
      setSessionError(null)
      try {
        let session
        try {
          session = await getSession(controller.signal)
        } catch (error) {
          if (!(error instanceof G0ApiError) || error.code !== 'SESSION_REQUIRED') {
            throw error
          }
          session = await createDemoSession('blank_demo', controller.signal)
        }
        if (cancelled) return
        setDemoAlias(session.demo_alias)
        setSessionPhase('ready')
      } catch (error) {
        if (cancelled || isAbortError(error)) return
        setSessionPhase('failed')
        setSessionError(publicErrorMessage(error, '无法初始化 Demo 会话。'))
      }
    }
    void initialize()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [resolvedApi, sessionFeaturesEnabled])

  useEffect(() => {
    if (
      !sessionFeaturesEnabled ||
      sessionPhase !== 'ready' ||
      demoAlias === null ||
      restoredAliasRef.current === demoAlias
    ) {
      return
    }
    restoredAliasRef.current = demoAlias
    const taskId = readSavedTaskId(demoAlias)
    if (!taskId) return
    let cancelled = false
    const restore = async () => {
      const snapshot = await restoreTask(taskId)
      if (cancelled) return
      if (!snapshot) {
        clearSavedTask(demoAlias)
        return
      }
      setTaskText(snapshot.task_text)
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [demoAlias, restoreTask, sessionFeaturesEnabled, sessionPhase])

  useEffect(() => {
    if (
      !sessionFeaturesEnabled ||
      sessionPhase !== 'ready' ||
      demoAlias === null ||
      state.taskId === null
    ) {
      return
    }
    saveTaskId(demoAlias, state.taskId)
  }, [demoAlias, sessionFeaturesEnabled, sessionPhase, state.taskId])

  const switchDemoAlias = useCallback(
    async (nextAlias: DemoAlias) => {
      if (
        !sessionFeaturesEnabled ||
        !resolvedApi.createDemoSession ||
        sessionPhase === 'switching' ||
        nextAlias === demoAlias
      ) {
        return
      }
      setSessionPhase('switching')
      setSessionError(null)
      resetOwner()
      resetFeedbackForm()
      setTaskText('')
      clearTaskUrl()
      const controller = new AbortController()
      try {
        const session = await resolvedApi.createDemoSession(
          nextAlias,
          controller.signal,
        )
        restoredAliasRef.current = null
        setDemoAlias(session.demo_alias)
        setSessionPhase('ready')
      } catch (error) {
        if (isAbortError(error)) return
        setSessionPhase('failed')
        setSessionError(publicErrorMessage(error, '切换 Demo 用户失败。'))
      }
    },
    [
      demoAlias,
      resetFeedbackForm,
      resetOwner,
      resolvedApi,
      sessionFeaturesEnabled,
      sessionPhase,
    ],
  )

  const handleFeedbackSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      setFeedbackFormError(null)
      const request: FeedbackCreateRequest = {}
      if (feedbackText.trim()) request.explicit_text = feedbackText.trim()
      if (editedOutput !== state.output) {
        if (!editedOutput.trim()) {
          setFeedbackFormError('修改稿不能为空；如不提交修改稿，请恢复原始输出。')
          return
        }
        request.edited_output = editedOutput
      }
      if (rating !== null) request.rating = rating
      if (acceptedDecision !== null) request.accepted = acceptedDecision
      if (Object.keys(request).length === 0) {
        setFeedbackFormError('请至少填写文字反馈、修改稿、评分或采纳决定中的一项。')
        return
      }
      const result = await submitFeedback(request)
      if (result) {
        setFeedbackText('')
        setRating(null)
        setAcceptedDecision(null)
      }
    },
    [acceptedDecision, editedOutput, feedbackText, rating, state.output, submitFeedback],
  )

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section
        aria-labelledby="chat-title"
        className="overflow-hidden rounded-[2rem] border border-stone-200 bg-white shadow-sm"
      >
        <div className="border-b border-stone-200 bg-[linear-gradient(135deg,#f0fdf4_0%,#fff_56%,#fff7ed_100%)] px-5 py-7 sm:px-8">
          <div className="flex flex-wrap items-center gap-3">
            <ProviderBadge providerMode={state.providerMode} />
            <span
              aria-live="polite"
              className="text-xs font-bold text-slate-500"
            >
              {phaseLabels[state.phase]}
            </span>
            {sessionFeaturesEnabled ? (
              <DemoSessionSwitch
                activeAlias={demoAlias}
                disabled={sessionPhase !== 'ready'}
                onSwitch={(alias) => void switchDemoAlias(alias)}
                phase={sessionPhase}
              />
            ) : null}
          </div>
          <h1
            className="mt-5 max-w-2xl text-3xl font-black leading-tight tracking-tight text-slate-950 sm:text-4xl"
            id="chat-title"
          >
            把编程问题交给 Agent，观察它如何完成任务
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
            任务指纹、公开计划、安全工具和流式回答都会留下可核对的运行轨迹。
          </p>
        </div>

        <div className="p-5 sm:p-8">
          {sessionError ? (
            <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 p-4" role="alert">
              <p className="text-sm font-black text-red-900">Demo 会话不可用</p>
              <p className="mt-1 text-sm text-red-800">{sessionError}</p>
            </div>
          ) : null}
          <form onSubmit={handleSubmit}>
            <label className="text-sm font-black text-slate-800" htmlFor="task-text">
              编程任务
            </label>
            <textarea
              aria-describedby="task-help task-count"
              className="mt-3 min-h-44 w-full resize-y rounded-2xl border border-stone-300 bg-stone-50 px-4 py-4 font-mono text-sm leading-6 text-slate-900 outline-none transition focus:border-emerald-600 focus:bg-white focus:ring-4 focus:ring-emerald-100"
              id="task-text"
              onChange={(event) => setTaskText(event.target.value)}
              placeholder="例如：请检查这段 Python 代码为什么会出现 IndexError……"
              value={taskText}
            />
            <p className="mt-2 text-xs leading-5 text-slate-500" id="task-help">
              提交新任务会安全关闭当前事件流；提交失败不会清空输入。
            </p>

            <div className="mt-4 max-w-sm">
              <label className="text-xs font-black text-slate-700">
                回答方式
                <select
                  className="mt-2 w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-sm font-semibold outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-100"
                  onChange={(event) =>
                    setResponsePolicy(event.target.value as ResponsePolicy)
                  }
                  value={responsePolicy}
                >
                  <option value="default">默认</option>
                  <option value="guided_hint">引导提示</option>
                  <option value="direct_fix">直接修复</option>
                </select>
              </label>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm font-bold text-slate-600">
                <input
                  checked={memoryEnabled}
                  className="size-4 accent-emerald-700"
                  onChange={(event) => setMemoryEnabled(event.target.checked)}
                  type="checkbox"
                />
                允许记忆流程（Day 4 才检索）
              </label>
              <span
                className={
                  trimmedScalarLength > 20000
                    ? 'text-xs font-bold text-red-700'
                    : 'text-xs font-semibold text-slate-500'
                }
                id="task-count"
              >
                {trimmedScalarLength.toLocaleString('zh-CN')} / 20,000 字符
              </span>
            </div>

            <button
              className="mt-5 w-full rounded-xl bg-emerald-700 px-5 py-3 text-sm font-black text-white shadow-sm transition hover:bg-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 sm:w-auto"
              disabled={invalidLength || isSubmitting || sessionUnavailable}
              type="submit"
            >
              {isSubmitting
                ? '正在提交…'
                : hasActiveRun
                  ? '关闭当前流并开始新任务'
                  : '运行 Agent'}
            </button>
          </form>

          {state.error ? (
            <div
              className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-4"
              role="alert"
            >
              <p className="text-sm font-black text-red-900">{state.error.code}</p>
              <p className="mt-1 text-sm leading-6 text-red-800">
                {state.error.message}
              </p>
              {state.phase === 'connection_failed' && state.error.retryable ? (
                <button
                  className="mt-3 rounded-lg bg-red-800 px-3 py-2 text-xs font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2"
                  onClick={retryConnection}
                  type="button"
                >
                  {state.runStatus === 'succeeded' || state.runStatus === 'failed'
                    ? '重新获取最终快照'
                    : '手动重试连接'}
                </button>
              ) : null}
            </div>
          ) : null}

          <RunTimeline state={state} />
          <PlanAndTool state={state} />
          <OutputPanel state={state} />
          <FeedbackPanel
            acceptedDecision={acceptedDecision}
            editedOutput={editedOutput}
            feedbackFormError={feedbackFormError}
            feedbackState={feedbackState}
            feedbackText={feedbackText}
            onAcceptedDecision={setAcceptedDecision}
            onEditedOutput={(value) => {
              if (state.taskId) setEditedDraft({ taskId: state.taskId, value })
            }}
            onFeedbackText={setFeedbackText}
            onRating={setRating}
            onResolve={resolveCandidate}
            onResumeMonitor={resumeMemoryJobMonitor}
            onRetryJob={retryMemoryJob}
            onSubmit={handleFeedbackSubmit}
            onToggleEvidence={toggleEvidence}
            rating={rating}
            state={state}
          />
        </div>
      </section>

      <RunSidebar state={state} />
    </div>
  )
}

function ProviderBadge({ providerMode }: { providerMode: G0State['providerMode'] }) {
  const mode = providerMode ?? 'unknown'
  const label = mode === 'mock' ? 'Mock' : mode === 'real' ? 'Real' : '未连接'
  return (
    <span
      aria-label={`Provider 模式：${label}`}
      className={
        mode === 'real'
          ? 'rounded-full bg-blue-700 px-3 py-1 text-xs font-black text-white'
          : mode === 'mock'
            ? 'rounded-full bg-amber-500 px-3 py-1 text-xs font-black text-amber-950'
            : 'rounded-full bg-slate-200 px-3 py-1 text-xs font-black text-slate-600'
      }
    >
      {label}
    </span>
  )
}

function DemoSessionSwitch({
  activeAlias,
  disabled,
  onSwitch,
  phase,
}: {
  activeAlias: DemoAlias | null
  disabled: boolean
  onSwitch: (alias: DemoAlias) => void
  phase: SessionPhase
}) {
  return (
    <div className="ml-auto flex items-center gap-1 rounded-full border border-stone-200 bg-white/90 p-1" aria-label="Demo 用户">
      {(['blank_demo', 'seeded_demo'] as const).map((alias) => (
        <button
          aria-pressed={activeAlias === alias}
          className={
            activeAlias === alias
              ? 'rounded-full bg-slate-900 px-3 py-1.5 text-xs font-black text-white'
              : 'rounded-full px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-stone-100'
          }
          disabled={disabled}
          key={alias}
          onClick={() => onSwitch(alias)}
          type="button"
        >
          {alias === 'blank_demo' ? '空白用户' : '种子用户'}
        </button>
      ))}
      {phase === 'loading' || phase === 'switching' ? (
        <span className="px-2 text-xs font-bold text-slate-500">
          {phase === 'loading' ? '初始化…' : '切换…'}
        </span>
      ) : null}
    </div>
  )
}

function RunTimeline({ state }: { state: G0State }) {
  const completedStages = new Map(
    state.stages.map((stage) => [stage.stage, stage] as const),
  )
  const lastOperationalStage = [...state.stages]
    .reverse()
    .find((record) =>
      stageDefinitions.some((definition) => definition.key === record.stage),
    )?.stage
  return (
    <section className="mt-8 border-t border-stone-200 pt-6" aria-labelledby="trace-title">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-black text-slate-900" id="trace-title">
          运行轨迹
        </h2>
        <span className="text-xs font-bold text-slate-400">
          {state.reconnectAttempt > 0 ? `第 ${state.reconnectAttempt} 次恢复` : phaseLabels[state.phase]}
        </span>
      </div>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2">
        {stageDefinitions.map((definition, index) => {
          const record = completedStages.get(definition.key)
          const status = timelineStatus(
            state,
            definition.key,
            record !== undefined,
            lastOperationalStage,
          )
          return (
            <li className={timelineClassName(status)} key={definition.key}>
              <div className="flex items-start gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-white text-xs font-black text-slate-500 shadow-sm ring-1 ring-stone-200">
                  {timelineMarker(status, index)}
                </span>
                <div>
                  <h3 className="text-sm font-black text-slate-700">
                    {definition.label}
                  </h3>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    {stageDescription(state, definition.key, status, definition.detail)}
                  </p>
                </div>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

type TimelineKey = (typeof stageDefinitions)[number]['key']
type TimelineStatus = 'pending' | 'current' | 'completed' | 'skipped' | 'failed'

function timelineClassName(status: TimelineStatus) {
  const classes: Record<TimelineStatus, string> = {
    completed: 'rounded-2xl border border-emerald-200 bg-emerald-50 p-4',
    skipped: 'rounded-2xl border border-amber-200 bg-amber-50 p-4',
    failed: 'rounded-2xl border border-red-200 bg-red-50 p-4',
    current: 'rounded-2xl border border-blue-200 bg-blue-50 p-4',
    pending:
      'rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-4',
  }
  return classes[status]
}

function timelineMarker(status: TimelineStatus, index: number) {
  if (status === 'completed') return '✓'
  if (status === 'skipped') return '–'
  if (status === 'failed') return '!'
  return index + 1
}

function timelineStatus(
  state: G0State,
  key: TimelineKey,
  hasRecord: boolean,
  lastOperationalStage: StageRecord['stage'] | undefined,
): TimelineStatus {
  const toolSkipped = key === 'tool_running' && state.toolDecision?.action === 'skip'
  if (state.runStatus === 'failed' && key === lastOperationalStage) return 'failed'
  if (state.terminal && state.runStatus === 'succeeded') {
    if (toolSkipped) return 'skipped'
    return hasRecord ? 'completed' : 'pending'
  }
  if (toolSkipped && (state.runStatus === 'generating' || state.terminal)) {
    return 'skipped'
  }
  if (state.runStatus === key) return 'current'
  return hasRecord ? 'completed' : 'pending'
}

function stageDescription(
  state: G0State,
  key: TimelineKey,
  status: TimelineStatus,
  fallback: string,
) {
  if (status === 'skipped') {
    return state.toolDecision?.reason ?? '当前任务不需要调用 Python AST 工具'
  }
  if (status === 'failed') return '运行在此阶段失败'
  const currentLabels: Record<TimelineKey, string> = {
    fingerprinting: '正在生成确定性任务指纹',
    retrieving: '正在检索候选记忆',
    planning: '正在发布公开计划',
    tool_running: '白名单静态工具正在运行',
    generating: '正在接收模型回答',
  }
  const completedLabels: Record<TimelineKey, string> = {
    fingerprinting: '确定性任务指纹已生成',
    retrieving: '检索完成：Day 3 尚未接入长期记忆检索',
    planning: '公开计划已发布',
    tool_running: 'Python AST 静态检查已完成',
    generating: '模型回答已接收',
  }
  if (status === 'current') return currentLabels[key]
  if (status === 'completed') return completedLabels[key]
  return fallback
}

function PlanAndTool({ state }: { state: G0State }) {
  if (!state.publicPlan && !state.toolDecision && !state.toolActivity) return null
  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-2">
      <section className="rounded-3xl border border-stone-200 bg-stone-50 p-5" aria-labelledby="plan-title">
        <p className="text-xs font-black uppercase tracking-[0.18em] text-emerald-700">
          Public plan
        </p>
        <h2 className="mt-2 text-base font-black text-slate-900" id="plan-title">
          公开计划
        </h2>
        {state.publicPlan ? (
          <dl className="mt-4 space-y-3 text-sm">
            <PlanRow label="目标" value={state.publicPlan.goal} />
            <PlanRow label="记忆" value={state.publicPlan.memory_summary} />
            <PlanRow label="下一步" value={state.publicPlan.next_action} />
          </dl>
        ) : (
          <p className="mt-3 text-sm text-slate-500">正在读取公开计划快照…</p>
        )}
      </section>

      <ToolPanel state={state} />
    </div>
  )
}

function PlanRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-black text-slate-500">{label}</dt>
      <dd className="mt-1 leading-6 text-slate-800">{value}</dd>
    </div>
  )
}

function ToolPanel({ state }: { state: G0State }) {
  const call = state.toolCalls[0]
  const skipped = state.toolDecision?.action === 'skip'
  return (
    <section className="rounded-3xl border border-stone-200 bg-stone-50 p-5" aria-labelledby="tool-title">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-blue-700">
        Safe tool
      </p>
      <h2 className="mt-2 text-base font-black text-slate-900" id="tool-title">
        {skipped ? '静态工具已跳过' : 'Python AST 静态检查'}
      </h2>
      {state.toolDecision ? (
        <p className="mt-3 text-sm leading-6 text-slate-600">
          {state.toolDecision.reason}
        </p>
      ) : state.toolActivity ? (
        <p className="mt-3 text-sm leading-6 text-slate-600">
          检测到 Python 代码，仅进行语法树解析，不执行代码。
        </p>
      ) : null}
      {state.toolActivity ? (
        <p className="mt-3 text-xs font-bold text-slate-500">
          安全输入摘要：{state.toolActivity.argsSummary.code_bytes.toLocaleString('zh-CN')} bytes
        </p>
      ) : null}
      {call ? <ToolResult call={call} /> : null}
    </section>
  )
}

function ToolResult({ call }: { call: ToolCallSnapshot }) {
  if (call.status === 'running') {
    return <p className="mt-4 text-sm font-bold text-blue-700">正在静态解析…</p>
  }
  if (call.status === 'failed') {
    return <p className="mt-4 text-sm font-bold text-red-700">工具调用失败</p>
  }
  if (!call.result) return null
  if (call.result.valid) {
    return <p className="mt-4 text-sm font-bold text-emerald-700">Python 语法结构有效</p>
  }
  const syntax = call.result.syntax_error
  return (
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-black">发现语法错误</p>
      <p className="mt-1 break-words">{syntax?.message}</p>
      <p className="mt-1 text-xs font-bold">
        位置：第 {syntax?.line ?? '未知'} 行，第 {syntax?.column ?? '未知'} 列
      </p>
    </div>
  )
}

function OutputPanel({ state }: { state: G0State }) {
  const busy = ['connecting', 'streaming', 'reconnecting', 'finalizing'].includes(
    state.phase,
  )
  if (!state.taskId && !state.output) return null
  return (
    <section className="mt-6 rounded-3xl border border-slate-800 bg-slate-950 p-5 text-slate-100" aria-labelledby="answer-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-black" id="answer-title">
          原始输出（只读）
        </h2>
        <span className="text-xs font-bold text-slate-400">
          {state.endOffset.toLocaleString('zh-CN')} UTF-8 bytes
        </span>
      </div>
      <pre
        aria-label="原始输出"
        aria-busy={busy}
        aria-live="polite"
        className="mt-4 min-h-24 whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-200"
      >
        {state.output || (busy ? '等待模型输出…' : '暂无输出')}
      </pre>
    </section>
  )
}

function FeedbackPanel({
  acceptedDecision,
  editedOutput,
  feedbackFormError,
  feedbackState,
  feedbackText,
  onAcceptedDecision,
  onEditedOutput,
  onFeedbackText,
  onRating,
  onResolve,
  onResumeMonitor,
  onRetryJob,
  onSubmit,
  onToggleEvidence,
  rating,
  state,
}: {
  acceptedDecision: boolean | null
  editedOutput: string
  feedbackFormError: string | null
  feedbackState: FeedbackSubmissionState
  feedbackText: string
  onAcceptedDecision: (value: boolean | null) => void
  onEditedOutput: (value: string) => void
  onFeedbackText: (value: string) => void
  onRating: (value: number | null) => void
  onResolve: (
    memoryId: MemoryId,
    request: ResolveRequest,
  ) => Promise<ResolveResponse | null>
  onResumeMonitor: () => void
  onRetryJob: (memoryJobId: MemoryJobId) => Promise<unknown>
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
  onToggleEvidence: (memoryId: MemoryId) => void
  rating: number | null
  state: G0State
}) {
  if (!state.terminal || state.runStatus !== 'succeeded') return null
  const delta = [...editedOutput].length - [...state.output].length
  const submitting = feedbackState.phase === 'submitting'
  return (
    <section className="mt-6 rounded-3xl border border-violet-200 bg-violet-50/60 p-5" aria-labelledby="feedback-title">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-violet-700">
        Post-run feedback
      </p>
      <h2 className="mt-2 text-lg font-black text-slate-950" id="feedback-title">
        修改稿与明确反馈
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        原始输出始终保持只读；下方修改稿会作为单独反馈保存。
      </p>
      <form className="mt-5 space-y-4" onSubmit={onSubmit}>
        <label className="block text-sm font-black text-slate-800">
          修改稿
          <textarea
            aria-label="修改稿"
            className="mt-2 min-h-40 w-full rounded-2xl border border-violet-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none focus:border-violet-600 focus:ring-4 focus:ring-violet-100"
            onChange={(event) => onEditedOutput(event.target.value)}
            value={editedOutput}
          />
        </label>
        <p className="text-xs font-bold text-slate-500">
          相对原始输出字符变化：{delta > 0 ? '+' : ''}{delta.toLocaleString('zh-CN')}
        </p>
        <label className="block text-sm font-black text-slate-800">
          自然语言反馈
          <textarea
            aria-label="自然语言反馈"
            className="mt-2 min-h-24 w-full rounded-2xl border border-violet-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none focus:border-violet-600 focus:ring-4 focus:ring-violet-100"
            onChange={(event) => onFeedbackText(event.target.value)}
            placeholder="例如：以后先提示我检查边界条件。"
            value={feedbackText}
          />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-black text-slate-800">
            评分（1–5）
            <select
              aria-label="评分"
              className="mt-2 w-full rounded-xl border border-violet-200 bg-white px-3 py-2.5 text-sm font-semibold"
              onChange={(event) =>
                onRating(event.target.value ? Number(event.target.value) : null)
              }
              value={rating ?? ''}
            >
              <option value="">暂不评分</option>
              {[1, 2, 3, 4, 5].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend className="text-sm font-black text-slate-800">采纳决定</legend>
            <div className="mt-2 flex gap-2">
              <button
                aria-pressed={acceptedDecision === true}
                className={decisionButtonClass(acceptedDecision === true)}
                onClick={() =>
                  onAcceptedDecision(acceptedDecision === true ? null : true)
                }
                type="button"
              >
                采纳
              </button>
              <button
                aria-pressed={acceptedDecision === false}
                className={decisionButtonClass(acceptedDecision === false)}
                onClick={() =>
                  onAcceptedDecision(acceptedDecision === false ? null : false)
                }
                type="button"
              >
                拒绝
              </button>
            </div>
          </fieldset>
        </div>
        {feedbackFormError || feedbackState.error ? (
          <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-800" role="alert">
            {feedbackFormError ?? feedbackState.error?.message}
          </p>
        ) : null}
        {feedbackState.phase === 'recorded' ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" role="status">
            <p className="font-black">反馈已记录，等待 Day 3 处理</p>
            <p className="mt-1 text-xs font-semibold">
              MemoryJob：{feedbackState.accepted?.memory_job_id} · {feedbackState.job?.stage ?? 'queued'}
            </p>
            {feedbackState.monitor === 'still_processing' ? (
              <div className="mt-3">
                <p className="text-xs font-bold">仍在处理；这不是失败，刷新后也会继续恢复。</p>
                <button
                  className="mt-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-black"
                  onClick={onResumeMonitor}
                  type="button"
                >
                  继续检查
                </button>
              </div>
            ) : null}
            {feedbackState.job?.status === 'failed' ? (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-red-900">
                <p className="text-xs font-black">
                  处理失败：{feedbackState.job.error_code ?? 'MEMORY_JOB_FAILED'}
                </p>
                {feedbackState.job.retryable ? (
                  <button
                    className="mt-2 rounded-lg bg-red-800 px-3 py-2 text-xs font-black text-white"
                    onClick={() => {
                      if (feedbackState.accepted) {
                        void onRetryJob(feedbackState.accepted.memory_job_id)
                      }
                    }}
                    type="button"
                  >
                    重试处理
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
        <button
          className="rounded-xl bg-violet-700 px-5 py-3 text-sm font-black text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          disabled={submitting}
          type="submit"
        >
          {submitting ? '正在记录反馈…' : '提交反馈'}
        </button>
      </form>
      <CandidateTimeline
        feedbackState={feedbackState}
        onResolve={onResolve}
        onToggleEvidence={onToggleEvidence}
        state={state}
      />
      {state.feedbackEvents.length > 0 ? (
        <p className="mt-4 text-xs font-bold text-slate-500">
          当前快照已恢复 {state.feedbackEvents.length.toLocaleString('zh-CN')} 条反馈记录。
        </p>
      ) : null}
    </section>
  )
}

function CandidateTimeline({
  feedbackState,
  onResolve,
  onToggleEvidence,
  state,
}: {
  feedbackState: FeedbackSubmissionState
  onResolve: (
    memoryId: MemoryId,
    request: ResolveRequest,
  ) => Promise<ResolveResponse | null>
  onToggleEvidence: (memoryId: MemoryId) => void
  state: G0State
}) {
  const jobId = feedbackState.accepted?.memory_job_id
  if (!jobId) return null
  const job = feedbackState.job ?? state.memoryJobs[jobId] ?? null
  const candidateIds = job?.candidate_ids ?? state.memoryCandidateIds[jobId] ?? []
  const details = candidateIds
    .map((memoryId) => state.memoryDetails[memoryId])
    .filter((detail): detail is MemoryDetailResponse => detail !== undefined)

  if (job?.status === 'completed' && candidateIds.length === 0) {
    const message =
      job.disposition === 'episode_only'
        ? '仅本次：不会进入长期记忆。'
        : job.disposition === 'reinforce_usage_only'
          ? '本次只更新使用证据，没有创建新候选。'
          : '本次没有形成可复用候选。'
    return (
      <section
        aria-label="候选记忆时间线"
        className="mt-5 rounded-2xl border border-stone-200 bg-white p-4"
      >
        <p className="text-sm font-black text-slate-900">候选处理完成</p>
        <p className="mt-2 text-sm text-slate-600">{message}</p>
      </section>
    )
  }
  if (candidateIds.length === 0) return null

  return (
    <section className="mt-6" aria-labelledby="candidate-timeline-title">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-violet-700">
            G2 candidate timeline
          </p>
          <h3 className="mt-1 text-base font-black text-slate-950" id="candidate-timeline-title">
            该反馈形成的候选记忆
          </h3>
        </div>
        <span className="text-xs font-bold text-slate-500">
          {details.length}/{candidateIds.length} 张详情已恢复
        </span>
      </div>
      <div className="mt-4 space-y-4">
        {candidateIds.map((memoryId) => {
          const detail = state.memoryDetails[memoryId]
          if (!detail) {
            return (
              <div className="rounded-2xl border border-dashed border-violet-200 bg-white p-4 text-sm text-slate-500" key={memoryId}>
                正在读取候选 {memoryId}…
              </div>
            )
          }
          return (
            <CandidateCard
              detail={detail}
              disposition={state.memoryDispositions[memoryId] ?? null}
              evidenceOpen={state.openEvidenceMemoryId === memoryId}
              key={memoryId}
              onResolve={onResolve}
              onToggleEvidence={() => onToggleEvidence(memoryId)}
              pending={state.memoryResolvePending[memoryId] === true}
              resolveAction={state.memoryResolveActions[memoryId] ?? null}
              resolveError={state.memoryResolveErrors[memoryId] ?? null}
            />
          )
        })}
      </div>
    </section>
  )
}

interface CandidateDraft {
  title: string
  rule: string
  avoid: string
  scope: MemoryScope
  exceptions: AllowedMemoryException[]
}

function CandidateCard({
  detail,
  disposition,
  evidenceOpen,
  onResolve,
  onToggleEvidence,
  pending,
  resolveAction,
  resolveError,
}: {
  detail: MemoryDetailResponse
  disposition: G0State['memoryDispositions'][MemoryId] | null
  evidenceOpen: boolean
  onResolve: (
    memoryId: MemoryId,
    request: ResolveRequest,
  ) => Promise<ResolveResponse | null>
  onToggleEvidence: () => void
  pending: boolean
  resolveAction: ResolveAction | null
  resolveError: PublicUiError | null
}) {
  const { card } = detail
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<CandidateDraft>(() => cardDraft(card))
  const isEditing = editing && card.status === 'candidate'

  const resolve = async (action: ResolveAction) => {
    const request: ResolveRequest =
      action === 'edit_accept'
        ? {
            action,
            patch: {
              title: draft.title,
              rule: draft.rule,
              avoid: draft.avoid,
              scope: draft.scope,
              exceptions: draft.exceptions,
            },
          }
        : { action, patch: null }
    const result = await onResolve(card.memory_id, request)
    if (result) setEditing(false)
  }

  return (
    <article className="rounded-3xl border border-violet-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-black text-violet-800">
            {memoryStatusLabel(card.status)}
          </span>
          <span className="ml-2 rounded-full bg-stone-100 px-3 py-1 text-xs font-bold text-slate-600">
            {memoryKindLabel(card.kind)}
          </span>
        </div>
        <span className="text-xs font-bold text-slate-400">{card.memory_id}</span>
      </div>

      {isEditing ? (
        <CandidateEditor draft={draft} onChange={setDraft} />
      ) : (
        <MemoryCardSummary detail={detail} />
      )}

      <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs font-bold leading-5 text-amber-900">
        {memoryStatusMessage(card.status, resolveAction, disposition)}
      </p>

      {resolveError ? (
        <p className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-800" role="alert">
          {resolveError.message} 修改稿已保留，可重试同一操作。
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs font-black text-slate-700"
          onClick={onToggleEvidence}
          type="button"
        >
          {evidenceOpen ? '收起证据' : `查看证据（${card.evidence_count}）`}
        </button>
        {card.status === 'candidate' ? (
          <>
            <button
              className="rounded-xl bg-emerald-700 px-3 py-2 text-xs font-black text-white disabled:bg-slate-300"
              disabled={pending}
              onClick={() => void resolve('accept')}
              type="button"
            >
              确认
            </button>
            <button
              aria-pressed={isEditing}
              className="rounded-xl bg-violet-700 px-3 py-2 text-xs font-black text-white disabled:bg-slate-300"
              disabled={pending}
              onClick={() => {
                if (isEditing) void resolve('edit_accept')
                else setEditing(true)
              }}
              type="button"
            >
              {isEditing ? '编辑后确认' : '编辑'}
            </button>
            <button
              className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-black text-red-800 disabled:bg-slate-100"
              disabled={pending}
              onClick={() => void resolve('reject')}
              type="button"
            >
              拒绝候选
            </button>
            <button
              className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-black text-amber-900 disabled:bg-slate-100"
              disabled={pending}
              onClick={() => void resolve('one_shot')}
              type="button"
            >
              仅本次
            </button>
          </>
        ) : null}
        {pending ? (
          <span className="self-center text-xs font-bold text-slate-500">正在提交决定…</span>
        ) : null}
      </div>

      {evidenceOpen ? <EvidenceDrawer detail={detail} /> : null}
    </article>
  )
}

function MemoryCardSummary({ detail }: { detail: MemoryDetailResponse }) {
  const { card } = detail
  return (
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
      <MemoryField label="标题" value={card.title} />
      <MemoryField label="来源" value={card.source_type} />
      <div className="sm:col-span-2">
        <MemoryField label="规则" value={card.rule} />
      </div>
      <MemoryField label="避免" value={card.avoid || '无'} />
      <MemoryField label="触发" value={card.trigger_text || '无'} />
      <MemoryField
        label="范围"
        value={`${card.scope.level} / ${card.scope.domain}`}
      />
      <MemoryField
        label="证据"
        value={`${card.source_type} · ${card.evidence_count} 条`}
      />
    </dl>
  )
}

function MemoryField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-black text-slate-500">{label}</dt>
      <dd className="mt-1 break-words leading-6 text-slate-800">{value}</dd>
    </div>
  )
}

function CandidateEditor({
  draft,
  onChange,
}: {
  draft: CandidateDraft
  onChange: (draft: CandidateDraft) => void
}) {
  const updateScope = <K extends keyof MemoryScope>(
    key: K,
    value: MemoryScope[K],
  ) => onChange({ ...draft, scope: { ...draft.scope, [key]: value } })
  const toggleException = (value: AllowedMemoryException) => {
    onChange({
      ...draft,
      exceptions: draft.exceptions.includes(value)
        ? draft.exceptions.filter((item) => item !== value)
        : [...draft.exceptions, value],
    })
  }
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      <label className="text-xs font-black text-slate-700">
        标题
        <input
          aria-label="候选标题"
          className="mt-1 w-full rounded-xl border border-violet-200 px-3 py-2 text-sm"
          maxLength={40}
          minLength={4}
          onChange={(event) => onChange({ ...draft, title: event.target.value })}
          value={draft.title}
        />
      </label>
      <label className="text-xs font-black text-slate-700 sm:col-span-2">
        规则
        <textarea
          aria-label="候选规则"
          className="mt-1 min-h-24 w-full rounded-xl border border-violet-200 px-3 py-2 text-sm"
          maxLength={300}
          minLength={20}
          onChange={(event) => onChange({ ...draft, rule: event.target.value })}
          value={draft.rule}
        />
      </label>
      <label className="text-xs font-black text-slate-700 sm:col-span-2">
        避免（允许清空）
        <textarea
          aria-label="候选避免项"
          className="mt-1 min-h-16 w-full rounded-xl border border-violet-200 px-3 py-2 text-sm"
          maxLength={400}
          onChange={(event) => onChange({ ...draft, avoid: event.target.value })}
          value={draft.avoid}
        />
      </label>
      <ScopeSelect
        label="范围级别"
        onChange={(value) => updateScope('level', value as MemoryScope['level'])}
        options={['session', 'task_family', 'project', 'global']}
        value={draft.scope.level}
      />
      <ScopeSelect
        label="领域"
        onChange={(value) => updateScope('domain', value as MemoryScope['domain'])}
        options={[
          'programming_learning',
          'software_development',
          'general_text',
          'other',
          'any',
        ]}
        value={draft.scope.domain}
      />
      <ScopeSelect
        allowEmpty
        label="任务类型"
        onChange={(value) =>
          updateScope(
            'task_type',
            (value || null) as MemoryScope['task_type'],
          )
        }
        options={[
          'debugging_guidance',
          'code_review',
          'code_explanation',
          'code_generation',
          'environment_configuration',
          'general_question',
          'other',
        ]}
        value={draft.scope.task_type ?? ''}
      />
      <ScopeSelect
        allowEmpty
        label="产物类型"
        onChange={(value) =>
          updateScope(
            'artifact_type',
            (value || null) as MemoryScope['artifact_type'],
          )
        }
        options={['source_code', 'configuration', 'text', 'none', 'other']}
        value={draft.scope.artifact_type ?? ''}
      />
      <ScopeSelect
        allowEmpty
        label="受众"
        onChange={(value) =>
          updateScope('audience', (value || null) as MemoryScope['audience'])
        }
        options={['beginner', 'intermediate', 'advanced', 'unknown']}
        value={draft.scope.audience ?? ''}
      />
      <label className="text-xs font-black text-slate-700">
        项目键
        <input
          aria-label="候选项目键"
          className="mt-1 w-full rounded-xl border border-violet-200 px-3 py-2 text-sm"
          maxLength={128}
          onChange={(event) =>
            updateScope('project_key', event.target.value || null)
          }
          value={draft.scope.project_key ?? ''}
        />
      </label>
      <fieldset className="sm:col-span-2">
        <legend className="text-xs font-black text-slate-700">例外</legend>
        <div className="mt-2 flex flex-wrap gap-3 text-xs font-bold text-slate-600">
          {(
            [
              'response_policy:direct_fix',
              'urgency:urgent',
            ] as AllowedMemoryException[]
          ).map((exception) => (
            <label className="flex items-center gap-2" key={exception}>
              <input
                checked={draft.exceptions.includes(exception)}
                onChange={() => toggleException(exception)}
                type="checkbox"
              />
              {exception}
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  )
}

function ScopeSelect({
  allowEmpty = false,
  label,
  onChange,
  options,
  value,
}: {
  allowEmpty?: boolean
  label: string
  onChange: (value: string) => void
  options: string[]
  value: string
}) {
  return (
    <label className="text-xs font-black text-slate-700">
      {label}
      <select
        aria-label={`候选${label}`}
        className="mt-1 w-full rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {allowEmpty ? <option value="">不限定</option> : null}
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  )
}

function EvidenceDrawer({ detail }: { detail: MemoryDetailResponse }) {
  return (
    <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 p-4" aria-label="证据抽屉">
      <p className="text-sm font-black text-blue-950">证据与修改差异</p>
      {detail.evidence.length === 0 ? (
        <p className="mt-2 text-sm text-blue-900/70">暂无证据投影。</p>
      ) : (
        <ol className="mt-3 space-y-3">
          {detail.evidence.map((evidence) => (
            <li className="rounded-xl bg-white p-3 text-xs leading-5 text-slate-700" key={evidence.evidence_id}>
              <p className="font-black text-slate-900">{evidence.source_type}</p>
              <p className="mt-2 whitespace-pre-wrap break-words">{evidence.evidence_quote}</p>
              <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                <MemoryField label="diff summary" value={evidence.diff_summary ?? '无编辑稿'} />
                <MemoryField
                  label="normalized edit cost"
                  value={
                    evidence.normalized_edit_cost === null
                      ? 'null'
                      : evidence.normalized_edit_cost.toFixed(4)
                  }
                />
                <MemoryField label="task / run" value={`${evidence.task_id ?? 'null'} / ${evidence.run_id ?? 'null'}`} />
                <MemoryField label="feedback / evidence" value={`${evidence.feedback_id ?? 'null'} / ${evidence.evidence_id}`} />
              </dl>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function cardDraft(card: MemoryDetailResponse['card']): CandidateDraft {
  return {
    title: card.title,
    rule: card.rule,
    avoid: card.avoid,
    scope: { ...card.scope },
    exceptions: [...card.exceptions],
  }
}

function memoryKindLabel(kind: MemoryDetailResponse['card']['kind']): string {
  const labels: Record<MemoryDetailResponse['card']['kind'], string> = {
    preference: '偏好',
    constraint: '规则',
    procedure: '流程',
    experience: '经验',
    environment: '环境',
    learning_checkpoint: '学习检查点',
  }
  return labels[kind]
}

function memoryStatusLabel(status: MemoryDetailResponse['card']['status']): string {
  if (status === 'candidate') return '候选'
  if (status === 'active') return '已确认'
  if (status === 'rejected') return '已拒绝'
  return status
}

function memoryStatusMessage(
  status: MemoryDetailResponse['card']['status'],
  action: ResolveAction | null,
  disposition: G0State['memoryDispositions'][MemoryId] | null,
): string {
  if (status === 'candidate') return '候选记忆，尚未生效。'
  if (status === 'active') return '已确认保存，但 Day 4 才接入检索。'
  if (action === 'one_shot' || disposition === 'episode_only') {
    return '仅本次，不进入长期记忆。'
  }
  if (status === 'rejected') return '候选已拒绝，不会进入长期记忆。'
  return '该记忆当前不参与 Day 3 后续生成。'
}

function decisionButtonClass(active: boolean): string {
  return active
    ? 'rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-black text-white'
    : 'rounded-xl border border-violet-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-700'
}

function RunSidebar({ state }: { state: G0State }) {
  return (
    <aside className="space-y-4" aria-label="运行说明与指标">
      <section className="rounded-3xl border border-emerald-100 bg-emerald-50 p-5">
        <p className="text-xs font-black uppercase tracking-[0.2em] text-emerald-700">
          Memory status
        </p>
        <h2 className="mt-3 text-lg font-black text-emerald-950">G2 候选与确认流程</h2>
        <p className="mt-2 text-sm leading-6 text-emerald-900/70">
          {state.effectiveMemoryMode === 'off'
            ? '本次任务已关闭记忆。'
            : 'Day 3 可生成并确认候选；已确认卡片要到 Day 4 才会接入检索。'}
        </p>
      </section>

      {state.fingerprintSummary ? (
        <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-blue-700">
            Auto classification
          </p>
          <h2 className="mt-2 text-sm font-black text-slate-900">系统识别场景</h2>
          <p className="mt-3 text-lg font-black text-slate-950">
            {state.fingerprintSummary.domain === 'other'
              ? '暂未明确识别'
              : domainLabel(state.fingerprintSummary.domain)}
          </p>
          <p className="mt-2 text-xs font-semibold leading-5 text-slate-500">
            规则置信度：{Math.round(state.fingerprintSummary.classification_confidence * 100)}%
            （确定性规则分数，不是统计概率）
          </p>
          {state.fingerprintSummary.classification_confidence < 0.7 ? (
            <p className="mt-2 rounded-xl bg-amber-50 p-3 text-xs font-bold leading-5 text-amber-900">
              低置信提示：当前信号较弱或冲突，系统不会要求你手工选择类别。
            </p>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <InfoChip>{state.fingerprintSummary.task_type}</InfoChip>
            <InfoChip>{state.fingerprintSummary.language}</InfoChip>
            {state.fingerprintSummary.classification_reasons.map((reason) => (
              <InfoChip key={reason}>{reasonLabel(reason)}</InfoChip>
            ))}
          </div>
        </section>
      ) : null}

      <MetricsPanel state={state} />

      <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-black text-slate-900">安全边界</h2>
        <ul className="mt-4 space-y-3 text-sm text-slate-600">
          <BoundaryItem>密钥只保存在服务端</BoundaryItem>
          <BoundaryItem>Python 工具只解析 AST</BoundaryItem>
          <BoundaryItem>不展示模型私有推理</BoundaryItem>
        </ul>
      </section>
    </aside>
  )
}

function MetricsPanel({ state }: { state: G0State }) {
  if (!state.metrics) return null
  const totalTokens =
    state.metrics.prompt_tokens === null || state.metrics.output_tokens === null
      ? null
      : state.metrics.prompt_tokens + state.metrics.output_tokens
  return (
    <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm" aria-labelledby="metrics-title">
      <h2 className="text-sm font-black text-slate-900" id="metrics-title">
        运行指标
      </h2>
      <dl className="mt-4 grid grid-cols-2 gap-3">
        <Metric label="模型" value={state.metrics.model} />
        <Metric
          label="Token"
          value={totalTokens === null ? '供应商未返回' : totalTokens.toLocaleString('zh-CN')}
        />
        <Metric label="首字" value={formatMs(state.metrics.first_token_ms)} />
        <Metric label="总耗时" value={formatMs(state.metrics.total_ms)} />
      </dl>
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-stone-100 p-3">
      <dt className="text-[11px] font-black text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-xs font-black text-slate-800">{value}</dd>
    </div>
  )
}

function formatMs(value: number | null) {
  return value === null ? '不可用' : `${Math.round(value).toLocaleString('zh-CN')} ms`
}

function InfoChip({ children }: { children: string }) {
  return (
    <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-700">
      {children}
    </span>
  )
}

function BoundaryItem({ children }: { children: string }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="mt-1 grid size-4 shrink-0 place-items-center rounded-full bg-emerald-100 text-[10px] font-black text-emerald-800"
      >
        ✓
      </span>
      <span>{children}</span>
    </li>
  )
}

function domainLabel(domain: Scenario): string {
  return {
    programming_learning: '编程学习',
    software_development: '软件开发',
    general_text: '通用文本',
    other: '暂未明确识别',
  }[domain]
}

function reasonLabel(reason: ClassificationReasonCode): string {
  return {
    code_present: '包含代码',
    technical_context: '技术语境',
    debugging_cue: '调试线索',
    learning_cue: '学习线索',
    explanation_intent: '解释意图',
    development_action: '开发动作',
    deployment_cue: '部署线索',
    text_task: '文本任务',
    ambiguous: '信号模糊',
  }[reason]
}

function readSavedTaskId(alias: DemoAlias): TaskId | null {
  const fromUrl = new URL(window.location.href).searchParams.get('task_id')
  if (fromUrl && TASK_ID_PATTERN.test(fromUrl)) return fromUrl as TaskId
  try {
    const fromStorage = window.sessionStorage.getItem(taskStorageKey(alias))
    return fromStorage && TASK_ID_PATTERN.test(fromStorage)
      ? (fromStorage as TaskId)
      : null
  } catch {
    return null
  }
}

function saveTaskId(alias: DemoAlias, taskId: TaskId): void {
  try {
    window.sessionStorage.setItem(taskStorageKey(alias), taskId)
  } catch {
    // URL persistence still provides refresh recovery when storage is blocked.
  }
  const url = new URL(window.location.href)
  url.searchParams.set('task_id', taskId)
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

function clearSavedTask(alias: DemoAlias): void {
  try {
    window.sessionStorage.removeItem(taskStorageKey(alias))
  } catch {
    // Continue clearing the URL when storage is unavailable.
  }
  clearTaskUrl()
}

function clearTaskUrl(): void {
  const url = new URL(window.location.href)
  url.searchParams.delete('task_id')
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

function taskStorageKey(alias: DemoAlias): string {
  return `memtrace.currentTask.${alias}`
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function publicErrorMessage(error: unknown, fallback: string): string {
  return error instanceof G0ApiError ? error.message : fallback
}
