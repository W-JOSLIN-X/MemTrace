import { useEffect, useState } from 'react'

import { publicApi } from '../auth/api'
import type { SystemInfo } from '../auth/types'
import { day7EvalArtifact } from '../release/evalArtifact'

const gateLabels = {
  provider_preflight: '真实 Provider 六项预检',
  validation_semantic: '冻结 validation 集',
  semantic_test: '冻结 untouched test',
  memory_ab: '记忆效果 A/B',
  four_baselines: '四基线真实工作流',
} as const

const baselineLabels = {
  no_memory: '无记忆',
  full_history: '完整历史',
  retrieval_only: '仅检索',
  memtrace: 'MemTrace',
} as const

export function EvalsPage() {
  const artifact = day7EvalArtifact
  const [system, setSystem] = useState<SystemInfo | null>(null)
  const passed = artifact.release_status === 'passed' && artifact.metrics !== null
  const semanticPassed = artifact.release_status === 'semantic_gates_passed'

  useEffect(() => {
    const controller = new AbortController()
    void publicApi.system(controller.signal).then(setSystem).catch(() => undefined)
    return () => controller.abort()
  }, [])

  return (
    <main className="page-shell" aria-labelledby="eval-title">
      <header className="page-heading">
        <p className="eyebrow">Day 7 · Release evidence</p>
        <h1 id="eval-title">真实模型评测</h1>
        <p>本页只读展示冻结 artifact，不提供会产生模型费用的动态运行按钮。</p>
      </header>

      <section className="memory-detail" aria-labelledby="eval-release-status">
        <h2 id="eval-release-status">发布状态</h2>
        <p role="status">
          {passed
            ? `已在 ${artifact.model} 上完成全部冻结真实语义门禁；产品发布状态以所有者发布报告为准。`
            : semanticPassed
              ? `已在 ${artifact.model} 上完成真实语义门禁；产品发布状态以所有者发布报告中的本机 Docker、双浏览器与安全门禁为准。`
            : artifact.release_status === 'failed'
              ? '真实语义门禁失败，当前构建不可发布。'
              : '真实 DeepSeek 发布门禁尚未执行完，当前构建不可发布。'}
        </p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <Info label="当前运行 revision" value={system?.revision ?? '正在读取已认证运行时'} />
          {artifact.candidate_commit ? (
            <Info label="评测基线提交" value={artifact.candidate_commit} />
          ) : null}
          <Info label="冻结模型" value={artifact.model ?? '等待真实 Provider 预检'} />
          <Info label="数据划分" value={artifact.split} />
          <Info label="生成时间" value={artifact.generated_at ?? '等待真实评测'} />
        </dl>
      </section>

      <section className="memory-detail" aria-labelledby="eval-gates">
        <h2 id="eval-gates">门禁进度</h2>
        <table>
          <thead><tr><th>门禁</th><th>完成</th><th>状态</th><th>失败代码</th></tr></thead>
          <tbody>
            {Object.entries(artifact.gates).map(([key, gate]) => (
              <tr key={key}>
                <td>{gateLabels[key as keyof typeof gateLabels]}</td>
                <td>{gate.completed} / {gate.expected}</td>
                <td>{statusLabel(gate.status)}</td>
                <td>{gate.failure_code ?? '无'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {artifact.selected_config ? (
        <section className="memory-detail" aria-labelledby="eval-config">
          <h2 id="eval-config">
            {artifact.config_selection === 'validation_grid_v1'
              ? '由 validation 网格选择的冻结配置'
              : '当前冻结配置（单配置 validation）'}
          </h2>
          <p>
            自动激活阈值 {artifact.selected_config.auto_activate_threshold.toFixed(2)}；
            单卡 {artifact.selected_config.per_card_token_budget} token；
            单轮总计 {artifact.selected_config.total_token_budget} token。
          </p>
        </section>
      ) : null}

      {artifact.metrics ? (
        <section className="memory-detail" aria-labelledby="eval-metrics">
          <h2 id="eval-metrics">核心结果</h2>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Info label="untouched test" value={`${artifact.metrics.untouched_test_passes} / ${artifact.metrics.untouched_test_expected}`} />
            <Info label="记忆激活 precision" value={`${(artifact.metrics.activation_precision * 100).toFixed(1)}%`} />
            <Info label="安全误激活" value={String(artifact.metrics.safety_false_activations)} />
            <Info label="A/B memory-on 胜出" value={`${artifact.metrics.memory_ab_wins} / ${artifact.metrics.memory_ab_cases}`} />
            <Info label="MemTrace 不劣于对照" value={`${artifact.metrics.memtrace_not_worse_cases} / ${artifact.metrics.memtrace_comparison_cases}`} />
            <Info label="p95 首 token" value={`${artifact.metrics.p95_first_token_ms.toFixed(0)} ms`} />
            <Info label="p95 总时延" value={`${artifact.metrics.p95_total_latency_ms.toFixed(0)} ms`} />
            <Info label="MemTrace 输入 token 中位数" value={String(artifact.metrics.memtrace_median_input_tokens)} />
            <Info label="完整历史输入 token 中位数" value={String(artifact.metrics.full_history_median_input_tokens)} />
          </dl>
        </section>
      ) : null}

      {artifact.baselines.length ? (
        <section className="memory-detail" aria-labelledby="eval-baselines">
          <h2 id="eval-baselines">四基线</h2>
          <table>
            <thead><tr><th>模式</th><th>完成</th><th>质量通过</th><th>输入 token 中位数</th><th>TTFT 中位数</th><th>p95 总时延</th></tr></thead>
            <tbody>{artifact.baselines.map((item) => <tr key={item.baseline}><td>{baselineLabels[item.baseline]}</td><td>{item.completed} / {item.expected}</td><td>{item.quality_passes}</td><td>{item.median_input_tokens}</td><td>{item.median_first_token_ms.toFixed(0)} ms</td><td>{item.p95_latency_ms.toFixed(0)} ms</td></tr>)}</tbody>
          </table>
        </section>
      ) : null}

      <section className="memory-detail" aria-labelledby="eval-provenance">
        <h2 id="eval-provenance">数据来源</h2>
        <p className="break-all">语义 fixture SHA-256：{artifact.semantic_fixture_sha256}</p>
        <p className="break-all">A/B fixture SHA-256：{artifact.ab_fixture_sha256}</p>
        <p className="break-all">四基线 fixture SHA-256：{artifact.baseline_fixture_sha256}</p>
        <p>原始对话、盲评正文和 Provider 响应保存在 Git 忽略目录，本 artifact 只包含聚合指标和受控失败代码。</p>
      </section>
    </main>
  )
}

function statusLabel(value: 'not_run' | 'passed' | 'failed'): string {
  return { not_run: '未执行', passed: '通过', failed: '失败' }[value]
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-stone-50 px-3 py-3"><dt className="text-xs font-bold text-slate-500">{label}</dt><dd className="mt-1 break-all text-sm font-black">{value}</dd></div>
}
