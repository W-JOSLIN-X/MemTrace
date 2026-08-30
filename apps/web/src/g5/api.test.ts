import { afterEach, describe, expect, it, vi } from 'vitest'

import { browserG5Api } from './api'
import {
  createG5EventList,
  createG5JobResponse,
  createG5MemoryList,
  createG5Response,
  createG5TurnResponse,
} from '../test/g5Fixtures'

const ID = '01J00000000000000000000001'

afterEach(() => vi.unstubAllGlobals())

describe('browser G5 API', () => {
  it('uses only public v2 REST routes, cookies and caller-owned idempotency keys', async () => {
    const editedMemory = {
      ...createG5MemoryList().items[0],
      kind: 'rule',
      content: '始终使用中文',
      applies_when: '所有回答',
      current_version_id: 'memver_01J00000000000000000000002',
      version: 2,
      source_type: 'user_edit',
    }
    const edit = {
      schema_version: '2.1.0',
      request_id: 'req-edit',
      memory: editedMemory,
    }
    const lifecycle = {
      schema_version: '2.1.0',
      request_id: 'req-pause',
      memory_id: `mem_${ID}`,
      old_status: 'active',
      new_status: 'paused',
      updated_at: '2026-08-30T12:00:00Z',
    }
    const responses = [
      createG5Response(),
      createG5TurnResponse(),
      createG5MemoryList(),
      createG5EventList(),
      createG5EventList(),
      createG5JobResponse(),
      edit,
      lifecycle,
    ]
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse(responses.shift()))
    vi.stubGlobal('fetch', fetchMock)

    await browserG5Api.createTask('on', 'create-key')
    await browserG5Api.createTurn(`task_${ID}`, '普通对话', 'on', 'turn-key')
    await browserG5Api.listMemories()
    await browserG5Api.getTaskEvents(`task_${ID}`, 0)
    await browserG5Api.getMemoryEvents(0)
    await browserG5Api.getReflectionJob(`job_${ID}`)
    await browserG5Api.editMemory(
      `mem_${ID}`,
      {
        kind: 'rule',
        content: '始终使用中文',
        applies_when: '所有回答',
        expected_current_version_id: `memver_${ID}`,
      },
      'edit-key',
    )
    await browserG5Api.changeMemory(`mem_${ID}`, 'pause', 'pause-key')

    for (const call of fetchMock.mock.calls) {
      expect(call[1]?.credentials).toBe('same-origin')
      expect(String(call[0])).toMatch(/^\/api\/v2\//)
    }
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'create-key',
    })
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'turn-key',
    })
    expect(fetchMock.mock.calls[6]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'edit-key',
    })
    expect(fetchMock.mock.calls[7]?.[1]?.headers).toMatchObject({
      'Idempotency-Key': 'pause-key',
    })
  })
})

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
