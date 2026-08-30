import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useSession } from '../auth/useSession'
import { browserG5Api, G5ApiError, newIdempotencyKey } from '../g5/api'
import type {
  ConversationListItem,
  ConversationMessage,
  MemoryDecision,
  MemoryKind,
  MemoryMode,
  MemoryProjection,
  StageUsage,
  TaskId,
  ToolCall,
  UserEffect,
} from '../g5/types'

type Draft = {
  memoryId: MemoryProjection['memory_id']
  kind: MemoryKind
  content: string
  appliesWhen: string
}

const kindLabel: Record<MemoryKind, string> = {
  preference: '偏好',
  rule: '规则',
  experience: '经验',
}

export function AgentPage() {
  const { session, refresh } = useSession()
  const [searchParams] = useSearchParams()
  const initialTaskParam = useRef(searchParams.get('task'))
  const [tasks, setTasks] = useState<ConversationListItem[]>([])
  const [taskId, setTaskId] = useState<TaskId | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [memories, setMemories] = useState<MemoryProjection[]>([])
  const [decisions, setDecisions] = useState<MemoryDecision[]>([])
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [usage, setUsage] = useState<StageUsage[]>([])
  const [input, setInput] = useState('')
  const [memoryMode, setMemoryMode] = useState<MemoryMode>(
    session?.account.default_memory_mode ?? 'on',
  )
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [analysisState, setAnalysisState] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busyMemory, setBusyMemory] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [memoryError, setMemoryError] = useState<string | null>(null)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const eventSource = useRef<EventSource | null>(null)
  const eventSourceTask = useRef<TaskId | null>(null)
  const eventSourceReady = useRef<Promise<void> | null>(null)
  const operationKeys = useRef(new Map<string, string>())
  const lastDeltaIndex = useRef(0)
  const memorySeq = useRef(0)

  const registerController = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return controller
  }, [])

  const releaseController = useCallback((controller: AbortController) => {
    controllers.current.delete(controller)
  }, [])

  const cancelPrivateWork = useCallback(() => {
    generation.current += 1
    for (const controller of controllers.current) controller.abort()
    controllers.current.clear()
    eventSource.current?.close()
    eventSource.current = null
    eventSourceTask.current = null
    eventSourceReady.current = null
    operationKeys.current.clear()
    lastDeltaIndex.current = 0
    setPendingUser(null)
    setStreamingText('')
    setDraft(null)
  }, [])

  const loadMemories = useCallback(async (signal?: AbortSignal) => {
    const page = await browserG5Api.listMemories({}, signal)
    setMemories(page.items)
    setMemoryError(null)
  }, [])

  const loadTasks = useCallback(async (signal?: AbortSignal) => {
    const page = await browserG5Api.listTasks(undefined, signal)
    setTasks(page.items)
    return page.items
  }, [])

  const syncTaskParam = useCallback((nextTaskId: TaskId | null) => {
    const url = new URL(globalThis.location.href)
    if (nextTaskId === null) url.searchParams.delete('task')
    else url.searchParams.set('task', nextTaskId)
    globalThis.history.replaceState(
      globalThis.history.state,
      '',
      `${url.pathname}${url.search}${url.hash}`,
    )
  }, [])

  const restoreTask = useCallback(async (nextTaskId: TaskId, signal?: AbortSignal) => {
    const snapshot = await browserG5Api.getTask(nextTaskId, signal)
    setTaskId(snapshot.task_id)
    setMessages(snapshot.messages)
    setMemoryMode(snapshot.memory_mode)
    setDecisions(snapshot.last_turn?.memory_decisions ?? [])
    setToolCalls(snapshot.last_turn?.tool_calls ?? [])
    setUsage(snapshot.last_turn?.usage ?? [])
  }, [])

  const connectTaskStream = useCallback(
    (nextTaskId: TaskId): Promise<void> => {
      if (eventSource.current !== null && eventSourceTask.current === nextTaskId) {
        return eventSourceReady.current ?? Promise.resolve()
      }
      eventSource.current?.close()
      lastDeltaIndex.current = 0
      const source = new EventSource(
        `/api/v2/tasks/${encodeURIComponent(nextTaskId)}/stream?after_event_seq=0`,
        { withCredentials: true },
      )
      eventSource.current = source
      eventSourceTask.current = nextTaskId
      const ready = new Promise<void>((resolve, reject) => {
        const timeout = globalThis.setTimeout(() => {
          reject(new Error('实时连接建立超时；本轮尚未发送。'))
        }, 8_000)
        source.addEventListener(
          'open',
          () => {
            globalThis.clearTimeout(timeout)
            resolve()
          },
          { once: true },
        )
      })
      eventSourceReady.current = ready
      source.addEventListener('assistant.delta', (event) => {
        const payload = parseDelta((event as MessageEvent<string>).data)
        if (payload === null || payload.deltaIndex <= lastDeltaIndex.current) return
        lastDeltaIndex.current = payload.deltaIndex
        setStreamingText((current) => current + payload.delta)
      })
      source.addEventListener('turn.started', () =>
        setAnalysisState('模型正在分析本轮上下文…'),
      )
      source.addEventListener('conversation.tool.completed', () =>
        setAnalysisState('静态语法检查已完成，模型正在组织回答…'),
      )
      source.addEventListener('conversation.tool.skipped', () =>
        setAnalysisState('模型判断本轮无需静态工具。'),
      )
      source.addEventListener('turn.completed', () => {
        setAnalysisState('回答已持久化，后台正在分析记忆。')
        const controller = registerController()
        void restoreTask(nextTaskId, controller.signal)
          .catch(() => undefined)
          .finally(() => releaseController(controller))
      })
      source.addEventListener('turn.failed', () => {
        setStreamingText('')
        setAnalysisState('本轮失败；未完成回答已清除，用户消息仍保留。')
      })
      source.onerror = () => setAnalysisState('实时连接中断，正在由浏览器自动重连…')
      return ready
    },
    [registerController, releaseController, restoreTask],
  )

  useEffect(() => {
    const controller = registerController()
    const run = async () => {
      try {
        const [loadedTasks] = await Promise.all([
          loadTasks(controller.signal),
          loadMemories(controller.signal),
        ])
        const requested = initialTaskParam.current
        const target =
          loadedTasks.find((item) => item.task_id === requested)?.task_id ??
          loadedTasks[0]?.task_id ??
          null
        if (target === null) syncTaskParam(null)
        else {
          await restoreTask(target, controller.signal)
          syncTaskParam(target)
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(message(reason, '无法载入账号数据。'))
      } finally {
        releaseController(controller)
      }
    }
    void run()
    return () => {
      controller.abort()
      releaseController(controller)
      cancelPrivateWork()
    }
  }, [
    cancelPrivateWork,
    loadMemories,
    loadTasks,
    registerController,
    releaseController,
    restoreTask,
    syncTaskParam,
  ])

  useEffect(() => {
    if (taskId === null) return
    void connectTaskStream(taskId).catch((reason) => {
      setError(message(reason, '实时连接建立失败。'))
    })
    return () => {
      if (eventSourceTask.current === taskId) {
        eventSource.current?.close()
        eventSource.current = null
        eventSourceTask.current = null
        eventSourceReady.current = null
      }
    }
  }, [connectTaskStream, taskId])

  useEffect(() => {
    let running = false
    const poll = async () => {
      if (running) return
      running = true
      const controller = registerController()
      try {
        const events = await browserG5Api.getMemoryEvents(memorySeq.current, controller.signal)
        if (events.next_seq !== null) memorySeq.current = Math.max(memorySeq.current, events.next_seq)
        if (events.items.length > 0) await loadMemories(controller.signal)
      } catch (reason) {
        if (!controller.signal.aborted) setMemoryError(message(reason, '记忆同步暂时中断。'))
      } finally {
        releaseController(controller)
        running = false
      }
    }
    void poll()
    const timer = globalThis.setInterval(() => void poll(), 1500)
    return () => globalThis.clearInterval(timer)
  }, [loadMemories, registerController, releaseController])

  const totalTokens = useMemo(() => usage.reduce((sum, row) => sum + row.total_tokens, 0), [usage])
  const chatUsage = usage.find((row) => row.stage === 'chat')

  async function chooseTask(nextTaskId: TaskId) {
    cancelPrivateWork()
    setMessages([])
    setDecisions([])
    setToolCalls([])
    setUsage([])
    setTaskId(nextTaskId)
    const controller = registerController()
    try {
      await restoreTask(nextTaskId, controller.signal)
      syncTaskParam(nextTaskId)
    } catch (reason) {
      if (!controller.signal.aborted) setError(message(reason, '无法恢复该对话。'))
    } finally {
      releaseController(controller)
    }
  }

  function newConversation() {
    cancelPrivateWork()
    syncTaskParam(null)
    setTaskId(null)
    setMessages([])
    setDecisions([])
    setToolCalls([])
    setUsage([])
    setError(null)
    setAnalysisState(null)
    setMemoryMode(session?.account.default_memory_mode ?? 'on')
  }

  async function submitTurn(event?: React.FormEvent) {
    event?.preventDefault()
    const content = input.trim()
    if (!content || submitting) return
    setSubmitting(true)
    setError(null)
    setPendingUser(content)
    setStreamingText('')
    lastDeltaIndex.current = 0
    setInput('')
    const controller = registerController()
    let activeTaskId = taskId
    try {
      if (activeTaskId === null) {
        const createKey = operationKey('task:create')
        const created = await browserG5Api.createTask(memoryMode, createKey, controller.signal)
        operationKeys.current.delete('task:create')
        activeTaskId = created.task_id
        setTaskId(activeTaskId)
        syncTaskParam(activeTaskId)
      }
      await connectTaskStream(activeTaskId)
      const turnKeyName = `turn:${activeTaskId}:${content}`
      const turn = await browserG5Api.createTurn(
        activeTaskId,
        content,
        memoryMode,
        operationKey(turnKeyName),
        controller.signal,
      )
      operationKeys.current.delete(turnKeyName)
      setMessages((current) => mergeMessages(current, [turn.user_message, turn.assistant_message]))
      setDecisions(turn.memory_decisions)
      setToolCalls(turn.tool_calls)
      setUsage(turn.usage)
      setPendingUser(null)
      setStreamingText('')
      setAnalysisState(turn.reflection_job_id ? '后台正在提取偏好、规则与经验…' : null)
      await Promise.all([loadTasks(controller.signal), refresh(controller.signal)])
    } catch (reason) {
      setStreamingText('')
      setInput(content)
      if (activeTaskId !== null && !(reason instanceof DOMException && reason.name === 'AbortError')) {
        try {
          await restoreTask(activeTaskId, controller.signal)
        } catch {
          // The controlled public error below remains the primary diagnostic.
        }
      }
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(message(reason, '本轮未完成；输入已恢复，可使用同一内容重试。'))
      }
      setPendingUser(null)
    } finally {
      setSubmitting(false)
      releaseController(controller)
    }
  }

  function operationKey(name: string): string {
    const existing = operationKeys.current.get(name)
    if (existing) return existing
    const key = newIdempotencyKey()
    operationKeys.current.set(name, key)
    return key
  }

  async function mutateMemory(
    memory: MemoryProjection,
    action: 'confirm' | 'dismiss' | 'pause' | 'resume' | 'edit',
  ) {
    setBusyMemory(memory.memory_id)
    setMemoryError(null)
    const controller = registerController()
    const keyName = `memory:${memory.memory_id}:${action}`
    try {
      if (action === 'edit' && draft?.memoryId === memory.memory_id) {
        await browserG5Api.editMemory(
          memory.memory_id,
          {
            kind: draft.kind,
            content: draft.content,
            applies_when: draft.appliesWhen,
            expected_current_version_id: memory.current_version_id,
          },
          operationKey(keyName),
          controller.signal,
        )
        setDraft(null)
      } else if (action !== 'edit') {
        await browserG5Api.changeMemory(
          memory.memory_id,
          action,
          operationKey(keyName),
          controller.signal,
        )
      }
      operationKeys.current.delete(keyName)
      await loadMemories(controller.signal)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setMemoryError(message(reason, '记忆操作未完成；编辑草稿已保留。'))
      }
    } finally {
      setBusyMemory(null)
      releaseController(controller)
    }
  }

  async function recordEffect(decision: MemoryDecision, effect: UserEffect) {
    if (taskId === null) return
    const controller = registerController()
    const name = `effect:${taskId}:${decision.memory_id}`
    try {
      await browserG5Api.recordMemoryEffect(
        taskId,
        decision.memory_id,
        effect,
        operationKey(name),
        controller.signal,
      )
      operationKeys.current.delete(name)
      setAnalysisState(`已记录 ${effect} 反馈。`)
    } catch (reason) {
      setError(message(reason, '效果反馈未完成。'))
    } finally {
      releaseController(controller)
    }
  }

  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[210px_minmax(0,1fr)_340px]">
      <aside className="rounded-3xl border border-stone-200 bg-white p-3 shadow-sm">
        <button className="w-full rounded-2xl bg-emerald-700 px-4 py-3 text-sm font-black text-white" onClick={newConversation} type="button">
          新对话
        </button>
        <h2 className="mt-5 px-2 text-xs font-black uppercase tracking-wider text-slate-400">会话历史</h2>
        <div className="mt-2 space-y-1">
          {tasks.length === 0 ? <p className="px-2 py-4 text-xs text-slate-500">还没有历史会话。</p> : null}
          {tasks.map((task) => (
            <button
              className={`w-full rounded-xl px-3 py-2 text-left text-sm ${task.task_id === taskId ? 'bg-emerald-50 font-black text-emerald-900' : 'text-slate-600 hover:bg-stone-50'}`}
              key={task.task_id}
              onClick={() => void chooseTask(task.task_id)}
              type="button"
            >
              <span className="line-clamp-2 block">{task.title}</span>
              <span className="mt-1 block text-[11px] text-slate-400">{task.message_count} 条消息</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex min-h-[760px] min-w-0 flex-col overflow-hidden rounded-3xl border border-stone-200 bg-white shadow-sm" aria-labelledby="agent-title">
        <header className="border-b border-stone-200 px-5 py-4">
          <h1 className="text-lg font-black" id="agent-title">与 MemTrace 对话</h1>
          <p className="mt-1 text-xs text-slate-500">像普通 Agent 一样自然交流；记忆分析在后台完成。</p>
        </header>
        <div aria-live="polite" className="flex-1 space-y-4 overflow-y-auto bg-stone-50/60 p-5">
          {messages.length === 0 && pendingUser === null ? <EmptyConversation /> : null}
          {messages.map((item) => <MessageBubble key={item.message_id} message={item} />)}
          {pendingUser ? <div className="ml-auto max-w-[88%] whitespace-pre-wrap rounded-2xl bg-emerald-700 px-4 py-3 text-sm leading-7 text-white">{pendingUser}</div> : null}
          {streamingText ? <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm leading-7 text-slate-800 shadow-sm">{streamingText}<span className="ml-1 inline-block size-1.5 animate-pulse rounded-full bg-emerald-600" /></div> : null}
          {submitting && !streamingText ? <p className="text-sm font-bold text-emerald-700">模型正在思考首个响应…</p> : null}
        </div>
        <div className="border-t border-stone-200 p-4">
          {error ? <p className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">{error}</p> : null}
          {analysisState ? <p className="mb-3 text-xs font-semibold text-slate-500" role="status">{analysisState}</p> : null}
          <form onSubmit={(event) => void submitTurn(event)}>
            <textarea
              aria-label="对话内容"
              className="min-h-28 w-full resize-y rounded-2xl border border-stone-300 px-4 py-3 text-sm leading-6 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
              disabled={submitting}
              maxLength={20_000}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void submitTurn()
                }
              }}
              placeholder="直接输入你想说的话…"
              value={input}
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm font-bold text-slate-600">
                <input checked={memoryMode === 'on'} className="size-4 accent-emerald-700" onChange={(event) => setMemoryMode(event.target.checked ? 'on' : 'off')} type="checkbox" />
                本轮启用记忆
              </label>
              <button className="rounded-2xl bg-emerald-700 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50" disabled={!input.trim() || submitting} type="submit">{submitting ? '发送中' : '发送'}</button>
            </div>
          </form>
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] font-semibold text-slate-500">
            <span>Provider：{session?.provider_mode === 'real' ? '真实模型' : session?.provider_mode}</span>
            <span>模型：{session?.model}</span>
            {usage.length ? <span>本轮实际 token：{totalTokens}</span> : null}
            {chatUsage?.first_token_ms !== null && chatUsage?.first_token_ms !== undefined ? <span>首 token：{chatUsage.first_token_ms} ms</span> : null}
            {chatUsage ? <span>模型总时延：{chatUsage.latency_ms} ms</span> : null}
          </div>
          {toolCalls.map((tool) => <ToolResult key={tool.tool_call_id} tool={tool} />)}
          {decisions.length ? <MemoryDecisions decisions={decisions} onEffect={(decision, effect) => void recordEffect(decision, effect)} /> : null}
        </div>
      </section>

      <aside className="min-w-0 rounded-3xl border border-stone-200 bg-white shadow-sm">
        <header className="border-b border-stone-200 px-5 py-4">
          <div className="flex items-center justify-between"><div><h2 className="font-black">实时记忆</h2><p className="mt-1 text-xs text-slate-500">偏好、规则与经验</p></div><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-black text-emerald-800">{memories.length}</span></div>
          {memoryError ? <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-800" role="alert">{memoryError}</p> : null}
        </header>
        <div className="max-h-[820px] space-y-3 overflow-y-auto p-4">
          {memories.length === 0 ? <p className="rounded-2xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm leading-6 text-slate-500">正常对话后，后台识别到的持久偏好、规则或经验会出现在这里。</p> : null}
          {memories.map((memory) => (
            <RealtimeMemoryCard
              busy={busyMemory === memory.memory_id}
              draft={draft?.memoryId === memory.memory_id ? draft : null}
              key={memory.memory_id}
              memory={memory}
              onDraft={setDraft}
              onMutate={(action) => void mutateMemory(memory, action)}
            />
          ))}
        </div>
      </aside>
    </div>
  )
}

function EmptyConversation() {
  return <div className="mx-auto mt-28 max-w-lg text-center"><p className="text-xl font-black">今天想聊什么？</p><p className="mt-3 text-sm leading-6 text-slate-500">无需选择任务类型。你可以直接提问，也可以自然表达长期偏好、规则或经验。</p></div>
}

function MessageBubble({ message }: { message: ConversationMessage }) {
  return <article className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7 ${message.role === 'user' ? 'ml-auto bg-emerald-700 text-white' : 'border border-stone-200 bg-white text-slate-800 shadow-sm'}`}>{message.content}</article>
}

function ToolResult({ tool }: { tool: ToolCall }) {
  return <div className="mt-3 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"><strong>工具：Python AST 静态检查</strong><span> · {tool.status === 'succeeded' ? '已完成' : tool.status}</span>{tool.result ? <span> · {tool.result.valid ? '语法有效' : `发现语法问题${tool.result.syntax_error?.line ? `（第 ${tool.result.syntax_error.line} 行）` : ''}`}</span> : null}<span> · {Math.round(tool.latency_ms ?? 0)} ms</span><p className="mt-1 text-sky-700">仅解析语法；没有运行代码，也没有访问 Shell、文件或网络。</p></div>
}

function MemoryDecisions({ decisions, onEffect }: { decisions: MemoryDecision[]; onEffect: (decision: MemoryDecision, effect: UserEffect) => void }) {
  return <details className="mt-3 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs"><summary className="cursor-pointer font-black">本轮记忆判定（{decisions.length}）</summary><ul className="mt-2 space-y-3">{decisions.map((decision) => <li key={decision.memory_id}><p>{decision.applicability} · {decision.injected ? '已注入' : '未注入'} · {decision.effect ?? '效果待判断'}</p>{decision.injected ? <div className="mt-1 flex gap-2"><button onClick={() => onEffect(decision, 'helpful')} type="button">有帮助</button><button onClick={() => onEffect(decision, 'harmful')} type="button">有害</button><button onClick={() => onEffect(decision, 'stale')} type="button">已过时</button></div> : null}</li>)}</ul></details>
}

function RealtimeMemoryCard({ memory, draft, busy, onDraft, onMutate }: { memory: MemoryProjection; draft: Draft | null; busy: boolean; onDraft: (draft: Draft | null) => void; onMutate: (action: 'confirm' | 'dismiss' | 'pause' | 'resume' | 'edit') => void }) {
  if (draft) return <article className="rounded-2xl border border-stone-200 p-4"><label className="block text-xs font-black">类型<select className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-2" value={draft.kind} onChange={(event) => onDraft({ ...draft, kind: event.target.value as MemoryKind })}>{Object.entries(kindLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="mt-3 block text-xs font-black">内容<textarea className="mt-1 min-h-24 w-full rounded-xl border border-stone-300 px-3 py-2" value={draft.content} onChange={(event) => onDraft({ ...draft, content: event.target.value })} /></label><label className="mt-3 block text-xs font-black">适用条件<textarea className="mt-1 min-h-16 w-full rounded-xl border border-stone-300 px-3 py-2" value={draft.appliesWhen} onChange={(event) => onDraft({ ...draft, appliesWhen: event.target.value })} /></label><div className="mt-3 flex gap-2"><button disabled={busy || !draft.content.trim() || !draft.appliesWhen.trim()} onClick={() => onMutate('edit')} type="button">保存新版本</button><button disabled={busy} onClick={() => onDraft(null)} type="button">取消</button></div></article>
  return <article className="rounded-2xl border border-stone-200 p-4"><div className="flex flex-wrap gap-2"><span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-black text-violet-800">{kindLabel[memory.kind]}</span><span className="rounded-full bg-stone-100 px-2 py-1 text-[11px] font-bold">{memory.review_status}</span></div><p className="mt-3 whitespace-pre-wrap text-sm font-semibold leading-6">{memory.content}</p><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-500">适用条件：{memory.applies_when}</p><div className="mt-3 flex flex-wrap gap-2"><button disabled={busy} onClick={() => onDraft({ memoryId: memory.memory_id, kind: memory.kind, content: memory.content, appliesWhen: memory.applies_when })} type="button">编辑</button>{memory.review_status === 'pending' ? <><button disabled={busy} onClick={() => onMutate('confirm')} type="button">确认启用</button><button disabled={busy} onClick={() => onMutate('dismiss')} type="button">忽略</button></> : null}{memory.review_status === 'active' ? <button disabled={busy} onClick={() => onMutate('pause')} type="button">暂停</button> : null}{memory.review_status === 'paused' ? <button disabled={busy} onClick={() => onMutate('resume')} type="button">恢复</button> : null}</div></article>
}

function parseDelta(raw: string): { deltaIndex: number; delta: string } | null {
  try {
    const value = JSON.parse(raw) as unknown
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
    const row = value as Record<string, unknown>
    if (Object.keys(row).sort().join(',') !== 'delta,delta_index,run_id') return null
    if (typeof row.delta !== 'string' || typeof row.delta_index !== 'number' || !Number.isInteger(row.delta_index) || row.delta_index < 1 || typeof row.run_id !== 'string' || !/^run_[0-9A-HJKMNP-TV-Z]{26}$/.test(row.run_id)) return null
    return { deltaIndex: row.delta_index, delta: row.delta }
  } catch {
    return null
  }
}

function mergeMessages(current: ConversationMessage[], incoming: ConversationMessage[]): ConversationMessage[] {
  const byId = new Map(current.map((item) => [item.message_id, item]))
  for (const item of incoming) byId.set(item.message_id, item)
  return [...byId.values()].sort((left, right) => left.turn_index - right.turn_index || left.created_at.localeCompare(right.created_at))
}

function message(reason: unknown, fallback: string): string {
  if (reason instanceof G5ApiError) {
    if (reason.code === 'QUOTA_EXHAUSTED') return '今日 50 轮真实模型额度已用完，请在 UTC 次日重置后继续。'
    if (reason.code === 'CONCURRENT_TURN_LIMIT') return '当前账号已有一轮正在运行，请等待它完成。'
    return reason.message
  }
  return fallback
}
