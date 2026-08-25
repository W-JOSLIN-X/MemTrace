import { useCallback, useEffect, useRef, useState } from 'react'

import { browserG0Api, newIdempotencyKey } from '../g0/api'
import type { ConflictDetailResponse, ConflictResolveRequest, ImportCommitResponse, MemoryListOptions, MemoryPackDocument, PackPreviewResponse } from '../g0/g4'
import type { MemoryCard, MemoryDetailResponse, MemoryId, MemoryRelation, MemoryUsage, MemoryVersionDiffResponse, MemoryVersionProjection } from '../g0/types'

export function MemoriesPage() {
  const [cards, setCards] = useState<MemoryCard[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [filters, setFilters] = useState<MemoryListOptions>({ sort: 'updated_desc' })
  const [detail, setDetail] = useState<MemoryDetailResponse | null>(null)
  const [draft, setDraft] = useState('')
  const [versions, setVersions] = useState<MemoryVersionProjection[]>([])
  const [usages, setUsages] = useState<MemoryUsage[]>([])
  const [relations, setRelations] = useState<MemoryRelation[]>([])
  const [diff, setDiff] = useState<MemoryVersionDiffResponse | null>(null)
  const [conflicts, setConflicts] = useState<MemoryRelation[]>([])
  const [conflict, setConflict] = useState<ConflictDetailResponse | null>(null)
  const [mergeTitle, setMergeTitle] = useState('')
  const [mergeRule, setMergeRule] = useState('')
  const [preview, setPreview] = useState<PackPreviewResponse | null>(null)
  const [importResult, setImportResult] = useState<ImportCommitResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const keysRef = useRef(new Map<string, string>())

  const clearPrivateState = useCallback(() => {
    abortRef.current?.abort()
    setCards([]); setCursor(null); setDetail(null); setDraft(''); setVersions([])
    setUsages([]); setRelations([]); setDiff(null); setConflicts([]); setConflict(null)
    setMergeTitle(''); setMergeRule(''); setPreview(null); setImportResult(null)
    keysRef.current.clear()
  }, [])

  const load = useCallback(async (append = false) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const page = await browserG0Api.listMemories?.({ ...filters, cursor: append ? cursor ?? undefined : undefined }, controller.signal)
      if (!page) return
      setCards((current) => append ? [...current, ...page.items] : page.items)
      setCursor(page.next_cursor); setError(null)
    } catch (reason) {
      if (!controller.signal.aborted) setError(message(reason))
    }
  }, [cursor, filters])

  useEffect(() => {
    const operationKeys = keysRef.current
    const initialLoad = globalThis.setTimeout(() => void load(), 0)
    const sessionChanged = () => { clearPrivateState(); queueMicrotask(() => void load()) }
    globalThis.addEventListener('memtrace:session-changed', sessionChanged)
    return () => {
      globalThis.clearTimeout(initialLoad)
      globalThis.removeEventListener('memtrace:session-changed', sessionChanged)
      abortRef.current?.abort()
      operationKeys.clear()
    }
  }, [clearPrivateState, load])

  async function open(memoryId: MemoryId) {
    abortRef.current?.abort()
    const controller = new AbortController(); abortRef.current = controller
    try {
      const [card, versionPage, usagePage, relationPage] = await Promise.all([
        browserG0Api.getMemory?.(memoryId, controller.signal),
        browserG0Api.getMemoryVersions?.(memoryId, undefined, controller.signal),
        browserG0Api.getMemoryUsages?.(memoryId, undefined, controller.signal),
        browserG0Api.getMemoryRelations?.(memoryId, undefined, controller.signal),
      ])
      if (!card) return
      setDetail(card); setDraft(card.card.rule); setVersions(versionPage?.items ?? card.versions)
      setUsages(usagePage?.items ?? []); setRelations(relationPage?.items ?? card.relations); setDiff(null)
    } catch (reason) { if (!controller.signal.aborted) setError(message(reason)) }
  }

  async function operation(id: string, action: (key: string) => Promise<void>) {
    setBusy(true); setError(null)
    const key = keysRef.current.get(id) ?? newIdempotencyKey(); keysRef.current.set(id, key)
    try { await action(key); keysRef.current.delete(id) } catch (reason) { setError(message(reason)) } finally { setBusy(false) }
  }

  function accept(updated: MemoryDetailResponse) {
    setDetail(updated); setDraft(updated.card.rule)
    setCards((current) => current.map((item) => item.memory_id === updated.card.memory_id ? updated.card : item))
  }

  async function save() {
    const card = detail?.card
    if (!card?.current_version_id || !browserG0Api.editMemory) return
    await operation(`${card.memory_id}:edit`, async (key) => accept(await browserG0Api.editMemory!(card.memory_id, { expected_current_version_id: card.current_version_id!, patch: { rule: draft } }, key)))
  }

  async function lifecycle(action: 'pause' | 'resume' | 'archive' | 'restore') {
    const card = detail?.card
    if (!card?.current_version_id) return
    const method = { pause: browserG0Api.pauseMemory, resume: browserG0Api.resumeMemory, archive: browserG0Api.archiveMemory, restore: browserG0Api.restoreMemory }[action]
    if (!method) return
    await operation(`${card.memory_id}:${action}`, async (key) => accept(await method(card.memory_id, card.current_version_id!, key)))
  }

  async function removeMemory() {
    const card = detail?.card
    if (!card?.current_version_id || !browserG0Api.deleteMemory || !confirm(`永久删除“${card.title}”？此操作不可撤销。`)) return
    await operation(`${card.memory_id}:delete`, async (key) => {
      await browserG0Api.deleteMemory!(card.memory_id, card.current_version_id!, card.title, key)
      setCards((current) => current.filter((item) => item.memory_id !== card.memory_id)); setDetail(null); setDraft('')
    })
  }

  async function removeSourceTask() {
    const taskId = detail?.evidence.find((item) => item.task_id)?.task_id
    if (!taskId || !browserG0Api.deleteSourceTask || !confirm(`删除来源任务 ${taskId} 的正文与派生证据？`)) return
    await operation(`${taskId}:delete`, async (key) => {
      const result = await browserG0Api.deleteSourceTask!(taskId, key)
      setError(`来源任务已删除，${result.affected_card_count} 张卡已标记证据缺失。`)
      if (detail) await open(detail.card.memory_id)
    })
  }

  async function showDiff(from: string, to: string) {
    if (!detail || !browserG0Api.getMemoryVersionDiff) return
    try { setDiff(await browserG0Api.getMemoryVersionDiff(detail.card.memory_id, from, to)) } catch (reason) { setError(message(reason)) }
  }

  async function loadConflicts() {
    try { setConflicts((await browserG0Api.listMemoryConflicts?.('unresolved'))?.items ?? []) } catch (reason) { setError(message(reason)) }
  }

  async function openConflict(relationId: string) {
    try { setConflict(await browserG0Api.getMemoryConflict?.(relationId) ?? null); setMergeTitle(''); setMergeRule('') } catch (reason) { setError(message(reason)) }
  }

  async function resolve(action: ConflictResolveRequest['action']) {
    if (!conflict || !browserG0Api.resolveMemoryConflict) return
    const request: ConflictResolveRequest = {
      expected_relation_status: 'unresolved', action,
      left_expected_current_version_id: conflict.left.current_version_id!, right_expected_current_version_id: conflict.right.current_version_id!,
    }
    if (action === 'prefer') request.preferred_memory_id = conflict.left.memory_id
    if (action === 'separate_scopes') {
      request.left_scope = { ...conflict.left.scope, project_key: 'left-resolution' }
      request.right_scope = { ...conflict.right.scope, project_key: 'right-resolution' }
    }
    if (action === 'merge') {
      if (!mergeTitle.trim() || !mergeRule.trim()) { setError('合并标题和规则必须由用户填写，系统不会自动生成。'); return }
      request.merged_card = { kind: conflict.left.kind, title: mergeTitle, rule: mergeRule, avoid: '', trigger_text: '', scope: conflict.left.scope, exceptions: [] }
    }
    await operation(`${conflict.relation.relation_id}:${action}`, async (key) => {
      await browserG0Api.resolveMemoryConflict!(conflict.relation.relation_id, request, key)
      setConflict(null); await loadConflicts(); await load()
    })
  }

  async function exportPack() {
    if (!browserG0Api.exportMemoryPack || cards.length === 0) return
    const exportableIds = cards
      .filter((card) => !['candidate', 'rejected', 'deleted'].includes(card.status) && card.current_version_id !== null)
      .map((card) => card.memory_id)
    if (exportableIds.length === 0) {
      setError('当前结果中没有可导出的已版本化记忆。')
      return
    }
    await operation('pack:export', async (key) => download(await browserG0Api.exportMemoryPack!(exportableIds, 'MemTrace export', '', key)))
  }

  async function previewFile(file: File | null) {
    if (!file || !browserG0Api.previewMemoryPack) return
    const bytes = new Uint8Array(await file.arrayBuffer())
    await operation('pack:preview', async (key) => { setPreview(await browserG0Api.previewMemoryPack!(bytes, key)); setImportResult(null) })
  }

  async function commitPack() {
    if (!preview || !browserG0Api.commitMemoryPack) return
    await operation('pack:commit', async (key) => {
      setImportResult(await browserG0Api.commitMemoryPack!(preview.batch_id, preview.preview_token, key)); setPreview(null); await load()
    })
  }

  return <main className="page-shell memory-page" aria-labelledby="memory-title">
    <header className="page-heading"><p className="eyebrow">Day 5 · G4</p><h1 id="memory-title">记忆中心</h1><p>搜索、Diff、关系、冲突、匿名 Pack、生命周期和删除均以当前用户的持久化状态为准。</p></header>
    {error ? <p role="alert" className="error-banner">{error}</p> : null}
    <section aria-label="搜索和筛选" className="memory-actions">
      <input aria-label="搜索记忆" placeholder="标题、规则或触发词" value={filters.query ?? ''} onChange={(event) => setFilters({ ...filters, query: event.target.value || undefined })} />
      <select aria-label="状态筛选" value={filters.status ?? ''} onChange={(event) => setFilters({ ...filters, status: (event.target.value || undefined) as MemoryListOptions['status'] })}><option value="">全部状态</option><option value="active">active</option><option value="paused">paused</option><option value="archived">archived</option><option value="conflicted">conflicted</option></select>
      <select aria-label="排序" value={filters.sort} onChange={(event) => setFilters({ ...filters, sort: event.target.value as MemoryListOptions['sort'] })}><option value="updated_desc">最近更新</option><option value="created_desc">最近创建</option><option value="last_used_desc">最近使用</option><option value="title_asc">标题</option></select>
      <button type="button" onClick={() => void load()}>应用</button><button type="button" onClick={() => void loadConflicts()}>未解决冲突</button>
    </section>
    <div className="memory-layout">
      <section aria-label="记忆列表" className="memory-list">{cards.length ? cards.map((card) => <button key={card.memory_id} type="button" onClick={() => void open(card.memory_id)}><strong>{card.title}</strong><span>{card.status} · {card.kind} · 注入 {card.injected_count} 次</span></button>) : <p>没有符合条件的记忆。</p>}{cursor ? <button type="button" onClick={() => void load(true)}>下一页</button> : null}</section>
      {detail ? <section aria-label="记忆详情" className="memory-detail"><h2>{detail.card.title}</h2><p>状态：{detail.card.status} · v{detail.card.version} · 来源：{detail.card.source_type}</p>{detail.card.evidence_missing ? <p>来源证据已删除。</p> : null}<label htmlFor="memory-rule">规则</label><textarea id="memory-rule" value={draft} onChange={(event) => setDraft(event.target.value)} /><div className="memory-actions"><button disabled={busy || draft === detail.card.rule} onClick={() => void save()}>保存新版本</button>{detail.card.status === 'active' ? <button onClick={() => void lifecycle('pause')}>暂停</button> : null}{detail.card.status === 'paused' ? <button onClick={() => void lifecycle('resume')}>恢复召回</button> : null}{['active', 'paused'].includes(detail.card.status) ? <button onClick={() => void lifecycle('archive')}>归档</button> : null}{detail.card.status === 'archived' ? <button onClick={() => void lifecycle('restore')}>恢复为暂停</button> : null}<button onClick={() => void removeMemory()}>永久删除</button>{detail.evidence.some((item) => item.task_id) ? <button onClick={() => void removeSourceTask()}>删除来源任务</button> : null}</div>
        <h3>不可变版本与 Diff</h3><ol>{versions.map((version, index) => <li key={version.memory_version_id}>v{version.version} · {version.created_by_action}{index + 1 < versions.length ? <button onClick={() => void showDiff(versions[index + 1].memory_version_id, version.memory_version_id)}>与前版比较</button> : null}</li>)}</ol>{diff ? <p>变更字段：{diff.changed_fields.join('、') || '无'}</p> : null}<h3>关系</h3><ol>{relations.map((relation) => <li key={relation.relation_id}>{relation.relation_type} · {relation.status}</li>)}</ol><h3>使用记录</h3>{usages.length ? <ol>{usages.map((usage) => <li key={usage.usage_id}>{usage.verification_status} · {usage.user_effect ?? '未反馈'}</li>)}</ol> : <p>暂无 usage receipt。</p>}</section> : null}
    </div>
    <section aria-label="冲突裁决" className="memory-detail"><h2>冲突裁决</h2>{conflicts.map((item) => <button key={item.relation_id} onClick={() => void openConflict(item.relation_id)}>{item.relation_id} · {item.status}</button>)}{conflict ? <div><p>{conflict.left.title} ↔ {conflict.right.title}</p><input aria-label="合并标题" placeholder="由用户填写合并标题" value={mergeTitle} onChange={(event) => setMergeTitle(event.target.value)} /><textarea aria-label="合并规则" placeholder="由用户填写合并规则" value={mergeRule} onChange={(event) => setMergeRule(event.target.value)} /><div className="memory-actions"><button onClick={() => void resolve('prefer')}>保留左卡</button><button onClick={() => void resolve('separate_scopes')}>拆分范围</button><button onClick={() => void resolve('merge')}>确认合并</button><button onClick={() => void resolve('pause_both')}>两张都暂停</button></div></div> : null}</section>
    <section aria-label="Memory Pack" className="memory-detail"><h2>匿名 Memory Pack</h2><button disabled={busy || !cards.length} onClick={() => void exportPack()}>下载当前结果</button><label>导入 .mempack.json<input type="file" accept="application/json,.json" onChange={(event) => void previewFile(event.target.files?.[0] ?? null)} /></label>{preview ? <div><p>合法 {preview.legal_new_count} · 重复 {preview.duplicate_count} · 潜在冲突 {preview.potential_conflict_count} · 可疑 {preview.suspicious_count}</p><ul>{preview.items.map((item) => <li key={item.external_id}>{item.title} · {item.classification} · {item.reason ?? '无受控原因'}</li>)}</ul><button onClick={() => void commitPack()}>全部以 paused 导入</button></div> : null}{importResult ? <p>已导入 {importResult.inserted_count}，跳过 {importResult.skipped_count}，警告 {importResult.warning_count}。</p> : null}</section>
  </main>
}

function download(pack: MemoryPackDocument) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(pack)], { type: 'application/json' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${pack.pack_id}.mempack.json`; anchor.click(); URL.revokeObjectURL(url)
}

function message(reason: unknown) { return reason instanceof Error ? reason.message : '记忆操作失败，请稍后重试。' }
