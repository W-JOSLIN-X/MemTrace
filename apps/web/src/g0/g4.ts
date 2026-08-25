import {
  ContractError,
  parseMemoryCard,
  parseMemoryRelation,
  parseMemoryVersionList,
} from './runtime'
import type {
  ImportBatchId,
  MemoryCard,
  MemoryCardStatus,
  MemoryId,
  MemoryKind,
  MemoryRelation,
  MemoryRelationListResponse,
  MemoryScope,
  MemorySourceType,
  MemoryVersionDiffResponse,
  MemoryVersionId,
  PackId,
  RelationId,
  RequestId,
  TaskId,
} from './types'

export type MemorySort =
  | 'updated_desc'
  | 'created_desc'
  | 'last_used_desc'
  | 'title_asc'

export interface MemoryListOptions {
  query?: string
  kind?: MemoryKind
  status?: Exclude<MemoryCardStatus, 'deleted'>
  domain?: MemoryScope['domain']
  task_type?: Exclude<MemoryScope['task_type'], null>
  source_type?: MemorySourceType
  used_after?: string
  sort?: MemorySort
  cursor?: string
}

export interface MemoryDeleteResponse {
  request_id: RequestId
  memory_id: MemoryId
  status: 'deleted'
  deleted_at: string
}

export interface TaskDeleteResponse {
  request_id: RequestId
  task_id: TaskId
  status: 'deleted'
  memory_policy: 'preserve_and_mark_evidence_missing'
  affected_card_count: number
}

export interface MergedMemoryCardInput {
  kind: MemoryKind
  title: string
  rule: string
  avoid: string
  trigger_text: string
  scope: MemoryScope
  exceptions: Array<'response_policy:direct_fix' | 'urgency:urgent'>
}

export interface ConflictDetectRequest {
  left_memory_id: MemoryId
  left_expected_current_version_id: MemoryVersionId
  right_memory_id: MemoryId
  right_expected_current_version_id: MemoryVersionId
}

export interface ConflictDetectResponse {
  request_id: RequestId
  relation_id: RelationId
  left_memory_id: MemoryId
  right_memory_id: MemoryId
  relation_type: 'conflicts_with'
  status: 'unresolved'
}

export interface ConflictDetailResponse {
  request_id: RequestId
  relation: MemoryRelation
  left: MemoryCard
  right: MemoryCard
}

export interface ConflictResolveRequest {
  expected_relation_status: 'unresolved'
  left_expected_current_version_id: MemoryVersionId
  right_expected_current_version_id: MemoryVersionId
  action: 'prefer' | 'separate_scopes' | 'merge' | 'pause_both'
  preferred_memory_id?: MemoryId
  left_scope?: MemoryScope
  right_scope?: MemoryScope
  merged_card?: MergedMemoryCardInput
}

export interface ConflictResolveResponse {
  request_id: RequestId
  relation_id: RelationId
  action: ConflictResolveRequest['action']
  status: 'resolved'
}

export interface MemoryMergeRequest {
  left_memory_id: MemoryId
  left_expected_current_version_id: MemoryVersionId
  right_memory_id: MemoryId
  right_expected_current_version_id: MemoryVersionId
  merged_card: MergedMemoryCardInput
}

export interface MemoryMergeResponse {
  request_id: RequestId
  merged_memory_id: MemoryId
  left_memory_id: MemoryId
  right_memory_id: MemoryId
}

export type PackClassification =
  | 'legal_new'
  | 'duplicate'
  | 'potential_conflict'
  | 'suspicious'

export interface PackPreviewItem {
  external_id: `card_${string}`
  kind: MemoryKind
  title: string
  rule: string
  avoid: string
  scope: MemoryScope
  classification: PackClassification
  reason:
    | 'exact_duplicate'
    | 'declared_conflict'
    | 'scope_overlap_similarity'
    | 'suspicious_text'
    | null
}

export interface PackPreviewResponse {
  request_id: RequestId
  batch_id: ImportBatchId
  pack_metadata: {
    name: string
    description: string
    format: 'memtrace-memory-pack'
    format_version: '1.0.0'
    producer: { name: string; version: string }
    source: {
      kind: 'user_export' | 'external_import'
      trust: 'self_asserted' | 'unverified'
    }
  }
  legal_new_count: number
  duplicate_count: number
  potential_conflict_count: number
  suspicious_count: number
  items: PackPreviewItem[]
  preview_token: string
}

export interface ImportCommitResponse {
  request_id: RequestId
  batch_id: ImportBatchId
  inserted_count: number
  skipped_count: number
  warning_count: number
}

export interface ImportBatchResponse {
  request_id: RequestId
  batch_id: ImportBatchId
  status: 'quarantined' | 'committed' | 'expired' | 'cancelled'
  created_at: string
  expires_at: string | null
  inserted_count: number
  skipped_count: number
  warning_count: number
  error_message: string | null
}

export interface MemoryPackDocument {
  schema_ref: 'memtrace-memory-pack@1.0.0'
  format: 'memtrace-memory-pack'
  format_version: '1.0.0'
  pack_id: PackId
  name: string
  description: string
  created_at: string
  producer: { name: string; version: string }
  source: {
    kind: 'user_export' | 'external_import'
    trust: 'self_asserted' | 'unverified'
  }
  privacy: { contains_raw_evidence: false; anonymized: true }
  cards: unknown[]
  relations: unknown[]
  integrity: { algorithm: 'sha256'; canonical_payload_sha256: string }
}

const requestPattern = /^req_[0-9A-HJKMNP-TV-Z]{26}$/
const memoryPattern = /^mem_[0-9A-HJKMNP-TV-Z]{26}$/
const relationPattern = /^rel_[0-9A-HJKMNP-TV-Z]{26}$/
const batchPattern = /^batch_[0-9A-HJKMNP-TV-Z]{26}$/
const packPattern = /^pack_[0-9A-HJKMNP-TV-Z]{26}$/
const tokenPattern = /^[A-Za-z0-9_-]{43}$/
const hashPattern = /^[0-9a-f]{64}$/

export function parseMemoryRelationList(value: unknown): MemoryRelationListResponse {
  const body = strictRecord(value, ['request_id', 'items', 'next_cursor'])
  id(body.request_id, requestPattern, 'request_id')
  array(body.items, 'items').forEach(parseMemoryRelation)
  nullableString(body.next_cursor, 'next_cursor')
  return body as unknown as MemoryRelationListResponse
}

export function parseMemoryVersionDiff(value: unknown): MemoryVersionDiffResponse {
  const body = strictRecord(value, [
    'request_id',
    'from_version',
    'to_version',
    'changed_fields',
  ])
  id(body.request_id, requestPattern, 'request_id')
  const parsed = parseMemoryVersionList({
    request_id: body.request_id,
    items: [body.from_version, body.to_version],
    next_cursor: null,
  })
  const allowed = ['title', 'rule', 'avoid', 'trigger_text', 'scope', 'exceptions']
  array(body.changed_fields, 'changed_fields').forEach((field) => {
    if (typeof field !== 'string' || !allowed.includes(field)) invalid('changed_fields')
  })
  return {
    request_id: body.request_id as RequestId,
    from_version: parsed.items[0],
    to_version: parsed.items[1],
    changed_fields: body.changed_fields as MemoryVersionDiffResponse['changed_fields'],
  }
}

export function parseConflictDetect(value: unknown): ConflictDetectResponse {
  const body = strictRecord(value, [
    'request_id',
    'relation_id',
    'left_memory_id',
    'right_memory_id',
    'relation_type',
    'status',
  ])
  id(body.request_id, requestPattern, 'request_id')
  id(body.relation_id, relationPattern, 'relation_id')
  id(body.left_memory_id, memoryPattern, 'left_memory_id')
  id(body.right_memory_id, memoryPattern, 'right_memory_id')
  constant(body.relation_type, 'conflicts_with', 'relation_type')
  constant(body.status, 'unresolved', 'status')
  return body as unknown as ConflictDetectResponse
}

export function parseConflictDetail(value: unknown): ConflictDetailResponse {
  const body = strictRecord(value, ['request_id', 'relation', 'left', 'right'])
  id(body.request_id, requestPattern, 'request_id')
  const relation = parseMemoryRelation(body.relation)
  const left = parseMemoryCard(body.left)
  const right = parseMemoryCard(body.right)
  if (relation.from_memory_id !== left.memory_id || relation.to_memory_id !== right.memory_id) {
    invalid('conflict endpoints')
  }
  return { request_id: body.request_id as RequestId, relation, left, right }
}

export function parseConflictResolve(value: unknown): ConflictResolveResponse {
  const body = strictRecord(value, ['request_id', 'relation_id', 'action', 'status'])
  id(body.request_id, requestPattern, 'request_id')
  id(body.relation_id, relationPattern, 'relation_id')
  oneOf(body.action, ['prefer', 'separate_scopes', 'merge', 'pause_both'], 'action')
  constant(body.status, 'resolved', 'status')
  return body as unknown as ConflictResolveResponse
}

export function parseMemoryMerge(value: unknown): MemoryMergeResponse {
  const body = strictRecord(value, [
    'request_id',
    'merged_memory_id',
    'left_memory_id',
    'right_memory_id',
  ])
  id(body.request_id, requestPattern, 'request_id')
  for (const key of ['merged_memory_id', 'left_memory_id', 'right_memory_id']) {
    id(body[key], memoryPattern, key)
  }
  return body as unknown as MemoryMergeResponse
}

export function parseMemoryDelete(value: unknown): MemoryDeleteResponse {
  const body = strictRecord(value, ['request_id', 'memory_id', 'status', 'deleted_at'])
  id(body.request_id, requestPattern, 'request_id')
  id(body.memory_id, memoryPattern, 'memory_id')
  constant(body.status, 'deleted', 'status')
  timestamp(body.deleted_at, 'deleted_at')
  return body as unknown as MemoryDeleteResponse
}

export function parseTaskDelete(value: unknown): TaskDeleteResponse {
  const body = strictRecord(value, [
    'request_id',
    'task_id',
    'status',
    'memory_policy',
    'affected_card_count',
  ])
  id(body.request_id, requestPattern, 'request_id')
  id(body.task_id, /^task_[0-9A-HJKMNP-TV-Z]{26}$/, 'task_id')
  constant(body.status, 'deleted', 'status')
  constant(body.memory_policy, 'preserve_and_mark_evidence_missing', 'memory_policy')
  count(body.affected_card_count, 'affected_card_count')
  return body as unknown as TaskDeleteResponse
}

export function parsePackPreview(value: unknown): PackPreviewResponse {
  const body = strictRecord(value, [
    'request_id',
    'batch_id',
    'pack_metadata',
    'legal_new_count',
    'duplicate_count',
    'potential_conflict_count',
    'suspicious_count',
    'items',
    'preview_token',
  ])
  id(body.request_id, requestPattern, 'request_id')
  id(body.batch_id, batchPattern, 'batch_id')
  const metadata = strictRecord(body.pack_metadata, [
    'name',
    'description',
    'format',
    'format_version',
    'producer',
    'source',
  ])
  string(metadata.name, 'name')
  string(metadata.description, 'description')
  constant(metadata.format, 'memtrace-memory-pack', 'format')
  constant(metadata.format_version, '1.0.0', 'format_version')
  strictRecord(metadata.producer, ['name', 'version'])
  strictRecord(metadata.source, ['kind', 'trust'])
  for (const key of [
    'legal_new_count',
    'duplicate_count',
    'potential_conflict_count',
    'suspicious_count',
  ]) count(body[key], key)
  array(body.items, 'items').forEach(parsePreviewItem)
  id(body.preview_token, tokenPattern, 'preview_token')
  return body as unknown as PackPreviewResponse
}

function parsePreviewItem(value: unknown): void {
  const body = strictRecord(value, [
    'external_id',
    'kind',
    'title',
    'rule',
    'avoid',
    'scope',
    'classification',
    'reason',
  ])
  id(body.external_id, /^card_[A-Za-z0-9_-]{1,64}$/, 'external_id')
  oneOf(
    body.kind,
    ['preference', 'constraint', 'procedure', 'experience', 'environment', 'learning_checkpoint'],
    'kind',
  )
  string(body.title, 'title')
  string(body.rule, 'rule')
  string(body.avoid, 'avoid')
  strictRecord(body.scope, [
    'level',
    'domain',
    'task_type',
    'artifact_type',
    'audience',
    'project_key',
    'language',
    'framework',
    'concepts',
  ])
  oneOf(
    body.classification,
    ['legal_new', 'duplicate', 'potential_conflict', 'suspicious'],
    'classification',
  )
  if (body.reason !== null) oneOf(
    body.reason,
    ['exact_duplicate', 'declared_conflict', 'scope_overlap_similarity', 'suspicious_text'],
    'reason',
  )
}

export function parseImportCommit(value: unknown): ImportCommitResponse {
  const body = strictRecord(value, [
    'request_id',
    'batch_id',
    'inserted_count',
    'skipped_count',
    'warning_count',
  ])
  id(body.request_id, requestPattern, 'request_id')
  id(body.batch_id, batchPattern, 'batch_id')
  count(body.inserted_count, 'inserted_count')
  count(body.skipped_count, 'skipped_count')
  count(body.warning_count, 'warning_count')
  return body as unknown as ImportCommitResponse
}

export function parseImportBatch(value: unknown): ImportBatchResponse {
  const body = strictRecord(value, [
    'request_id',
    'batch_id',
    'status',
    'created_at',
    'expires_at',
    'inserted_count',
    'skipped_count',
    'warning_count',
    'error_message',
  ])
  id(body.request_id, requestPattern, 'request_id')
  id(body.batch_id, batchPattern, 'batch_id')
  oneOf(body.status, ['quarantined', 'committed', 'expired', 'cancelled'], 'status')
  timestamp(body.created_at, 'created_at')
  if (body.expires_at !== null) timestamp(body.expires_at, 'expires_at')
  count(body.inserted_count, 'inserted_count')
  count(body.skipped_count, 'skipped_count')
  count(body.warning_count, 'warning_count')
  nullableString(body.error_message, 'error_message')
  return body as unknown as ImportBatchResponse
}

export function parseMemoryPack(value: unknown): MemoryPackDocument {
  const body = strictRecord(value, [
    'schema_ref',
    'format',
    'format_version',
    'pack_id',
    'name',
    'description',
    'created_at',
    'producer',
    'source',
    'privacy',
    'cards',
    'relations',
    'integrity',
  ])
  constant(body.schema_ref, 'memtrace-memory-pack@1.0.0', 'schema_ref')
  constant(body.format, 'memtrace-memory-pack', 'format')
  constant(body.format_version, '1.0.0', 'format_version')
  id(body.pack_id, packPattern, 'pack_id')
  string(body.name, 'name')
  string(body.description, 'description')
  timestamp(body.created_at, 'created_at')
  strictRecord(body.producer, ['name', 'version'])
  strictRecord(body.source, ['kind', 'trust'])
  const privacy = strictRecord(body.privacy, ['contains_raw_evidence', 'anonymized'])
  constant(privacy.contains_raw_evidence, false, 'contains_raw_evidence')
  constant(privacy.anonymized, true, 'anonymized')
  array(body.cards, 'cards').forEach((card) => {
    const item = strictRecord(card, [
      'external_id', 'schema_version', 'kind', 'title', 'rule', 'avoid', 'trigger_text',
      'scope', 'exceptions', 'claimed_origin', 'version', 'updated_at',
    ])
    id(item.external_id, /^card_[A-Za-z0-9_-]{1,64}$/, 'external_id')
  })
  array(body.relations, 'relations').forEach((relation) => {
    strictRecord(relation, ['from_external_id', 'to_external_id', 'relation_type'])
  })
  const integrity = strictRecord(body.integrity, ['algorithm', 'canonical_payload_sha256'])
  constant(integrity.algorithm, 'sha256', 'algorithm')
  id(integrity.canonical_payload_sha256, hashPattern, 'canonical_payload_sha256')
  return body as unknown as MemoryPackDocument
}

function strictRecord(value: unknown, keys: string[]): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) invalid('object')
  const body = value as Record<string, unknown>
  const actual = Object.keys(body).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    invalid('unknown or missing field')
  }
  return body
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) invalid(label)
  return value
}

function string(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string') invalid(label)
}

function nullableString(value: unknown, label: string): void {
  if (value !== null) string(value, label)
}

function id(value: unknown, pattern: RegExp, label: string): asserts value is string {
  string(value, label)
  if (!pattern.test(value)) invalid(label)
}

function timestamp(value: unknown, label: string): void {
  string(value, label)
  if (!value.endsWith('Z') || Number.isNaN(Date.parse(value))) invalid(label)
}

function count(value: unknown, label: string): void {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) invalid(label)
}

function oneOf(value: unknown, values: readonly string[], label: string): void {
  if (typeof value !== 'string' || !values.includes(value)) invalid(label)
}

function constant(value: unknown, expected: unknown, label: string): void {
  if (value !== expected) invalid(label)
}

function invalid(label: string): never {
  throw new ContractError(`invalid G4 ${label}`)
}
