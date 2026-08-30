import type {
  Account,
  AuthSession,
  Quota,
  RecoveryCodeResult,
  RecoveryResult,
  RegisterResult,
  SystemInfo,
} from './types'

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('expected object')
  }
  return value as Record<string, unknown>
}

function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const row = object(value)
  const actual = Object.keys(row).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error('unknown or missing field')
  }
  return row
}

function string(value: unknown, min: number, max: number): string {
  if (typeof value !== 'string' || value.length < min || value.length > max) {
    throw new Error('invalid string')
  }
  return value
}

function integer(value: unknown, min = 0): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min) {
    throw new Error('invalid integer')
  }
  return value
}

function bool(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('invalid boolean')
  return value
}

function parseQuota(value: unknown): Quota {
  const row = exact(value, ['limit', 'used', 'remaining', 'active', 'resets_at'])
  const result = {
    limit: integer(row.limit, 1),
    used: integer(row.used),
    remaining: integer(row.remaining),
    active: integer(row.active),
    resets_at: string(row.resets_at, 1, 64),
  }
  if (result.used + result.remaining !== result.limit) throw new Error('inconsistent quota')
  return result
}

function parseAccount(value: unknown): Account {
  const row = exact(value, [
    'username',
    'display_name',
    'status',
    'default_memory_mode',
  ])
  const username = string(row.username, 3, 32)
  if (!/^[a-z0-9_]{3,32}$/.test(username)) throw new Error('invalid username')
  if (row.status !== 'active' || !['on', 'off'].includes(String(row.default_memory_mode))) {
    throw new Error('invalid account state')
  }
  return {
    username,
    display_name: string(row.display_name, 1, 80),
    status: 'active',
    default_memory_mode: row.default_memory_mode as Account['default_memory_mode'],
  }
}

export function parseAuthSession(value: unknown): AuthSession {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'authenticated',
    'account',
    'csrf_token',
    'session_expires_at',
    'quota',
    'provider_mode',
    'model',
    'key_configured',
  ])
  if (row.schema_version !== '2.1.0' || row.authenticated !== true) {
    throw new Error('invalid auth contract')
  }
  if (row.provider_mode !== 'real' && row.provider_mode !== 'mock') {
    throw new Error('invalid provider mode')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 1, 64),
    authenticated: true,
    account: parseAccount(row.account),
    csrf_token: string(row.csrf_token, 43, 128),
    session_expires_at: string(row.session_expires_at, 1, 64),
    quota: parseQuota(row.quota),
    provider_mode: row.provider_mode,
    model: string(row.model, 1, 128),
    key_configured: bool(row.key_configured),
  }
}

export function parseRegisterResult(value: unknown): RegisterResult {
  const row = exact(value, ['schema_version', 'request_id', 'session', 'recovery_code'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid schema version')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 1, 64),
    session: parseAuthSession(row.session),
    recovery_code: string(row.recovery_code, 20, 256),
  }
}

export function parseRecoveryResult(value: unknown): RecoveryResult {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'recovery_code',
    'sessions_revoked',
  ])
  if (row.schema_version !== '2.1.0') throw new Error('invalid schema version')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 1, 64),
    recovery_code: string(row.recovery_code, 20, 256),
    sessions_revoked: integer(row.sessions_revoked),
  }
}

export function parseRecoveryCode(value: unknown): RecoveryCodeResult {
  const row = exact(value, ['schema_version', 'request_id', 'recovery_code'])
  if (row.schema_version !== '2.1.0') throw new Error('invalid schema version')
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 1, 64),
    recovery_code: string(row.recovery_code, 20, 256),
  }
}

export function parseSystemInfo(value: unknown): SystemInfo {
  const row = exact(value, [
    'schema_version',
    'request_id',
    'version',
    'revision',
    'migration',
    'provider_mode',
    'model',
    'key_configured',
    'memory_budget_per_card',
    'memory_budget_total',
    'tool_allowlist',
    'quota',
  ])
  if (
    row.schema_version !== '2.1.0' ||
    row.migration !== '007_day7_public_release' ||
    (row.provider_mode !== 'real' && row.provider_mode !== 'mock') ||
    !Array.isArray(row.tool_allowlist) ||
    row.tool_allowlist.length !== 1 ||
    row.tool_allowlist[0] !== 'python_ast_check'
  ) {
    throw new Error('invalid system contract')
  }
  return {
    schema_version: '2.1.0',
    request_id: string(row.request_id, 1, 64),
    version: string(row.version, 1, 32),
    revision: string(row.revision, 1, 64),
    migration: '007_day7_public_release',
    provider_mode: row.provider_mode,
    model: string(row.model, 1, 128),
    key_configured: bool(row.key_configured),
    memory_budget_per_card: integer(row.memory_budget_per_card, 1),
    memory_budget_total: integer(row.memory_budget_total, 1),
    tool_allowlist: ['python_ast_check'],
    quota: parseQuota(row.quota),
  }
}
