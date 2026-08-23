import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { G0ApiError, type G0Api } from '../g0/api'
import type {
  DemoAlias,
  MemoryJobResponse,
  ResolveAction,
  TaskSnapshot,
} from '../g0/types'
import {
  MEMORY_JOB_ID,
  makeMemoryDetail,
  makeMemoryJob,
  makeResolveResponse,
} from '../test/day3Fixtures'
import { AT, TASK_ID, makeSnapshot } from '../test/g0Fixtures'
import { ChatPage } from './ChatPage'

function terminalSnapshotWithFeedback(): TaskSnapshot {
  return makeSnapshot({
    run_status: 'succeeded',
    partial_output: '你好，世界',
    end_offset: 15,
    final_message: {
      id: 'msg_01J00000000000000000000001',
      role: 'assistant',
      content: '你好，世界',
      created_at: AT,
    },
    feedback_events: [
      {
        feedback_id: 'feedback_01J00000000000000000000001',
        run_id: 'run_01J00000000000000000000000',
        feedback_type: 'explicit_text',
        explicit_text: '以后先说明边界条件。',
        edited_output: null,
        rating: null,
        accepted: null,
        memory_job_id: MEMORY_JOB_ID,
        created_at: AT,
      },
    ],
    terminal: true,
    last_persistent_event_seq: 20,
  })
}

function sessionResponse(alias: DemoAlias) {
  return {
    request_id: 'req_01J00000000000000000000001' as const,
    demo_alias: alias,
    expires_at: '2026-08-24T12:00:00Z',
  }
}

function createG2Api(options: {
  job?: MemoryJobResponse
  snapshot?: TaskSnapshot
} = {}) {
  const createTask = vi.fn<G0Api['createTask']>()
  const getTask = vi.fn<G0Api['getTask']>()
  const getSession = vi.fn<NonNullable<G0Api['getSession']>>()
  const createDemoSession = vi.fn<NonNullable<G0Api['createDemoSession']>>()
  const getMemoryJob = vi.fn<NonNullable<G0Api['getMemoryJob']>>()
  const retryMemoryJob = vi.fn<NonNullable<G0Api['retryMemoryJob']>>()
  const resolveMemoryCandidate = vi.fn<
    NonNullable<G0Api['resolveMemoryCandidate']>
  >()
  const getMemory = vi.fn<NonNullable<G0Api['getMemory']>>()

  getTask.mockResolvedValue(options.snapshot ?? terminalSnapshotWithFeedback())
  getSession.mockResolvedValue(sessionResponse('blank_demo'))
  createDemoSession.mockImplementation(async (alias) => sessionResponse(alias))
  getMemoryJob.mockResolvedValue(options.job ?? makeMemoryJob())
  retryMemoryJob.mockResolvedValue(
    makeMemoryJob({
      status: 'pending',
      stage: 'queued',
      candidate_ids: [],
      disposition: null,
      attempt: 1,
    }),
  )
  resolveMemoryCandidate.mockImplementation(async (_id, request) =>
    makeResolveResponse(request.action),
  )
  getMemory.mockResolvedValue(makeMemoryDetail())

  const api: G0Api = {
    createTask,
    getTask,
    getSession,
    createDemoSession,
    getMemoryJob,
    retryMemoryJob,
    resolveMemoryCandidate,
    getMemory,
  }
  return {
    api,
    createDemoSession,
    getMemory,
    getMemoryJob,
    resolveMemoryCandidate,
    retryMemoryJob,
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  window.history.replaceState(null, '', `/?task_id=${TASK_ID}`)
})

describe('Day 3 G2 owner flow', () => {
  it('restores a candidate, opens evidence, and preserves an edit across a failed retry', async () => {
    const user = userEvent.setup()
    const { api, getMemory, resolveMemoryCandidate } = createG2Api()
    const activeDetail = makeMemoryDetail(makeResolveResponse('edit_accept').card)
    getMemory
      .mockResolvedValueOnce(makeMemoryDetail())
      .mockResolvedValueOnce(activeDetail)
    resolveMemoryCandidate
      .mockRejectedValueOnce(
        new G0ApiError('网络暂时不可用。', {
          code: 'NETWORK_ERROR',
          retryable: true,
          status: null,
        }),
      )
      .mockResolvedValueOnce(makeResolveResponse('edit_accept'))
    const keyFactory = vi.fn(() => 'resolve-edit-key-0001')

    render(
      <ChatPage
        api={api}
        idempotencyKeyFactory={keyFactory}
        memoryMonitorTimeoutMs={2_000}
      />,
    )

    expect(await screen.findByText('先解释边界条件')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看证据（1）' }))
    expect(screen.getByLabelText('证据抽屉')).toHaveTextContent(
      '以后先说明边界条件。',
    )

    await user.click(screen.getByRole('button', { name: '编辑' }))
    const title = screen.getByLabelText('候选标题')
    await user.clear(title)
    await user.type(title, '先讲清楚边界条件')
    await user.click(screen.getByRole('button', { name: '编辑后确认' }))
    expect(await screen.findByText(/网络暂时不可用/)).toBeInTheDocument()
    expect(title).toHaveValue('先讲清楚边界条件')

    await user.click(screen.getByRole('button', { name: '编辑后确认' }))
    expect(
      await screen.findByText('已确认保存，但 Day 4 才接入检索。'),
    ).toBeInTheDocument()
    expect(resolveMemoryCandidate).toHaveBeenCalledTimes(2)
    expect(resolveMemoryCandidate.mock.calls[0]?.[2]).toBe(
      'resolve-edit-key-0001',
    )
    expect(resolveMemoryCandidate.mock.calls[1]?.[2]).toBe(
      'resolve-edit-key-0001',
    )
    expect(resolveMemoryCandidate.mock.calls[1]?.[1]).toMatchObject({
      action: 'edit_accept',
      patch: { title: '先讲清楚边界条件', avoid: '' },
    })
    expect(keyFactory).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['accept', '确认'],
    ['reject', '拒绝候选'],
    ['one_shot', '仅本次'],
  ] as const)('submits the %s disposition with its own key', async (action, label) => {
    const user = userEvent.setup()
    const { api, getMemory, resolveMemoryCandidate } = createG2Api()
    const resolved = makeResolveResponse(action as ResolveAction)
    getMemory
      .mockResolvedValueOnce(makeMemoryDetail())
      .mockResolvedValueOnce(makeMemoryDetail(resolved.card))

    render(
      <ChatPage
        api={api}
        idempotencyKeyFactory={() => `resolve-${action}-key-0001`}
      />,
    )

    await user.click(await screen.findByRole('button', { name: label }))
    await waitFor(() => expect(resolveMemoryCandidate).toHaveBeenCalledTimes(1))
    expect(resolveMemoryCandidate.mock.calls[0]?.[1]).toEqual({
      action,
      patch: null,
    })
    expect(resolveMemoryCandidate.mock.calls[0]?.[2]).toBe(
      `resolve-${action}-key-0001`,
    )
    if (action === 'one_shot') {
      expect(await screen.findByText('仅本次，不进入长期记忆。')).toBeInTheDocument()
    }
  })

  it('reuses a retry key after a network failure and then reaches no-memory', async () => {
    const user = userEvent.setup()
    const failedJob = makeMemoryJob({
      status: 'failed',
      stage: 'failed',
      candidate_ids: [],
      disposition: 'failed',
      error_code: 'MEMORY_PROVIDER_ERROR',
      retryable: true,
    })
    const { api, getMemoryJob, retryMemoryJob } = createG2Api({ job: failedJob })
    getMemoryJob
      .mockResolvedValueOnce(failedJob)
      .mockResolvedValueOnce(
        makeMemoryJob({
          candidate_ids: [],
          disposition: 'no_memory',
        }),
      )
    retryMemoryJob
      .mockRejectedValueOnce(
        new G0ApiError('重试请求网络失败。', {
          code: 'NETWORK_ERROR',
          retryable: true,
          status: null,
        }),
      )
      .mockResolvedValueOnce(
        makeMemoryJob({
          status: 'pending',
          stage: 'queued',
          candidate_ids: [],
          disposition: null,
          error_code: null,
          retryable: false,
        }),
      )
    const keyFactory = vi.fn(() => 'retry-job-key-0001')

    render(<ChatPage api={api} idempotencyKeyFactory={keyFactory} />)

    const retry = await screen.findByRole('button', { name: '重试处理' })
    await user.click(retry)
    expect(await screen.findByText('重试请求网络失败。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重试处理' }))
    expect(
      await screen.findByText('本次没有形成可复用候选。'),
    ).toBeInTheDocument()
    expect(retryMemoryJob).toHaveBeenCalledTimes(2)
    expect(retryMemoryJob.mock.calls[0]?.[1]).toBe('retry-job-key-0001')
    expect(retryMemoryJob.mock.calls[1]?.[1]).toBe('retry-job-key-0001')
    expect(keyFactory).toHaveBeenCalledTimes(1)
  })

  it('shows a non-failure continuation state when polling reaches its bound', async () => {
    const pending = makeMemoryJob({
      status: 'pending',
      stage: 'queued',
      attempt: 0,
      candidate_ids: [],
      disposition: null,
    })
    const { api } = createG2Api({ job: pending })

    render(<ChatPage api={api} memoryMonitorTimeoutMs={0} />)

    expect(await screen.findByText(/仍在处理；这不是失败/)).toBeInTheDocument()
    expect(screen.queryByText(/处理超时|处理失败/)).not.toBeInTheDocument()
  })

  it('clears candidates and drafts when switching demo users', async () => {
    const user = userEvent.setup()
    const { api, createDemoSession } = createG2Api()

    render(<ChatPage api={api} />)

    expect(await screen.findByText('先解释边界条件')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '编辑' }))
    await user.type(screen.getByLabelText('候选标题'), '草稿')
    await user.click(screen.getByRole('button', { name: '种子用户' }))
    await waitFor(() =>
      expect(createDemoSession).toHaveBeenCalledWith(
        'seeded_demo',
        expect.any(AbortSignal),
      ),
    )
    expect(screen.queryByText('先解释边界条件')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('候选标题')).not.toBeInTheDocument()
  })
})
