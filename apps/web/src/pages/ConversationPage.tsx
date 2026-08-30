import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { browserG0Api, G0ApiError } from '../g0/api'
import type { G0Api } from '../g0/api'
import type { DemoAlias } from '../g0/types'
import { browserG5Api, G5ApiError, newIdempotencyKey } from '../g5/api'
import type { G5Api } from '../g5/api'
import type {
  ConversationMessage,
  MemoryDecision,
  MemoryKind,
  MemoryMode,
  MemoryProjection,
  ReflectionJobId,
  StageUsage,
  TaskId,
} from '../g5/types'

type ConversationPageProps = {
  api?: G5Api
  sessionApi?: Pick<G0Api, 'getSession' | 'createDemoSession'>
  pollIntervalMs?: number
}

type MemoryDraft = {
  memoryId: MemoryProjection['memory_id']
  kind: MemoryKind
  content: string
  appliesWhen: string
}

const memoryKindLabels: Record<MemoryKind, string> = {
  preference: '偏好',
  rule: '规则',
  experience: '经验',
}

const statusLabels: Record<MemoryProjection['review_status'], string> = {
  pending: '待确认',
  active: '已启用',
  paused: '已暂停',
  archived: '已忽略',
  superseded: '已被替代',
}

const decisionLabels: Record<MemoryDecision['applicability'], string> = {
  applicable: '本轮适用',
  current_instruction_override: '被本轮明确指令覆盖',
  conflict: '与本轮要求冲突',
  irrelevant: '本轮无关',
}

const effectLabels: Record<NonNullable<MemoryDecision['effect']>, string> = {
  applied: '回答已遵守',
  violated: '回答未遵守',
  not_observable: '无法从回答观察',
  unknown: '效果未知',
}

const eventPageSize = 100
const maxCatchUpPagesPerPoll = 100

export function ConversationPage({
  api = browserG5Api,
  sessionApi = browserG0Api,
  pollIntervalMs = 1500,
}: ConversationPageProps) {
  const [demoAlias, setDemoAlias] = useState<DemoAlias | null>(null)
  const [sessionPhase, setSessionPhase] = useState<'loading' | 'ready' | 'switching' | 'failed'>(
    'loading',
  )
  const [taskId, setTaskId] = useState<TaskId | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [input, setInput] = useState('')
  const [memoryMode, setMemoryMode] = useState<MemoryMode>('on')
  const [memories, setMemories] = useState<MemoryProjection[]>([])
  const [decisions, setDecisions] = useState<MemoryDecision[]>([])
  const [usage, setUsage] = useState<StageUsage[]>([])
  const [provider, setProvider] = useState<{ mode: string; model: string } | null>(null)
  const [reflectionStatus, setReflectionStatus] = useState<string | null>(null)
  const [draft, setDraft] = useState<MemoryDraft | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [mutationPending, setMutationPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [memoryError, setMemoryError] = useState<string | null>(null)
  const generationRef = useRef(0)
  const controllersRef = useRef(new Set<AbortController>())
  const pendingKeysRef = useRef(new Map<string, string>())
  const memoryEventSeqRef = useRef(0)
  const taskEventSeqRef = useRef(0)

  const registerController = useCallback(() => {
    const controller = new AbortController()
    controllersRef.current.add(controller)
    return controller
  }, [])

  const releaseController = useCallback((controller: AbortController) => {
    controllersRef.current.delete(controller)
  }, [])

  const abortOwnerWork = useCallback(() => {
    generationRef.current += 1
    for (const controller of controllersRef.current) controller.abort()
    controllersRef.current.clear()
    pendingKeysRef.current.clear()
  }, [])

  const resetOwnerView = useCallback(() => {
    setTaskId(null)
    setMessages([])
    setMemories([])
    setDecisions([])
    setUsage([])
    setProvider(null)
    setReflectionStatus(null)
    setDraft(null)
    setInput('')
    setError(null)
    setMemoryError(null)
    memoryEventSeqRef.current = 0
    taskEventSeqRef.current = 0
  }, [])

  const keyFor = useCallback((operation: string) => {
    const existing = pendingKeysRef.current.get(operation)
    if (existing) return existing
    const created = newIdempotencyKey()
    pendingKeysRef.current.set(operation, created)
    return created
  }, [])

  const refreshMemories = useCallback(
    async (generation: number, signal?: AbortSignal) => {
      const response = await api.listMemories({}, signal)
      if (generation !== generationRef.current) return
      setMemories(response.items)
      setMemoryError(null)
    },
    [api],
  )

  useEffect(() => {
    const controller = registerController()
    let disposed = false
    async function initializeSession() {
      setSessionPhase('loading')
      try {
        const getSession = sessionApi.getSession
        const createDemoSession = sessionApi.createDemoSession
        if (!getSession || !createDemoSession) throw new Error('session api unavailable')
        let session
        try {
          session = await getSession(controller.signal)
        } catch (caught) {
          if (!(caught instanceof G0ApiError) || caught.code !== 'SESSION_REQUIRED') throw caught
          session = await createDemoSession('blank_demo', controller.signal)
        }
        if (disposed) return
        setDemoAlias(session.demo_alias)
        setSessionPhase('ready')
      } catch (caught) {
        if (disposed || isAbortError(caught)) return
        setSessionPhase('failed')
        setError(publicError(caught, '无法初始化 Demo 会话。'))
      } finally {
        releaseController(controller)
      }
    }
    void initializeSession()
    return () => {
      disposed = true
      controller.abort()
      releaseController(controller)
    }
  }, [registerController, releaseController, sessionApi])

  useEffect(() => {
    if (sessionPhase !== 'ready' || demoAlias === null) return
    const activeAlias = demoAlias
    const generation = generationRef.current
    const controller = registerController()
    let disposed = false
    async function restoreOwner() {
      try {
        await refreshMemories(generation, controller.signal)
        const savedTaskId = readSavedTaskId(activeAlias)
        if (!savedTaskId) return
        try {
          const snapshot = await api.getTask(savedTaskId, controller.signal)
          if (disposed || generation !== generationRef.current) return
          setTaskId(snapshot.task_id)
          setMessages(snapshot.messages)
          setMemoryMode(snapshot.memory_mode)
          setDecisions(snapshot.last_turn?.memory_decisions ?? [])
          setUsage(snapshot.last_turn?.usage ?? [])
          const chatUsage = snapshot.last_turn?.usage.find((item) => item.stage === 'chat')
          setProvider(
            chatUsage
              ? { mode: chatUsage.provider_mode, model: chatUsage.model }
              : { mode: snapshot.provider_mode, model: snapshot.model },
          )
          taskEventSeqRef.current = snapshot.last_event_seq
        } catch (caught) {
          if (caught instanceof G5ApiError && caught.status === 404) {
            clearSavedTaskId(activeAlias)
            return
          }
          throw caught
        }
      } catch (caught) {
        if (disposed || isAbortError(caught)) return
        setError(publicError(caught, '无法恢复当前用户的会话。'))
      } finally {
        releaseController(controller)
      }
    }
    void restoreOwner()
    return () => {
      disposed = true
      controller.abort()
      releaseController(controller)
    }
  }, [api, demoAlias, refreshMemories, registerController, releaseController, sessionPhase])

  useEffect(() => {
    if (sessionPhase !== 'ready' || demoAlias === null) return
    const generation = generationRef.current
    let running = false
    const poll = async () => {
      if (running) return
      running = true
      const controller = registerController()
      try {
        let memoryChanged = false
        for (let page = 0; page < maxCatchUpPagesPerPoll; page += 1) {
          const previousSeq = memoryEventSeqRef.current
          const events = await api.getMemoryEvents(previousSeq, controller.signal)
          if (generation !== generationRef.current) return
          if (events.next_seq !== null && events.next_seq > previousSeq) {
            memoryEventSeqRef.current = events.next_seq
          }
          memoryChanged ||= events.items.length > 0
          if (
            events.items.length < eventPageSize ||
            events.next_seq === null ||
            events.next_seq <= previousSeq
          ) {
            break
          }
        }
        if (memoryChanged) await refreshMemories(generation, controller.signal)
        if (taskId) {
          for (let page = 0; page < maxCatchUpPagesPerPoll; page += 1) {
            const previousSeq = taskEventSeqRef.current
            const taskEvents = await api.getTaskEvents(taskId, previousSeq, controller.signal)
            if (generation !== generationRef.current) return
            if (taskEvents.next_seq !== null && taskEvents.next_seq > previousSeq) {
              taskEventSeqRef.current = taskEvents.next_seq
            }
            if (
              taskEvents.items.length < eventPageSize ||
              taskEvents.next_seq === null ||
              taskEvents.next_seq <= previousSeq
            ) {
              break
            }
          }
        }
        setMemoryError(null)
      } catch (caught) {
        if (!isAbortError(caught) && generation === generationRef.current) {
          setMemoryError(publicError(caught, '实时记忆同步暂时中断。'))
        }
      } finally {
        releaseController(controller)
        running = false
      }
    }
    void poll()
    const timer = globalThis.setInterval(() => void poll(), pollIntervalMs)
    return () => globalThis.clearInterval(timer)
  }, [api, demoAlias, pollIntervalMs, refreshMemories, registerController, releaseController, sessionPhase, taskId])

  useEffect(
    () => () => {
      abortOwnerWork()
    },
    [abortOwnerWork],
  )

  const totalTokens = useMemo(
    () => usage.reduce((sum, item) => sum + item.total_tokens, 0),
    [usage],
  )

  const switchDemoAlias = useCallback(
    async (nextAlias: DemoAlias) => {
      if (
        nextAlias === demoAlias ||
        sessionPhase === 'switching' ||
        !sessionApi.createDemoSession
      ) {
        return
      }
      abortOwnerWork()
      resetOwnerView()
      setSessionPhase('switching')
      const controller = registerController()
      try {
        const session = await sessionApi.createDemoSession(nextAlias, controller.signal)
        setDemoAlias(session.demo_alias)
        setSessionPhase('ready')
      } catch (caught) {
        if (isAbortError(caught)) return
        setSessionPhase('failed')
        setError(publicError(caught, '切换 Demo 用户失败。'))
      } finally {
        releaseController(controller)
      }
    },
    [
      abortOwnerWork,
      demoAlias,
      registerController,
      releaseController,
      resetOwnerView,
      sessionApi,
      sessionPhase,
    ],
  )

  const startNewConversation = useCallback(() => {
    if (demoAlias === null) return
    abortOwnerWork()
    clearSavedTaskId(demoAlias)
    resetOwnerView()
  }, [abortOwnerWork, demoAlias, resetOwnerView])

  const pollReflectionJob = useCallback(
    async (jobId: ReflectionJobId, generation: number) => {
      const started = Date.now()
      setReflectionStatus('正在后台识别可复用记忆')
      while (Date.now() - started < 90_000 && generation === generationRef.current) {
        const controller = registerController()
        try {
          const job = await api.getReflectionJob(jobId, controller.signal)
          if (generation !== generationRef.current) return
          if (job.status === 'completed') {
            setReflectionStatus(
              job.mutation_decision === 'noop' ? '本轮没有新增长期记忆' : '本轮记忆分析完成',
            )
            await refreshMemories(generation, controller.signal)
            return
          }
          if (job.status === 'failed') {
            setReflectionStatus(`后台记忆分析失败（${job.error_code ?? '受控错误'}）`)
            return
          }
        } catch (caught) {
          if (isAbortError(caught)) return
          setMemoryError(publicError(caught, '无法读取后台记忆分析状态。'))
          return
        } finally {
          releaseController(controller)
        }
        await wait(pollIntervalMs)
      }
      if (generation === generationRef.current) setReflectionStatus('后台记忆分析仍在继续')
    },
    [api, pollIntervalMs, refreshMemories, registerController, releaseController],
  )

  const submitTurn = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const content = input.trim()
      if (!content || submitting || sessionPhase !== 'ready' || demoAlias === null) return
      setSubmitting(true)
      setError(null)
      const generation = generationRef.current
      const controller = registerController()
      try {
        let activeTaskId = taskId
        if (!activeTaskId) {
          const operation = `create-task:${memoryMode}`
          const created = await api.createTask(
            memoryMode,
            keyFor(operation),
            controller.signal,
          )
          pendingKeysRef.current.delete(operation)
          if (generation !== generationRef.current) return
          activeTaskId = created.task_id
          setTaskId(activeTaskId)
          setProvider({ mode: created.provider_mode, model: created.model })
          saveTaskId(demoAlias, activeTaskId)
        }
        const operation = `turn:${activeTaskId}:${memoryMode}:${content}`
        const response = await api.createTurn(
          activeTaskId,
          content,
          memoryMode,
          keyFor(operation),
          controller.signal,
        )
        pendingKeysRef.current.delete(operation)
        if (generation !== generationRef.current) return
        setMessages((current) => [...current, response.user_message, response.assistant_message])
        setDecisions(response.memory_decisions)
        setUsage(response.usage)
        const chatUsage = response.usage.find((item) => item.stage === 'chat')
        if (chatUsage) setProvider({ mode: chatUsage.provider_mode, model: chatUsage.model })
        setInput('')
        if (response.reflection_job_id) {
          void pollReflectionJob(response.reflection_job_id, generation)
        } else {
          setReflectionStatus(memoryMode === 'off' ? '本轮已关闭记忆' : null)
        }
      } catch (caught) {
        if (isAbortError(caught)) return
        setError(publicError(caught, '本轮对话没有完成。'))
      } finally {
        releaseController(controller)
        if (generation === generationRef.current) setSubmitting(false)
      }
    },
    [
      api,
      demoAlias,
      input,
      keyFor,
      memoryMode,
      pollReflectionJob,
      registerController,
      releaseController,
      sessionPhase,
      submitting,
      taskId,
    ],
  )

  const saveDraft = useCallback(async () => {
    if (!draft) return
    const card = memories.find((item) => item.memory_id === draft.memoryId)
    if (!card || !draft.content.trim() || !draft.appliesWhen.trim()) return
    const operation = `edit:${card.memory_id}:${card.current_version_id}:${draft.kind}:${draft.content}:${draft.appliesWhen}`
    setMutationPending(card.memory_id)
    setMemoryError(null)
    const generation = generationRef.current
    const controller = registerController()
    try {
      await api.editMemory(
        card.memory_id,
        {
          kind: draft.kind,
          content: draft.content.trim(),
          applies_when: draft.appliesWhen.trim(),
          expected_current_version_id: card.current_version_id,
        },
        keyFor(operation),
        controller.signal,
      )
      pendingKeysRef.current.delete(operation)
      await refreshMemories(generation, controller.signal)
      if (generation === generationRef.current) setDraft(null)
    } catch (caught) {
      if (!isAbortError(caught)) {
        setMemoryError(publicError(caught, '记忆编辑失败，草稿已保留。'))
      }
    } finally {
      releaseController(controller)
      if (generation === generationRef.current) setMutationPending(null)
    }
  }, [api, draft, keyFor, memories, refreshMemories, registerController, releaseController])

  const changeMemory = useCallback(
    async (
      card: MemoryProjection,
      action: 'confirm' | 'dismiss' | 'pause' | 'resume',
    ) => {
      const operation = `${action}:${card.memory_id}:${card.current_version_id}`
      setMutationPending(card.memory_id)
      setMemoryError(null)
      const generation = generationRef.current
      const controller = registerController()
      try {
        await api.changeMemory(
          card.memory_id,
          action,
          keyFor(operation),
          controller.signal,
        )
        pendingKeysRef.current.delete(operation)
        await refreshMemories(generation, controller.signal)
      } catch (caught) {
        if (!isAbortError(caught)) setMemoryError(publicError(caught, '记忆状态更新失败。'))
      } finally {
        releaseController(controller)
        if (generation === generationRef.current) setMutationPending(null)
      }
    },
    [api, keyFor, refreshMemories, registerController, releaseController],
  )

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="flex min-h-[720px] flex-col overflow-hidden rounded-3xl border border-stone-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
          <div>
            <h1 className="text-lg font-black tracking-tight">与 MemTrace 对话</h1>
            <p className="mt-1 text-xs text-slate-500">像普通 Agent 一样交流，记忆识别在后台完成。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <DemoUserSwitch
              current={demoAlias}
              disabled={sessionPhase !== 'ready'}
              onChange={(alias) => void switchDemoAlias(alias)}
            />
            <button
              className="rounded-xl border border-stone-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-stone-50 disabled:opacity-50"
              disabled={sessionPhase !== 'ready'}
              onClick={startNewConversation}
              type="button"
            >
              新对话
            </button>
          </div>
        </div>

        <div aria-live="polite" className="flex-1 space-y-4 overflow-y-auto bg-stone-50/60 p-5">
          {messages.length === 0 ? (
            <div className="mx-auto mt-24 max-w-lg text-center">
              <p className="text-xl font-black text-slate-800">今天想聊什么？</p>
              <p className="mt-3 text-sm leading-6 text-slate-500">
                你可以自然表达偏好、规则或做事经验。只有经过后台分析和持久化的内容才会出现在右侧。
              </p>
            </div>
          ) : null}
          {messages.map((message) => (
            <article
              className={[
                'max-w-[88%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7',
                message.role === 'user'
                  ? 'ml-auto bg-emerald-700 text-white'
                  : 'border border-stone-200 bg-white text-slate-800 shadow-sm',
              ].join(' ')}
              data-testid={`message-${message.role}`}
              key={message.message_id}
            >
              {message.content}
            </article>
          ))}
          {submitting ? <p className="text-sm font-semibold text-emerald-700">模型正在回答…</p> : null}
        </div>

        <div className="border-t border-stone-200 p-4">
          {error ? (
            <p className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
              {error}
            </p>
          ) : null}
          <form className="space-y-3" onSubmit={(event) => void submitTurn(event)}>
            <textarea
              aria-label="对话内容"
              className="min-h-28 w-full resize-y rounded-2xl border border-stone-300 bg-white px-4 py-3 text-sm leading-6 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
              disabled={sessionPhase !== 'ready' || submitting}
              maxLength={20_000}
              onChange={(event) => setInput(event.target.value)}
              placeholder="直接输入你想说的话…"
              value={input}
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm font-bold text-slate-600">
                <input
                  checked={memoryMode === 'on'}
                  className="size-4 accent-emerald-700"
                  onChange={(event) => setMemoryMode(event.target.checked ? 'on' : 'off')}
                  type="checkbox"
                />
                本轮启用记忆
              </label>
              <button
                className="rounded-2xl bg-emerald-700 px-5 py-2.5 text-sm font-black text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!input.trim() || submitting || sessionPhase !== 'ready'}
                type="submit"
              >
                {submitting ? '发送中' : '发送'}
              </button>
            </div>
          </form>
          <Diagnostics provider={provider} totalTokens={totalTokens} usage={usage} />
          <DecisionSummary decisions={decisions} />
        </div>
      </section>

      <aside className="min-w-0 rounded-3xl border border-stone-200 bg-white shadow-sm">
        <div className="border-b border-stone-200 px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-black">实时记忆</h2>
              <p className="mt-1 text-xs text-slate-500">偏好、规则与经验</p>
            </div>
            <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-black text-emerald-800">
              {memories.length}
            </span>
          </div>
          {reflectionStatus ? <p className="mt-3 text-xs font-semibold text-slate-600">{reflectionStatus}</p> : null}
          {memoryError ? (
            <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-800" role="alert">
              {memoryError}
            </p>
          ) : null}
        </div>
        <div className="max-h-[820px] space-y-3 overflow-y-auto p-4">
          {memories.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm leading-6 text-slate-500">
              还没有被持久化的记忆。正常对话后，后台识别结果会出现在这里。
            </p>
          ) : null}
          {memories.map((card) => (
            <MemoryCard
              card={card}
              draft={draft?.memoryId === card.memory_id ? draft : null}
              key={card.memory_id}
              onCancelEdit={() => setDraft(null)}
              onChangeDraft={setDraft}
              onEdit={() =>
                setDraft({
                  memoryId: card.memory_id,
                  kind: card.kind,
                  content: card.content,
                  appliesWhen: card.applies_when,
                })
              }
              onLifecycle={(action) => void changeMemory(card, action)}
              onSave={() => void saveDraft()}
              pending={mutationPending === card.memory_id}
            />
          ))}
        </div>
      </aside>
    </div>
  )
}

function DemoUserSwitch({
  current,
  disabled,
  onChange,
}: {
  current: DemoAlias | null
  disabled: boolean
  onChange: (alias: DemoAlias) => void
}) {
  return (
    <div aria-label="Demo 用户" className="flex rounded-xl bg-stone-100 p-1">
      {(['blank_demo', 'seeded_demo'] as const).map((alias) => (
        <button
          aria-pressed={current === alias}
          className={[
            'rounded-lg px-3 py-1.5 text-xs font-black',
            current === alias ? 'bg-white text-emerald-800 shadow-sm' : 'text-slate-500',
          ].join(' ')}
          disabled={disabled}
          key={alias}
          onClick={() => onChange(alias)}
          type="button"
        >
          {alias === 'blank_demo' ? '空白用户' : '种子用户'}
        </button>
      ))}
    </div>
  )
}

function Diagnostics({
  provider,
  totalTokens,
  usage,
}: {
  provider: { mode: string; model: string } | null
  totalTokens: number
  usage: StageUsage[]
}) {
  if (!provider) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-semibold text-slate-500">
      <span>Provider: {provider.mode === 'real' ? '真实模型' : provider.mode}</span>
      <span>模型: {provider.model}</span>
      {usage.length > 0 ? <span>本轮实际 token: {totalTokens}</span> : null}
    </div>
  )
}

function DecisionSummary({ decisions }: { decisions: MemoryDecision[] }) {
  if (decisions.length === 0) return null
  return (
    <details className="mt-3 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-black text-slate-700">本轮记忆判定（{decisions.length}）</summary>
      <ul className="mt-2 space-y-2 text-slate-600">
        {decisions.map((decision) => (
          <li key={decision.memory_id}>
            {decisionLabels[decision.applicability]}
            {decision.injected ? ' · 已注入模型上下文' : ' · 未注入'}
            {decision.effect ? ` · ${effectLabels[decision.effect]}` : ''}
          </li>
        ))}
      </ul>
    </details>
  )
}

function MemoryCard({
  card,
  draft,
  pending,
  onEdit,
  onSave,
  onCancelEdit,
  onChangeDraft,
  onLifecycle,
}: {
  card: MemoryProjection
  draft: MemoryDraft | null
  pending: boolean
  onEdit: () => void
  onSave: () => void
  onCancelEdit: () => void
  onChangeDraft: (draft: MemoryDraft) => void
  onLifecycle: (action: 'confirm' | 'dismiss' | 'pause' | 'resume') => void
}) {
  return (
    <article className="rounded-2xl border border-stone-200 p-4" data-memory-id={card.memory_id}>
      {draft ? (
        <div className="space-y-3">
          <label className="block text-xs font-black text-slate-600">
            类型
            <select
              className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-2 text-sm"
              onChange={(event) => onChangeDraft({ ...draft, kind: event.target.value as MemoryKind })}
              value={draft.kind}
            >
              {Object.entries(memoryKindLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-black text-slate-600">
            内容
            <textarea
              className="mt-1 min-h-24 w-full rounded-xl border border-stone-300 px-3 py-2 text-sm leading-6"
              onChange={(event) => onChangeDraft({ ...draft, content: event.target.value })}
              value={draft.content}
            />
          </label>
          <label className="block text-xs font-black text-slate-600">
            适用条件
            <textarea
              className="mt-1 min-h-16 w-full rounded-xl border border-stone-300 px-3 py-2 text-sm leading-6"
              onChange={(event) => onChangeDraft({ ...draft, appliesWhen: event.target.value })}
              value={draft.appliesWhen}
            />
          </label>
          <div className="flex gap-2">
            <button
              className="rounded-xl bg-emerald-700 px-3 py-2 text-xs font-black text-white disabled:opacity-50"
              disabled={pending || !draft.content.trim() || !draft.appliesWhen.trim()}
              onClick={onSave}
              type="button"
            >
              保存
            </button>
            <button
              className="rounded-xl border border-stone-200 px-3 py-2 text-xs font-bold"
              disabled={pending}
              onClick={onCancelEdit}
              type="button"
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-black text-violet-800">
              {memoryKindLabels[card.kind]}
            </span>
            <span className="rounded-full bg-stone-100 px-2 py-1 text-[11px] font-bold text-slate-600">
              {statusLabels[card.review_status]}
            </span>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm font-semibold leading-6 text-slate-800">{card.content}</p>
          <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-500">
            适用条件：{card.applies_when}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="rounded-xl border border-stone-200 px-3 py-1.5 text-xs font-bold hover:bg-stone-50"
              disabled={pending}
              onClick={onEdit}
              type="button"
            >
              编辑
            </button>
            {card.review_status === 'pending' ? (
              <>
                <button
                  className="rounded-xl bg-emerald-700 px-3 py-1.5 text-xs font-black text-white disabled:opacity-50"
                  disabled={pending}
                  onClick={() => onLifecycle('confirm')}
                  type="button"
                >
                  确认启用
                </button>
                <button
                  className="rounded-xl bg-stone-100 px-3 py-1.5 text-xs font-bold text-slate-600 disabled:opacity-50"
                  disabled={pending}
                  onClick={() => onLifecycle('dismiss')}
                  type="button"
                >
                  忽略
                </button>
              </>
            ) : null}
            {card.review_status === 'active' ? (
              <button
                className="rounded-xl bg-amber-50 px-3 py-1.5 text-xs font-bold text-amber-800 disabled:opacity-50"
                disabled={pending}
                onClick={() => onLifecycle('pause')}
                type="button"
              >
                暂停
              </button>
            ) : null}
            {card.review_status === 'paused' ? (
              <button
                className="rounded-xl bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-800 disabled:opacity-50"
                disabled={pending}
                onClick={() => onLifecycle('resume')}
                type="button"
              >
                恢复
              </button>
            ) : null}
          </div>
        </>
      )}
    </article>
  )
}

function savedTaskKey(alias: DemoAlias): string {
  return `memtrace:g5:task:${alias}`
}

function readSavedTaskId(alias: DemoAlias): TaskId | null {
  const value = globalThis.localStorage?.getItem(savedTaskKey(alias))
  return value && /^task_[0-9A-HJKMNP-TV-Z]{26}$/.test(value) ? (value as TaskId) : null
}

function saveTaskId(alias: DemoAlias, taskId: TaskId): void {
  globalThis.localStorage?.setItem(savedTaskKey(alias), taskId)
}

function clearSavedTaskId(alias: DemoAlias): void {
  globalThis.localStorage?.removeItem(savedTaskKey(alias))
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function publicError(error: unknown, fallback: string): string {
  if (error instanceof G5ApiError || error instanceof G0ApiError) return error.message
  return fallback
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms))
}
