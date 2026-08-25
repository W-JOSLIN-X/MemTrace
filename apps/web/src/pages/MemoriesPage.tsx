import { useEffect, useRef, useState } from 'react'

import { browserG0Api, newIdempotencyKey } from '../g0/api'
import type { MemoryCard, MemoryDetailResponse, MemoryId, MemoryUsage, MemoryVersionProjection } from '../g0/types'

export function MemoriesPage() {
  const [cards, setCards] = useState<MemoryCard[]>([])
  const [detail, setDetail] = useState<MemoryDetailResponse | null>(null)
  const [draft, setDraft] = useState('')
  const [versions, setVersions] = useState<MemoryVersionProjection[]>([])
  const [usages, setUsages] = useState<MemoryUsage[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const detailAbortRef = useRef<AbortController | null>(null)
  const operationKeysRef = useRef(new Map<string, string>())

  useEffect(() => {
    const controller = new AbortController()
    const operationKeys = operationKeysRef.current
    void Promise.all([
      browserG0Api.listMemories?.({ status: 'active' }, controller.signal),
      browserG0Api.listMemories?.({ status: 'paused' }, controller.signal),
    ])
      .then(([active, paused]) => {
        setCards([...(active?.items ?? []), ...(paused?.items ?? [])])
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(publicMessage(reason))
      })
    return () => {
      controller.abort()
      detailAbortRef.current?.abort()
      operationKeys.clear()
    }
  }, [])

  async function open(memoryId: MemoryId) {
    setError(null)
    detailAbortRef.current?.abort()
    const controller = new AbortController()
    detailAbortRef.current = controller
    try {
      const [response, versionPage, usagePage] = await Promise.all([
        browserG0Api.getMemory?.(memoryId, controller.signal),
        browserG0Api.getMemoryVersions?.(memoryId, undefined, controller.signal),
        browserG0Api.getMemoryUsages?.(memoryId, undefined, controller.signal),
      ])
      if (response) {
        setDetail(response)
        setDraft(response.card.rule)
        setVersions(versionPage?.items ?? response.versions)
        setUsages(usagePage?.items ?? [])
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(publicMessage(reason))
    }
  }

  async function save() {
    if (!detail?.card.current_version_id || !browserG0Api.editMemory) return
    setBusy(true)
    setError(null)
    const operationId = `${detail.card.memory_id}:edit`
    const key = operationKeysRef.current.get(operationId) ?? newIdempotencyKey()
    operationKeysRef.current.set(operationId, key)
    try {
      const updated = await browserG0Api.editMemory(
        detail.card.memory_id,
        {
          expected_current_version_id: detail.card.current_version_id,
          patch: { rule: draft },
        },
        key,
      )
      operationKeysRef.current.delete(operationId)
      setDetail(updated)
      replaceCard(updated.card)
    } catch (reason) {
      setError(publicMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function changeState(action: 'pause' | 'resume') {
    if (!detail?.card.current_version_id) return
    const operation = action === 'pause' ? browserG0Api.pauseMemory : browserG0Api.resumeMemory
    if (!operation) return
    setBusy(true)
    setError(null)
    const operationId = `${detail.card.memory_id}:${action}`
    const key = operationKeysRef.current.get(operationId) ?? newIdempotencyKey()
    operationKeysRef.current.set(operationId, key)
    try {
      const updated = await operation(
        detail.card.memory_id,
        detail.card.current_version_id,
        key,
      )
      operationKeysRef.current.delete(operationId)
      setDetail(updated)
      replaceCard(updated.card)
    } catch (reason) {
      setError(publicMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  function replaceCard(card: MemoryCard) {
    setCards((current) =>
      current.map((item) => (item.memory_id === card.memory_id ? card : item)),
    )
  }

  return (
    <main className="page-shell memory-page" aria-labelledby="memory-title">
      <header className="page-heading">
        <p className="eyebrow">Day 4 · G3</p>
        <h1 id="memory-title">活跃记忆</h1>
        <p>这里只管理 active/paused 卡片、不可变版本和使用计数；搜索、合并与删除不在 Day 4 范围。</p>
      </header>
      {error ? <p role="alert" className="error-banner">{error}</p> : null}
      <div className="memory-layout">
        <section aria-label="记忆列表" className="memory-list">
          {cards.length === 0 ? <p>当前没有 active 或 paused 记忆。</p> : cards.map((card) => (
            <button key={card.memory_id} type="button" onClick={() => void open(card.memory_id)}>
              <strong>{card.title}</strong>
              <span>{card.status} · 注入 {card.injected_count} 次</span>
            </button>
          ))}
        </section>
        {detail ? (
          <section aria-label="记忆详情" className="memory-detail">
            <h2>{detail.card.title}</h2>
            <p>状态：{detail.card.status} · 当前版本：v{detail.card.version}</p>
            <label htmlFor="memory-rule">规则</label>
            <textarea id="memory-rule" value={draft} onChange={(event) => setDraft(event.target.value)} />
            <div className="memory-actions">
              <button type="button" disabled={busy || draft === detail.card.rule} onClick={() => void save()}>保存新版本</button>
              <button type="button" disabled={busy} onClick={() => void changeState(detail.card.status === 'active' ? 'pause' : 'resume')}>
                {detail.card.status === 'active' ? '暂停召回' : '恢复召回'}
              </button>
            </div>
            <h3>不可变版本</h3>
            <ol>{versions.map((version) => <li key={version.memory_version_id}>v{version.version} · {version.created_by_action}</li>)}</ol>
            <h3>使用记录</h3>
            {usages.length === 0 ? <p>暂无 usage receipt。</p> : (
              <ol>{usages.map((usage) => <li key={usage.usage_id}>{usage.usage_id} · {usage.verification_status} · {usage.user_effect ?? '未记录'}</li>)}</ol>
            )}
          </section>
        ) : null}
      </div>
    </main>
  )
}

function publicMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : '记忆操作失败，请稍后重试。'
}
