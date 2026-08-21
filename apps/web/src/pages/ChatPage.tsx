import { useState } from 'react'

const pendingStages = [
  { label: '任务指纹', detail: '识别任务类型与编程语言' },
  { label: '公开计划', detail: '展示下一步动作，不暴露私有推理' },
  { label: '静态工具', detail: '仅解析 Python AST，不执行代码' },
  { label: '流式结果', detail: '实时呈现 Agent 的回答' },
]

export function ChatPage() {
  const [taskText, setTaskText] = useState('')

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section
        aria-labelledby="chat-title"
        className="overflow-hidden rounded-[2rem] border border-stone-200 bg-white shadow-sm"
      >
        <div className="border-b border-stone-200 bg-[linear-gradient(135deg,#f0fdf4_0%,#fff_56%,#fff7ed_100%)] px-6 py-8 sm:px-8">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-emerald-700 px-3 py-1 text-xs font-black text-white">
              Day 1 · UI 骨架
            </span>
            <span className="text-xs font-bold text-slate-500">
              G0 Agent 闭环
            </span>
          </div>
          <h1
            className="mt-5 max-w-2xl text-3xl font-black leading-tight tracking-tight text-slate-950 sm:text-4xl"
            id="chat-title"
          >
            把编程问题交给 Agent，观察它如何完成任务
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
            当前步骤只建立可运行的页面和交互容器。任务提交、SSE
            事件与断线恢复将在下一实施步骤接入。
          </p>
        </div>

        <div className="p-5 sm:p-8">
          <label
            className="text-sm font-black text-slate-800"
            htmlFor="task-text"
          >
            编程任务
          </label>
          <textarea
            className="mt-3 min-h-44 w-full resize-y rounded-2xl border border-stone-300 bg-stone-50 px-4 py-4 font-mono text-sm leading-6 text-slate-900 outline-none transition focus:border-emerald-600 focus:bg-white focus:ring-4 focus:ring-emerald-100"
            id="task-text"
            maxLength={20000}
            onChange={(event) => setTaskText(event.target.value)}
            placeholder="例如：请检查这段 Python 代码为什么会出现 IndexError……"
            value={taskText}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs font-semibold text-slate-500">
              {taskText.length.toLocaleString('zh-CN')} / 20,000 字符
            </span>
            <button
              aria-describedby="submit-status"
              className="cursor-not-allowed rounded-xl bg-slate-200 px-5 py-3 text-sm font-black text-slate-500"
              disabled
              type="button"
            >
              接入后即可运行
            </button>
          </div>
          <p className="sr-only" id="submit-status">
            Day 1 Step 4 仅完成页面骨架，任务提交将在 Step 5 开放。
          </p>

          <div className="mt-8 border-t border-stone-200 pt-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-black text-slate-900">运行轨迹</h2>
              <span className="text-xs font-bold text-slate-400">等待任务</span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {pendingStages.map((stage, index) => (
                <article
                  className="rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-4"
                  key={stage.label}
                >
                  <div className="flex items-start gap-3">
                    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-white text-xs font-black text-slate-400 shadow-sm ring-1 ring-stone-200">
                      {index + 1}
                    </span>
                    <div>
                      <h3 className="text-sm font-black text-slate-700">
                        {stage.label}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        {stage.detail}
                      </p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <aside className="space-y-4" aria-label="运行说明">
        <section className="rounded-3xl border border-emerald-100 bg-emerald-50 p-5">
          <p className="text-xs font-black uppercase tracking-[0.2em] text-emerald-700">
            Memory status
          </p>
          <h2 className="mt-3 text-lg font-black text-emerald-950">
            尚无长期记忆
          </h2>
          <p className="mt-2 text-sm leading-6 text-emerald-900/70">
            Day 1 不进行记忆提取或检索。这里保留真实状态，不展示伪造记忆。
          </p>
        </section>

        <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-black text-slate-900">本阶段安全边界</h2>
          <ul className="mt-4 space-y-3 text-sm text-slate-600">
            <BoundaryItem>不在浏览器中存放模型密钥</BoundaryItem>
            <BoundaryItem>不执行用户提交的 Python 代码</BoundaryItem>
            <BoundaryItem>不展示模型私有思维过程</BoundaryItem>
          </ul>
        </section>
      </aside>
    </div>
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
