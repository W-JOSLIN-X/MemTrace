import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { browserG5Api } from '../g5/api'
import type {
  MemoryConflictDetail,
  MemoryDetailResponse,
  MemoryProjection,
  MemoryRelation,
  PackPreview,
} from '../g5/types'
import { MemoriesPage } from './MemoriesPage'

const ULID = '01J00000000000000000000001'
const ULID_2 = '01J00000000000000000000002'
const MEMORY_ID = `mem_${ULID}` as const
const OTHER_MEMORY_ID = `mem_${ULID_2}` as const
const VERSION_ID = `memver_${ULID}` as const
const OLD_VERSION_ID = `memver_${ULID_2}` as const
const AT = '2026-08-30T12:00:00Z'

afterEach(() => vi.restoreAllMocks())

describe('unified G5 Memory Center', () => {
  it('renders model text as plain text and preserves a draft plus idempotency key on retry', async () => {
    const memory = makeMemory('<img src=x onerror=alert(1)>偏好中文')
    const detail = makeDetail(memory)
    mockReads(memory, detail)
    const keys: string[] = []
    let attempt = 0
    vi.spyOn(browserG5Api, 'editMemory').mockImplementation(async (_id, _request, key) => {
      keys.push(key)
      attempt += 1
      if (attempt === 1) throw new Error('网络中断，请重试。')
      return memory
    })
    const lifecycle = vi.spyOn(browserG5Api, 'changeMemory').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-life',
      memory_id: MEMORY_ID,
      old_status: 'active',
      new_status: 'paused',
      updated_at: AT,
    })
    vi.spyOn(browserG5Api, 'getMemoryVersionDiff').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-diff',
      from_version: detail.versions[0],
      to_version: detail.versions[1],
      changed_fields: ['content'],
    })
    const user = userEvent.setup()
    render(<MemoriesPage />)

    await user.click(await screen.findByRole('button', { name: /偏好中文/ }))
    expect(await screen.findByLabelText('记忆详情')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    const editor = screen.getByLabelText('内容')
    await user.clear(editor)
    await user.type(editor, '以后优先使用简体中文回答')
    await user.click(screen.getByRole('button', { name: '保存新版本' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络中断')
    expect(editor).toHaveValue('以后优先使用简体中文回答')

    await user.click(screen.getByRole('button', { name: '保存新版本' }))
    await waitFor(() => expect(keys).toHaveLength(2))
    expect(keys[1]).toBe(keys[0])
    expect(await screen.findByText('已创建新的不可变记忆版本。')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '与前版比较' }))
    expect(await screen.findByLabelText('版本 Diff')).toHaveTextContent('变更字段：内容')
    await user.click(screen.getByRole('button', { name: '暂停' }))
    await waitFor(() =>
      expect(lifecycle).toHaveBeenCalledWith(
        MEMORY_ID,
        'pause',
        expect.any(String),
        expect.any(AbortSignal),
      ),
    )
  })

  it('appends cursor pages without an effect-driven first-page reload', async () => {
    const first = makeMemory('第一页记忆')
    const second = {
      ...makeMemory('第二页记忆'),
      memory_id: OTHER_MEMORY_ID,
    }
    const list = vi.spyOn(browserG5Api, 'listMemories').mockImplementation(async (filters) => ({
      schema_version: '2.1.0',
      request_id: filters?.cursor ? 'req-page-2' : 'req-page-1',
      items: filters?.cursor ? [second] : [first],
      next_cursor: filters?.cursor ? null : OTHER_MEMORY_ID,
    }))
    const user = userEvent.setup()
    render(<MemoriesPage />)

    expect(await screen.findByRole('button', { name: /第一页记忆/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '下一页' }))
    expect(await screen.findByRole('button', { name: /第二页记忆/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /第一页记忆/ })).toBeInTheDocument()
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
    expect(list.mock.calls[1][0]?.cursor).toBe(OTHER_MEMORY_ID)
  })

  it('requires user-authored merge content before resolving a conflict', async () => {
    const left = makeMemory('默认使用中文')
    const right = { ...makeMemory('默认使用英文'), memory_id: OTHER_MEMORY_ID }
    const relation = makeRelation()
    mockReads(left, makeDetail(left))
    vi.spyOn(browserG5Api, 'listMemoryConflicts').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-conflicts',
      items: [relation],
      next_cursor: null,
    })
    vi.spyOn(browserG5Api, 'getMemoryConflict').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-conflict',
      relation,
      left,
      right,
    } satisfies MemoryConflictDetail)
    const resolve = vi.spyOn(browserG5Api, 'resolveMemoryConflict').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-resolve',
      relation_id: relation.relation_id,
      action: 'merge',
      status: 'resolved',
      resolution_memory_id: MEMORY_ID,
    })
    const user = userEvent.setup()
    render(<MemoriesPage />)

    await user.click(await screen.findByRole('button', { name: '未解决冲突' }))
    await user.click(await screen.findByRole('button', { name: /rel_/ }))
    await user.click(screen.getByRole('button', { name: '按填写内容合并' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('必须由用户填写')

    await user.type(screen.getByLabelText('合并内容'), '根据当前任务语言选择中文或英文')
    await user.type(screen.getByLabelText('合并适用条件'), '所有需要语言选择的普通对话')
    await user.click(screen.getByRole('button', { name: '按填写内容合并' }))
    await waitFor(() => expect(resolve).toHaveBeenCalledTimes(1))
    expect(resolve.mock.calls[0][1]).toMatchObject({
      action: 'merge',
      merged_memory: {
        kind: 'rule',
        content: '根据当前任务语言选择中文或英文',
        applies_when: '所有需要语言选择的普通对话',
      },
    })
  })

  it('previews untrusted Pack data and imports only through the paused commit action', async () => {
    const memory = makeMemory('优先给出简短结论')
    mockReads(memory, makeDetail(memory))
    const preview = makePackPreview()
    vi.spyOn(browserG5Api, 'previewMemoryPack').mockResolvedValue(preview)
    const commit = vi.spyOn(browserG5Api, 'commitMemoryPack').mockResolvedValue({
      schema_version: '2.1.0',
      request_id: 'req-commit',
      batch_id: preview.batch_id,
      inserted_count: 1,
      skipped_count: 0,
      warning_count: 0,
    })
    const user = userEvent.setup()
    render(<MemoriesPage />)
    await screen.findByRole('button', { name: /简短结论/ })
    const file = new File(['{"synthetic":true}'], 'synthetic.json', {
      type: 'application/json',
    })
    await user.upload(screen.getByLabelText('导入 Memory Pack'), file)
    expect(await screen.findByText(/合法新项 1/)).toBeInTheDocument()
    expect(
      screen.getByText((_content, element) =>
        element?.tagName === 'LI' &&
        Boolean(element.textContent?.includes('<script>alert(1)</script>')),
      ),
    ).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    await user.click(screen.getByRole('button', { name: '全部以 paused 导入' }))
    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/已导入 1，跳过 0，警告 0/)).toBeInTheDocument()
  })

  it('keeps superseded memories read-only instead of exposing a failing edit action', async () => {
    const memory = { ...makeMemory('已被更新版本取代的记忆'), review_status: 'superseded' as const }
    mockReads(memory, makeDetail(memory))
    render(<MemoriesPage />)

    await userEvent.setup().click(await screen.findByRole('button', { name: /已被更新版本取代/ }))
    const detail = within(await screen.findByRole('region', { name: '记忆详情' }))
    expect(detail.getByRole('note')).toHaveTextContent('已取代记忆为只读')
    expect(detail.getByLabelText('类型')).toBeDisabled()
    expect(detail.getByLabelText('内容')).toBeDisabled()
    expect(detail.getByLabelText('适用条件')).toBeDisabled()
    expect(detail.getByRole('button', { name: '保存新版本' })).toBeDisabled()
    expect(detail.getByRole('button', { name: '作为新版本恢复' })).toBeDisabled()
    expect(detail.getByRole('button', { name: '永久删除' })).toBeEnabled()
  })
})

function mockReads(memory: MemoryProjection, detail: MemoryDetailResponse): void {
  vi.spyOn(browserG5Api, 'listMemories').mockResolvedValue({
    schema_version: '2.1.0',
    request_id: 'req-list',
    items: [memory],
    next_cursor: null,
  })
  vi.spyOn(browserG5Api, 'getMemory').mockResolvedValue(detail)
  vi.spyOn(browserG5Api, 'getMemoryUsages').mockResolvedValue({
    schema_version: '2.1.0',
    request_id: 'req-usages',
    items: [],
    next_cursor: null,
  })
  vi.spyOn(browserG5Api, 'getMemoryRelations').mockResolvedValue({
    schema_version: '2.1.0',
    request_id: 'req-relations',
    items: [],
    next_cursor: null,
  })
}

function makeMemory(content: string): MemoryProjection {
  return {
    memory_id: MEMORY_ID,
    kind: 'preference',
    content,
    applies_when: '所有普通技术对话',
    review_status: 'active',
    confidence: 0.95,
    current_version_id: VERSION_ID,
    version: 2,
    source_type: 'conversation_turn',
    retrieved_count: 2,
    injected_count: 1,
    verified_applied_count: 1,
    helpful_count: 1,
    harmful_count: 0,
    stale_count: 0,
    last_used_at: AT,
    created_at: AT,
    updated_at: AT,
  }
}

function makeDetail(memory: MemoryProjection): MemoryDetailResponse {
  return {
    schema_version: '2.1.0',
    request_id: 'req-detail',
    memory,
    versions: [
      {
        version_id: OLD_VERSION_ID,
        version: 1,
        kind: memory.kind,
        content: '旧版本内容',
        applies_when: memory.applies_when,
        review_status: memory.review_status,
        confidence: memory.confidence,
        created_by_action: 'llm_extract',
        created_at: AT,
      },
      {
        version_id: VERSION_ID,
        version: 2,
        kind: memory.kind,
        content: memory.content,
        applies_when: memory.applies_when,
        review_status: memory.review_status,
        confidence: memory.confidence,
        created_by_action: 'user_edit',
        created_at: AT,
      },
    ],
    evidence: [
      {
        evidence_id: `evidence_${ULID}`,
        message_id: `msg_${ULID}`,
        task_id: `task_${ULID}`,
        turn_index: 1,
        source_type: 'conversation_turn',
        is_primary: true,
        created_at: AT,
      },
    ],
  }
}

function makeRelation(): MemoryRelation {
  return {
    relation_id: `rel_${ULID}`,
    from_memory_id: MEMORY_ID,
    to_memory_id: OTHER_MEMORY_ID,
    relation_type: 'conflicts_with',
    status: 'unresolved',
    resolution_action: null,
    resolution_memory_id: null,
    created_at: AT,
  }
}

function makePackPreview(): PackPreview {
  return {
    schema_version: '2.1.0',
    request_id: 'req-preview',
    batch_id: `batch_${ULID}`,
    name: 'Synthetic Pack',
    description: 'Fixture only',
    format_version: '2.0.0',
    legal_new_count: 1,
    duplicate_count: 0,
    potential_conflict_count: 0,
    suspicious_count: 0,
    items: [
      {
        external_id: `card_${ULID}`,
        kind: 'rule',
        content: '<script>alert(1)</script>',
        applies_when: '合成测试',
        classification: 'legal_new',
        reason: null,
      },
    ],
    preview_token: 'p'.repeat(43),
    expires_at: AT,
  }
}
