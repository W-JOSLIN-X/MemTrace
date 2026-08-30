import { describe, expect, it } from 'vitest'

import {
  parseConversationCreate,
  parseConversationSnapshot,
  parseConversationTurn,
  parseMemoryEvents,
  parseMemoryList,
  parseReflectionJob,
} from './runtime'
import {
  createG5EventList,
  createG5JobResponse,
  createG5MemoryList,
  createG5Response,
  createG5SnapshotResponse,
  createG5TurnResponse,
} from '../test/g5Fixtures'

describe('G5 strict runtime parser', () => {
  it('parses the conversation, memory, event and job contract', () => {
    expect(parseConversationCreate(createG5Response()).provider_mode).toBe('real')
    expect(parseConversationTurn(createG5TurnResponse()).usage[0]?.total_tokens).toBe(30)
    expect(parseConversationSnapshot(createG5SnapshotResponse()).last_turn?.usage[0]?.total_tokens).toBe(30)
    expect(parseMemoryList(createG5MemoryList()).items[0]?.kind).toBe('preference')
    expect(parseMemoryEvents(createG5EventList()).items[0]?.event_seq).toBe(1)
    expect(parseReflectionJob(createG5JobResponse()).status).toBe('completed')
  })

  it('rejects unknown fields instead of silently cleaning provider or API output', () => {
    expect(() => parseConversationCreate({ ...createG5Response(), scenario: 'coding' })).toThrow(
      'unknown or missing field',
    )
    expect(() =>
      parseConversationTurn({
        ...createG5TurnResponse(),
        usage: [{ ...(createG5TurnResponse().usage as object[])[0], input_tokens: '10' }],
      }),
    ).toThrow('invalid number')
  })

  it('rejects malformed ids and enum values', () => {
    expect(() => parseMemoryList({ ...createG5MemoryList(), next_cursor: 'memory-1' })).toThrow(
      'invalid id',
    )
    expect(() =>
      parseReflectionJob({ ...createG5JobResponse(), mutation_decision: 'keyword_match' }),
    ).toThrow('invalid enum')
  })

  it('rejects event pages larger than the frozen 100 item bound', () => {
    const event = createG5EventList().items[0]
    expect(() =>
      parseMemoryEvents({
        ...createG5EventList(),
        items: Array.from({ length: 101 }, () => event),
      }),
    ).toThrow('too many events')
  })

  it('strictly validates the persisted latest-turn snapshot projection', () => {
    const snapshot = createG5SnapshotResponse()
    expect(() =>
      parseConversationSnapshot({
        ...snapshot,
        last_turn: { ...snapshot.last_turn, leaked_prompt: 'forbidden' },
      }),
    ).toThrow('unknown or missing field')
  })
})
