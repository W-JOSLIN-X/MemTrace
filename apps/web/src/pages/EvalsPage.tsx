const groups = [
  ['G1 基础任务', 24],
  ['G2/G3 记忆质量', 60],
  ['G4 Pack 与安全', 12],
  ['G4 冲突裁决', 8],
] as const

export function EvalsPage() {
  return <main className="page-shell" aria-labelledby="eval-title">
    <header className="page-heading"><p className="eyebrow">Day 5 · G4</p><h1 id="eval-title">评测清单</h1><p>只读展示冻结 manifest；Day 5 不提供动态评测 API，未运行的指标明确显示 N/A。</p></header>
    <section className="memory-detail" aria-label="冻结评测分组"><table><thead><tr><th>分组</th><th>冻结数量</th><th>本页运行指标</th></tr></thead><tbody>{groups.map(([name, count]) => <tr key={name}><td>{name}</td><td>{count}</td><td>N/A</td></tr>)}</tbody></table><p>划分算法：g4_split_v1。实际 REST Eval 结果以所有者集成报告为准。</p></section>
  </main>
}
