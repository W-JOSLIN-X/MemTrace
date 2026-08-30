import { useCallback, useEffect, useRef, useState } from 'react'

import { browserG5Api, newIdempotencyKey } from '../g5/api'
import type {
  MemoryConflictDetail,
  MemoryConflictResolveRequest,
  MemoryDetailResponse,
  MemoryId,
  MemoryKind,
  MemoryProjection,
  MemoryRelation,
  MemoryUsage,
  MemoryVersionDiffResponse,
  MemoryVersionId,
  PackCommitResponse,
  PackPreview,
  ReviewStatus,
} from '../g5/types'

type Filters = {
  query: string
  kind: MemoryKind | ''
  reviewStatus: ReviewStatus | ''
  source: 'conversation_turn' | 'user_edit' | 'import' | ''
  sort: 'newest' | 'oldest'
}

const initialFilters: Filters = {
  query: '',
  kind: '',
  reviewStatus: '',
  source: '',
  sort: 'newest',
}

export function MemoriesPage() {
  const [filters, setFilters] = useState(initialFilters)
  const [memories, setMemories] = useState<MemoryProjection[]>([])
  const [cursor, setCursor] = useState<MemoryId | null>(null)
  const [detail, setDetail] = useState<MemoryDetailResponse | null>(null)
  const [usages, setUsages] = useState<MemoryUsage[]>([])
  const [relations, setRelations] = useState<MemoryRelation[]>([])
  const [diff, setDiff] = useState<MemoryVersionDiffResponse | null>(null)
  const [draftKind, setDraftKind] = useState<MemoryKind>('preference')
  const [draftContent, setDraftContent] = useState('')
  const [draftAppliesWhen, setDraftAppliesWhen] = useState('')
  const [conflicts, setConflicts] = useState<MemoryRelation[]>([])
  const [conflict, setConflict] = useState<MemoryConflictDetail | null>(null)
  const [leftScope, setLeftScope] = useState('')
  const [rightScope, setRightScope] = useState('')
  const [mergeKind, setMergeKind] = useState<MemoryKind>('rule')
  const [mergeContent, setMergeContent] = useState('')
  const [mergeAppliesWhen, setMergeAppliesWhen] = useState('')
  const [packPreview, setPackPreview] = useState<PackPreview | null>(null)
  const [packResult, setPackResult] = useState<PackCommitResponse | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const filtersRef = useRef<Filters>(initialFilters)
  const cursorRef = useRef<MemoryId | null>(null)
  const listAbortRef = useRef<AbortController | null>(null)
  const detailAbortRef = useRef<AbortController | null>(null)
  const auxiliaryAbortRef = useRef<AbortController | null>(null)
  const operationAbortRef = useRef<AbortController | null>(null)
  const operationKeys = useRef(new Map<string, string>())

  const clearPrivateState = useCallback(() => {
    listAbortRef.current?.abort()
    detailAbortRef.current?.abort()
    auxiliaryAbortRef.current?.abort()
    operationAbortRef.current?.abort()
    filtersRef.current = initialFilters
    cursorRef.current = null
    setFilters(initialFilters)
    setMemories([])
    setCursor(null)
    setDetail(null)
    setUsages([])
    setRelations([])
    setDiff(null)
    setDraftContent('')
    setDraftAppliesWhen('')
    setConflicts([])
    setConflict(null)
    setLeftScope('')
    setRightScope('')
    setMergeContent('')
    setMergeAppliesWhen('')
    setPackPreview(null)
    setPackResult(null)
    setNotice(null)
    setError(null)
    setBusy(false)
    operationKeys.current.clear()
  }, [])

  const loadMemories = useCallback(
    async (append = false, requestedFilters?: Filters) => {
      listAbortRef.current?.abort()
      const controller = new AbortController()
      listAbortRef.current = controller
      const activeFilters = requestedFilters ?? filtersRef.current
      const activeCursor = append ? cursorRef.current : null
      try {
        const page = await browserG5Api.listMemories(
          {
            query: activeFilters.query.trim() || undefined,
            kind: activeFilters.kind || undefined,
            reviewStatus: activeFilters.reviewStatus || undefined,
            source: activeFilters.source || undefined,
            sort: activeFilters.sort,
            cursor: activeCursor ?? undefined,
          },
          controller.signal,
        )
        setMemories((current) => (append ? [...current, ...page.items] : page.items))
        cursorRef.current = page.next_cursor
        setCursor(page.next_cursor)
        setError(null)
      } catch (reason) {
        if (!controller.signal.aborted) setError(errorMessage(reason))
      }
    },
    [],
  )

  useEffect(() => {
    const pendingKeys = operationKeys.current
    const timer = globalThis.setTimeout(() => void loadMemories(false), 0)
    const sessionChanged = () => {
      clearPrivateState()
      queueMicrotask(() => void loadMemories(false))
    }
    globalThis.addEventListener('memtrace:session-changed', sessionChanged)
    return () => {
      globalThis.clearTimeout(timer)
      globalThis.removeEventListener('memtrace:session-changed', sessionChanged)
      listAbortRef.current?.abort()
      detailAbortRef.current?.abort()
      auxiliaryAbortRef.current?.abort()
      operationAbortRef.current?.abort()
      pendingKeys.clear()
    }
  }, [clearPrivateState, loadMemories])

  async function openMemory(memoryId: MemoryId) {
    detailAbortRef.current?.abort()
    const controller = new AbortController()
    detailAbortRef.current = controller
    try {
      const [nextDetail, usagePage, relationPage] = await Promise.all([
        browserG5Api.getMemory(memoryId, controller.signal),
        browserG5Api.getMemoryUsages(memoryId, undefined, controller.signal),
        browserG5Api.getMemoryRelations(memoryId, undefined, controller.signal),
      ])
      setDetail(nextDetail)
      setUsages(usagePage.items)
      setRelations(relationPage.items)
      setDraftKind(nextDetail.memory.kind)
      setDraftContent(nextDetail.memory.content)
      setDraftAppliesWhen(nextDetail.memory.applies_when)
      setDiff(null)
      setError(null)
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason))
    }
  }

  async function runOperation(
    name: string,
    operation: (key: string, signal: AbortSignal) => Promise<void>,
  ) {
    operationAbortRef.current?.abort()
    const controller = new AbortController()
    operationAbortRef.current = controller
    setBusy(true)
    setError(null)
    setNotice(null)
    const key = operationKeys.current.get(name) ?? newIdempotencyKey()
    operationKeys.current.set(name, key)
    try {
      await operation(key, controller.signal)
      operationKeys.current.delete(name)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(errorMessage(reason))
      }
    } finally {
      if (operationAbortRef.current === controller) {
        operationAbortRef.current = null
        setBusy(false)
      }
    }
  }

  async function saveMemory() {
    if (!detail) return
    const current = detail.memory
    await runOperation(`${current.memory_id}:edit`, async (key, signal) => {
      await browserG5Api.editMemory(
        current.memory_id,
        {
          kind: draftKind,
          content: draftContent.trim(),
          applies_when: draftAppliesWhen.trim(),
          expected_current_version_id: current.current_version_id,
        },
        key,
        signal,
      )
      await Promise.all([openMemory(current.memory_id), loadMemories(false)])
      setNotice('已创建新的不可变记忆版本。')
    })
  }

  async function changeLifecycle(
    action: 'confirm' | 'dismiss' | 'pause' | 'resume' | 'archive' | 'restore',
  ) {
    if (!detail) return
    const memoryId = detail.memory.memory_id
    await runOperation(`${memoryId}:${action}`, async (key, signal) => {
      await browserG5Api.changeMemory(memoryId, action, key, signal)
      await Promise.all([openMemory(memoryId), loadMemories(false)])
    })
  }

  async function compareVersions(from: MemoryVersionId, to: MemoryVersionId) {
    if (!detail) return
    auxiliaryAbortRef.current?.abort()
    const controller = new AbortController()
    auxiliaryAbortRef.current = controller
    try {
      setDiff(
        await browserG5Api.getMemoryVersionDiff(
          detail.memory.memory_id,
          from,
          to,
          controller.signal,
        ),
      )
      setError(null)
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason))
    }
  }

  async function restoreVersion(sourceVersionId: MemoryVersionId) {
    if (!detail) return
    const memory = detail.memory
    await runOperation(`${memory.memory_id}:version:${sourceVersionId}`, async (key, signal) => {
      await browserG5Api.restoreMemoryVersion(
        memory.memory_id,
        sourceVersionId,
        memory.current_version_id,
        key,
        signal,
      )
      await Promise.all([openMemory(memory.memory_id), loadMemories(false)])
      setNotice('旧版本内容已作为一个新版本恢复，历史版本没有被改写。')
    })
  }

  async function permanentlyDeleteMemory() {
    if (!detail) return
    const memory = detail.memory
    if (!globalThis.confirm(`永久删除这条记忆？\n\n${memory.content}`)) return
    await runOperation(`${memory.memory_id}:delete`, async (key, signal) => {
      await browserG5Api.deleteMemory(
        memory.memory_id,
        memory.current_version_id,
        memory.content,
        key,
        signal,
      )
      setDetail(null)
      setUsages([])
      setRelations([])
      await loadMemories(false)
      setNotice('记忆正文、版本、证据链接、usage 与 judgment 已永久删除。')
    })
  }

  async function deleteSourceTask() {
    const taskId = detail?.evidence[0]?.task_id
    if (!taskId || !globalThis.confirm(`删除来源会话 ${taskId} 的正文和派生证据？`)) return
    await runOperation(`${taskId}:delete`, async (key, signal) => {
      const result = await browserG5Api.deleteSourceTask(taskId, key, signal)
      if (detail) await openMemory(detail.memory.memory_id)
      setNotice(`来源会话已删除；${result.affected_memory_count} 条记忆被标记为证据受影响。`)
    })
  }

  async function loadConflicts() {
    auxiliaryAbortRef.current?.abort()
    const controller = new AbortController()
    auxiliaryAbortRef.current = controller
    try {
      const page = await browserG5Api.listMemoryConflicts('unresolved', controller.signal)
      setConflicts(page.items)
      setError(null)
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason))
    }
  }

  async function openConflict(relationId: string) {
    auxiliaryAbortRef.current?.abort()
    const controller = new AbortController()
    auxiliaryAbortRef.current = controller
    try {
      const next = await browserG5Api.getMemoryConflict(relationId, controller.signal)
      setConflict(next)
      setLeftScope(next.left.applies_when)
      setRightScope(next.right.applies_when)
      setMergeKind('rule')
      setMergeContent('')
      setMergeAppliesWhen('')
      setError(null)
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason))
    }
  }

  async function resolveConflict(action: MemoryConflictResolveRequest['action']) {
    if (!conflict) return
    const request: MemoryConflictResolveRequest = {
      expected_relation_status: 'unresolved',
      left_expected_current_version_id: conflict.left.current_version_id,
      right_expected_current_version_id: conflict.right.current_version_id,
      action,
    }
    if (action === 'prefer') request.preferred_memory_id = conflict.left.memory_id
    if (action === 'separate_scopes') {
      request.left_applies_when = leftScope.trim()
      request.right_applies_when = rightScope.trim()
    }
    if (action === 'merge') {
      if (!mergeContent.trim() || !mergeAppliesWhen.trim()) {
        setError('合并后的记忆内容和适用条件必须由用户填写。')
        return
      }
      request.merged_memory = {
        kind: mergeKind,
        content: mergeContent.trim(),
        applies_when: mergeAppliesWhen.trim(),
      }
    }
    await runOperation(`${conflict.relation.relation_id}:${action}`, async (key, signal) => {
      await browserG5Api.resolveMemoryConflict(
        conflict.relation.relation_id,
        request,
        key,
        signal,
      )
      setConflict(null)
      await Promise.all([loadConflicts(), loadMemories(false)])
      setNotice('冲突裁决已原子保存。')
    })
  }

  async function exportPack() {
    const exportable = memories.filter((item) => item.review_status !== 'superseded')
    if (!exportable.length) {
      setError('当前筛选结果中没有可导出的记忆。')
      return
    }
    await runOperation('pack:export', async (key, signal) => {
      const pack = await browserG5Api.exportMemoryPack(
        exportable.map((item) => item.memory_id),
        'MemTrace G5 export',
        'An anonymized MemTrace v2 memory export.',
        key,
        signal,
      )
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(pack)], { type: 'application/json' }),
      )
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${pack.pack_id}.mempack.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice(`已导出 ${pack.cards.length} 条匿名记忆。`)
    })
  }

  async function previewPack(file: File | null) {
    if (!file) return
    await runOperation('pack:preview', async (key, signal) => {
      const bytes = await readFileBytes(file)
      signal.throwIfAborted()
      const preview = await browserG5Api.previewMemoryPack(bytes, key, signal)
      setPackPreview(preview)
      setPackResult(null)
    })
  }

  async function commitPack() {
    if (!packPreview) return
    await runOperation(`pack:${packPreview.batch_id}:commit`, async (key, signal) => {
      const result = await browserG5Api.commitMemoryPack(
        packPreview.batch_id,
        packPreview.preview_token,
        key,
        signal,
      )
      setPackPreview(null)
      setPackResult(result)
      await loadMemories(false)
      setNotice('合法的新记忆已全部以 paused 状态导入。')
    })
  }

  function updateFilters(next: Filters) {
    filtersRef.current = next
    cursorRef.current = null
    setFilters(next)
  }

  const memory = detail?.memory ?? null
  const draftChanged = Boolean(
    memory &&
      (draftKind !== memory.kind ||
        draftContent !== memory.content ||
        draftAppliesWhen !== memory.applies_when),
  )

  return (
    <main className="page-shell memory-page" aria-labelledby="memory-title">
      <header className="page-heading">
        <p className="eyebrow">G5 · 公开版本</p>
        <h1 id="memory-title">记忆中心</h1>
        <p>这里只显示当前账号由真实模型提取或由用户创建的偏好、规则和经验。</p>
      </header>

      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {notice ? <p className="success-banner" role="status">{notice}</p> : null}

      <section className="memory-actions" aria-label="记忆搜索和筛选">
        <label>搜索内容或适用条件<input value={filters.query} onChange={(event) => updateFilters({ ...filters, query: event.target.value })} /></label>
        <label>类型<select value={filters.kind} onChange={(event) => updateFilters({ ...filters, kind: event.target.value as Filters['kind'] })}><option value="">全部</option><option value="preference">偏好</option><option value="rule">规则</option><option value="experience">经验</option></select></label>
        <label>状态<select value={filters.reviewStatus} onChange={(event) => updateFilters({ ...filters, reviewStatus: event.target.value as Filters['reviewStatus'] })}><option value="">全部</option><option value="pending">待确认</option><option value="active">生效</option><option value="paused">暂停</option><option value="archived">归档</option><option value="superseded">已取代</option></select></label>
        <label>来源<select value={filters.source} onChange={(event) => updateFilters({ ...filters, source: event.target.value as Filters['source'] })}><option value="">全部</option><option value="conversation_turn">对话提取</option><option value="user_edit">用户编辑</option><option value="import">Pack 导入</option></select></label>
        <label>排序<select value={filters.sort} onChange={(event) => updateFilters({ ...filters, sort: event.target.value as Filters['sort'] })}><option value="newest">最近更新</option><option value="oldest">最早创建</option></select></label>
        <button type="button" onClick={() => void loadMemories(false, filters)}>应用筛选</button>
        <button type="button" onClick={() => void loadConflicts()}>未解决冲突</button>
      </section>

      <div className="memory-layout">
        <section className="memory-list" aria-label="记忆列表">
          {memories.length === 0 ? <p>没有符合条件的记忆。</p> : null}
          {memories.map((item) => <button key={item.memory_id} type="button" onClick={() => void openMemory(item.memory_id)}><strong>{item.content}</strong><span>{kindLabel(item.kind)} · {statusLabel(item.review_status)} · 已注入 {item.injected_count} 次</span></button>)}
          {cursor ? <button type="button" onClick={() => void loadMemories(true)}>下一页</button> : null}
        </section>

        {memory && detail ? (
          <section className="memory-detail" aria-label="记忆详情">
            <h2>{kindLabel(memory.kind)}</h2>
            <p>{statusLabel(memory.review_status)} · v{memory.version} · {sourceLabel(memory.source_type)}</p>
            <p>置信度 {memory.confidence.toFixed(2)} · 召回 {memory.retrieved_count} · 注入 {memory.injected_count} · 已遵守 {memory.verified_applied_count}</p>
            <label htmlFor="memory-kind">类型</label><select id="memory-kind" value={draftKind} onChange={(event) => setDraftKind(event.target.value as MemoryKind)}><option value="preference">偏好</option><option value="rule">规则</option><option value="experience">经验</option></select>
            <label htmlFor="memory-content">内容</label><textarea id="memory-content" value={draftContent} onChange={(event) => setDraftContent(event.target.value)} />
            <label htmlFor="memory-scope">适用条件</label><textarea id="memory-scope" value={draftAppliesWhen} onChange={(event) => setDraftAppliesWhen(event.target.value)} />
            <div className="memory-actions">
              <button disabled={busy || !draftChanged || draftContent.trim().length < 4 || draftAppliesWhen.trim().length < 4} onClick={() => void saveMemory()}>保存新版本</button>
              {memory.review_status === 'pending' ? <button disabled={busy} onClick={() => void changeLifecycle('confirm')}>确认记忆</button> : null}
              {memory.review_status === 'pending' ? <button disabled={busy} onClick={() => void changeLifecycle('dismiss')}>忽略</button> : null}
              {memory.review_status === 'active' ? <button disabled={busy} onClick={() => void changeLifecycle('pause')}>暂停</button> : null}
              {memory.review_status === 'paused' ? <button disabled={busy} onClick={() => void changeLifecycle('resume')}>恢复</button> : null}
              {['active', 'paused'].includes(memory.review_status) ? <button disabled={busy} onClick={() => void changeLifecycle('archive')}>归档</button> : null}
              {memory.review_status === 'archived' ? <button disabled={busy} onClick={() => void changeLifecycle('restore')}>恢复为暂停</button> : null}
              <button disabled={busy} onClick={() => void permanentlyDeleteMemory()}>永久删除</button>
              {detail.evidence.length ? <button disabled={busy} onClick={() => void deleteSourceTask()}>删除来源会话</button> : null}
            </div>
            <h3>版本时间线</h3>
            <ol>{detail.versions.map((version, index) => <li key={version.version_id}>v{version.version} · {version.created_by_action} · {version.created_at}{index > 0 ? <button type="button" onClick={() => void compareVersions(detail.versions[index - 1].version_id, version.version_id)}>与前版比较</button> : null}{version.version_id !== memory.current_version_id ? <button type="button" disabled={busy} onClick={() => void restoreVersion(version.version_id)}>作为新版本恢复</button> : null}</li>)}</ol>
            {diff ? <div aria-label="版本 Diff"><p>变更字段：{diff.changed_fields.map(memoryFieldLabel).join('、') || '无'}</p><p>旧：{diff.from_version.content}</p><p>新：{diff.to_version.content}</p></div> : null}
            <h3>使用与效果</h3>{usages.length ? <ol>{usages.map((usage) => <li key={usage.usage_id}>{usage.verification_status} · {usage.user_effect ?? '未反馈'} · {usage.estimated_tokens} token</li>)}</ol> : <p>暂无使用记录。</p>}
            <h3>关系</h3>{relations.length ? <ol>{relations.map((relation) => <li key={relation.relation_id}>{relation.relation_type} · {relation.status}</li>)}</ol> : <p>暂无关系。</p>}
          </section>
        ) : null}
      </div>

      <section className="memory-detail" aria-label="冲突裁决">
        <h2>冲突裁决</h2>
        {conflicts.length === 0 ? <p>点击“未解决冲突”读取当前冲突。</p> : null}
        {conflicts.map((item) => <button key={item.relation_id} type="button" onClick={() => void openConflict(item.relation_id)}>{item.relation_id} · {item.status}</button>)}
        {conflict ? <div><p>左侧：{conflict.left.content}</p><p>右侧：{conflict.right.content}</p><label>左侧新适用条件<input value={leftScope} onChange={(event) => setLeftScope(event.target.value)} /></label><label>右侧新适用条件<input value={rightScope} onChange={(event) => setRightScope(event.target.value)} /></label><label>合并类型<select value={mergeKind} onChange={(event) => setMergeKind(event.target.value as MemoryKind)}><option value="preference">偏好</option><option value="rule">规则</option><option value="experience">经验</option></select></label><label>合并内容<textarea value={mergeContent} onChange={(event) => setMergeContent(event.target.value)} /></label><label>合并适用条件<textarea value={mergeAppliesWhen} onChange={(event) => setMergeAppliesWhen(event.target.value)} /></label><div className="memory-actions"><button disabled={busy} onClick={() => void resolveConflict('prefer')}>保留左侧</button><button disabled={busy || leftScope.trim().length < 4 || rightScope.trim().length < 4} onClick={() => void resolveConflict('separate_scopes')}>拆分适用条件</button><button disabled={busy} onClick={() => void resolveConflict('merge')}>按填写内容合并</button><button disabled={busy} onClick={() => void resolveConflict('pause_both')}>两条都暂停</button></div></div> : null}
      </section>

      <section className="memory-detail" aria-label="Memory Pack">
        <h2>匿名 Memory Pack</h2>
        <p>导出不会包含 owner、task、message、证据正文或本地资源 ID；外部 Pack 永远按不可信纯数据处理。</p>
        <button type="button" disabled={busy || memories.length === 0} onClick={() => void exportPack()}>下载当前筛选结果</button>
        <label>导入 Memory Pack<input type="file" accept="application/json,.json" onChange={(event) => void previewPack(event.target.files?.[0] ?? null)} /></label>
        {packPreview ? <div><p>合法新项 {packPreview.legal_new_count} · 重复 {packPreview.duplicate_count} · 潜在冲突 {packPreview.potential_conflict_count} · 可疑 {packPreview.suspicious_count}</p><ul>{packPreview.items.map((item) => <li key={item.external_id}><strong>{item.classification}</strong> · {kindLabel(item.kind)} · {item.content} · 适用：{item.applies_when} · {item.reason ?? '无受控原因'}</li>)}</ul><button type="button" disabled={busy || packPreview.legal_new_count === 0} onClick={() => void commitPack()}>全部以 paused 导入</button></div> : null}
        {packResult ? <p role="status">已导入 {packResult.inserted_count}，跳过 {packResult.skipped_count}，警告 {packResult.warning_count}。</p> : null}
      </section>
    </main>
  )
}

function kindLabel(kind: MemoryKind): string {
  return { preference: '偏好', rule: '规则', experience: '经验' }[kind]
}

function statusLabel(status: ReviewStatus): string {
  return { pending: '待确认', active: '生效', paused: '暂停', archived: '归档', superseded: '已取代' }[status]
}

function sourceLabel(source: MemoryProjection['source_type']): string {
  return { conversation_turn: '对话提取', user_edit: '用户编辑', import: 'Pack 导入' }[source]
}

function memoryFieldLabel(field: string): string {
  return { kind: '类型', content: '内容', applies_when: '适用条件' }[field] ?? field
}

function readFileBytes(file: File): Promise<ArrayBuffer> {
  const arrayBuffer = (file as File & { arrayBuffer?: () => Promise<ArrayBuffer> }).arrayBuffer
  if (arrayBuffer) return arrayBuffer.call(file)
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result)
      else reject(new Error('无法读取 Memory Pack。'))
    }
    reader.onerror = () => reject(new Error('无法读取 Memory Pack。'))
    reader.readAsArrayBuffer(file)
  })
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : '记忆操作失败，请稍后重试。'
}
