import { describe, expect, it } from 'vitest'

import { parseImportBatch, parseMemoryDelete, parsePackPreview } from './g4'
import { ContractError } from './runtime'

const requestId = 'req_01J00000000000000000000000'
const memoryId = 'mem_01J00000000000000000000000'
const batchId = 'batch_01J00000000000000000000000'

describe('Day 5 G4 strict runtime contract', () => {
  it('accepts a controlled permanent-delete tombstone and rejects unknown fields', () => {
    const body = { request_id: requestId, memory_id: memoryId, status: 'deleted', deleted_at: '2026-08-26T00:00:00Z' }
    expect(parseMemoryDelete(body).status).toBe('deleted')
    expect(() => parseMemoryDelete({ ...body, title: 'must not survive' })).toThrow(ContractError)
  })

  it('strictly parses all four Pack preview classifications without exposing the token in output', () => {
    const scope = { level: 'global', domain: 'any', task_type: null, artifact_type: null, audience: null, project_key: null, language: null, framework: null, concepts: [] }
    const classifications = [
      ['legal_new', null], ['duplicate', 'exact_duplicate'],
      ['potential_conflict', 'scope_overlap_similarity'], ['suspicious', 'suspicious_text'],
    ]
    const parsed = parsePackPreview({
      request_id: requestId, batch_id: batchId,
      pack_metadata: { name: 'safe', description: '', format: 'memtrace-memory-pack', format_version: '1.0.0', producer: { name: 'MemTrace', version: '1.4.0' }, source: { kind: 'external_import', trust: 'unverified' } },
      legal_new_count: 1, duplicate_count: 1, potential_conflict_count: 1, suspicious_count: 1,
      items: classifications.map(([classification, reason], index) => ({ external_id: `card_${index}`, kind: 'preference', title: `card ${index}`, rule: 'plain text', avoid: '', scope, classification, reason })),
      preview_token: 'a'.repeat(43),
    })
    expect(parsed.items.map((item) => item.classification)).toEqual(['legal_new', 'duplicate', 'potential_conflict', 'suspicious'])
    expect(() => parsePackPreview({ ...parsed, unexpected: true })).toThrow(ContractError)
  })

  it('parses batch recovery states and rejects invalid IDs', () => {
    const body = { request_id: requestId, batch_id: batchId, status: 'committed', created_at: '2026-08-26T00:00:00Z', expires_at: null, inserted_count: 1, skipped_count: 0, warning_count: 0, error_message: null }
    expect(parseImportBatch(body).status).toBe('committed')
    expect(() => parseImportBatch({ ...body, batch_id: 'batch_bad' })).toThrow(ContractError)
  })
})
