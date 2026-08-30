export type MemoryMode = 'on' | 'off'
export type ProviderMode = 'real' | 'mock'

export type Account = {
  username: string
  display_name: string
  status: 'active'
  default_memory_mode: MemoryMode
}

export type Quota = {
  limit: number
  used: number
  remaining: number
  active: number
  resets_at: string
}

export type AuthSession = {
  schema_version: '2.1.0'
  request_id: string
  authenticated: true
  account: Account
  csrf_token: string
  session_expires_at: string
  quota: Quota
  provider_mode: ProviderMode
  model: string
  key_configured: boolean
}

export type RegisterInput = {
  invitation_code: string
  username: string
  display_name: string
  password: string
  password_confirmation: string
}

export type LoginInput = {
  username: string
  password: string
}

export type RecoverInput = {
  username: string
  recovery_code: string
  new_password: string
  new_password_confirmation: string
}

export type RegisterResult = {
  schema_version: '2.1.0'
  request_id: string
  session: AuthSession
  recovery_code: string
}

export type RecoveryResult = {
  schema_version: '2.1.0'
  request_id: string
  recovery_code: string
  sessions_revoked: number
}

export type RecoveryCodeResult = {
  schema_version: '2.1.0'
  request_id: string
  recovery_code: string
}

export type SystemInfo = {
  schema_version: '2.1.0'
  request_id: string
  version: string
  revision: string
  migration: '007_day7_public_release'
  provider_mode: ProviderMode
  model: string
  key_configured: boolean
  memory_budget_per_card: number
  memory_budget_total: number
  tool_allowlist: ['python_ast_check']
  quota: Quota
}
