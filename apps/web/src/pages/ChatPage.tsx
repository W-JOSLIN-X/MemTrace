import { useMemo, useState } from 'react'

import type { G0Api } from '../g0/api'
import type { EventSourceFactory } from '../g0/eventStream'
import type { G0Phase, G0State, StageRecord } from '../g0/reducer'
import type { ResponsePolicy, Scenario, ToolCallSnapshot } from '../g0/types'
import { useG0Agent } from '../g0/useG0Agent'

export interface ChatPageProps {
  api?: G0Api
  eventSourceFactory?: EventSourceFactory
  retryDelaysMs?: readonly number[]
}

const stageDefinitions = [
  { key: 'fingerprinting', label: '任务指纹', detail: '识别任务类型与编程语言' },
  { key: 'retrieving', label: '记忆检索', detail: 'Day 1 明确返回空长期记忆' },
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
}: ChatPageProps) {
  const [taskText, setTaskText] = useState('')
  const [scenario, setScenario] = useState<Scenario>('programming_learning')
  const [responsePolicy, setResponsePolicy] =
    useState<ResponsePolicy>('default')
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const { state, submitTask, retryConnection } = useG0Agent({
    api,
    eventSourceFactory,
    retryDelaysMs,
  })
  const trimmedScalarLength = useMemo(
    () => [...taskText.trim()].length,
    [taskText],
  )
  const invalidLength = trimmedScalarLength === 0 || trimmedScalarLength > 20000
  const isSubmitting = state.phase === 'submitting'
  const hasActiveRun =
    state.taskId !== null && !state.terminal && state.phase !== 'connection_failed'

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (invalidLength || isSubmitting) return
    void submitTask(taskText, {
      scenario,
      memoryMode: memoryEnabled ? 'on' : 'off',
      responsePolicy,
    })
  }

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

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-black text-slate-700">
                使用场景
                <select
                  className="mt-2 w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-sm font-semibold outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-100"
                  onChange={(event) => setScenario(event.target.value as Scenario)}
                  value={scenario}
                >
                  <option value="programming_learning">编程学习</option>
                  <option value="software_development">软件开发</option>
                  <option value="general_text">通用文本</option>
                  <option value="other">其他</option>
                </select>
              </label>
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
                开启记忆检索
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
              disabled={invalidLength || isSubmitting}
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

function RunTimeline({ state }: { state: G0State }) {
  const completedStages = new Map(
    state.stages.map((stage) => [stage.stage, stage] as const),
  )
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
          const isCurrent = state.runStatus === definition.key
          return (
            <li
              className={
                record
                  ? 'rounded-2xl border border-emerald-200 bg-emerald-50 p-4'
                  : isCurrent
                    ? 'rounded-2xl border border-blue-200 bg-blue-50 p-4'
                    : 'rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-4'
              }
              key={definition.key}
            >
              <div className="flex items-start gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-white text-xs font-black text-slate-500 shadow-sm ring-1 ring-stone-200">
                  {record ? '✓' : index + 1}
                </span>
                <div>
                  <h3 className="text-sm font-black text-slate-700">
                    {definition.label}
                  </h3>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    {stageDescription(record, definition.detail)}
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

function stageDescription(record: StageRecord | undefined, fallback: string) {
  if (!record) return fallback
  const labels: Record<string, string> = {
    fingerprinting_task: '正在生成确定性任务指纹',
    retrieving_memory: '检索完成：Day 1 尚无长期记忆',
    publishing_plan: '公开计划已发布',
    running_static_tool: '白名单静态工具正在运行',
    generating_answer: '正在接收模型回答',
    run_failed: '运行在此阶段失败',
  }
  return labels[record.progressLabel] ?? fallback
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
          Agent 回答
        </h2>
        <span className="text-xs font-bold text-slate-400">
          {state.endOffset.toLocaleString('zh-CN')} UTF-8 bytes
        </span>
      </div>
      <pre
        aria-busy={busy}
        aria-live="polite"
        className="mt-4 min-h-24 whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-200"
      >
        {state.output || (busy ? '等待模型输出…' : '暂无输出')}
      </pre>
    </section>
  )
}

function RunSidebar({ state }: { state: G0State }) {
  return (
    <aside className="space-y-4" aria-label="运行说明与指标">
      <section className="rounded-3xl border border-emerald-100 bg-emerald-50 p-5">
        <p className="text-xs font-black uppercase tracking-[0.2em] text-emerald-700">
          Memory status
        </p>
        <h2 className="mt-3 text-lg font-black text-emerald-950">尚无长期记忆</h2>
        <p className="mt-2 text-sm leading-6 text-emerald-900/70">
          {state.effectiveMemoryMode === 'off'
            ? '本次任务已关闭记忆。'
            : 'Day 1 会执行空检索，但不会提取或保存长期记忆。'}
        </p>
      </section>

      {state.fingerprintSummary ? (
        <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-black text-slate-900">任务指纹</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            <InfoChip>{state.fingerprintSummary.domain}</InfoChip>
            <InfoChip>{state.fingerprintSummary.task_type}</InfoChip>
            <InfoChip>{state.fingerprintSummary.language}</InfoChip>
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
