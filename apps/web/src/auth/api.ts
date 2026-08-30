import {
  parseAuthSession,
  parseRecoveryCode,
  parseRecoveryResult,
  parseRegisterResult,
  parseSystemInfo,
} from './runtime'
import type {
  AuthSession,
  LoginInput,
  RecoverInput,
  RecoveryCodeResult,
  RecoveryResult,
  RegisterInput,
  RegisterResult,
  SystemInfo,
} from './types'

export class PublicApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number | null
  readonly retryAfterSeconds: number | null

  constructor(
    message: string,
    options: {
      code: string
      retryable: boolean
      status: number | null
      retryAfterSeconds?: number | null
    },
  ) {
    super(message)
    this.name = 'PublicApiError'
    this.code = options.code
    this.retryable = options.retryable
    this.status = options.status
    this.retryAfterSeconds = options.retryAfterSeconds ?? null
  }
}

let csrfToken: string | null = null
const pendingAuthenticatedWrites = new Map<string, { key: string; bodyFingerprint: string }>()

export function setCsrfToken(value: string | null): void {
  csrfToken = value
  if (value === null) pendingAuthenticatedWrites.clear()
}

export function csrfHeaders(): HeadersInit {
  return csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
}

export const publicApi = {
  async session(signal?: AbortSignal): Promise<AuthSession> {
    const result = parseAuthSession(await request('/api/v2/auth/session', { signal }))
    setCsrfToken(result.csrf_token)
    return result
  },
  async login(input: LoginInput, signal?: AbortSignal): Promise<AuthSession> {
    const result = parseAuthSession(
      await request('/api/v2/auth/login', jsonRequest('POST', input, signal, false)),
    )
    setCsrfToken(result.csrf_token)
    return result
  },
  async register(input: RegisterInput, signal?: AbortSignal): Promise<RegisterResult> {
    const result = parseRegisterResult(
      await request('/api/v2/auth/register', jsonRequest('POST', input, signal, false)),
    )
    setCsrfToken(result.session.csrf_token)
    return result
  },
  async recover(input: RecoverInput, signal?: AbortSignal): Promise<RecoveryResult> {
    return parseRecoveryResult(
      await request('/api/v2/auth/recover', jsonRequest('POST', input, signal, false)),
    )
  },
  async logout(signal?: AbortSignal): Promise<void> {
    await authenticatedWrite('logout', '/api/v2/auth/logout', 'POST', undefined, signal)
    setCsrfToken(null)
  },
  async logoutAll(signal?: AbortSignal): Promise<void> {
    await authenticatedWrite('logout-all', '/api/v2/auth/logout-all', 'POST', undefined, signal)
    setCsrfToken(null)
  },
  async changePassword(
    input: {
      current_password: string
      new_password: string
      new_password_confirmation: string
    },
    signal?: AbortSignal,
  ): Promise<void> {
    await authenticatedWrite(
      'change-password',
      '/api/v2/auth/change-password',
      'POST',
      input,
      signal,
    )
    setCsrfToken(null)
  },
  async rotateRecoveryCode(signal?: AbortSignal): Promise<RecoveryCodeResult> {
    return parseRecoveryCode(
      await authenticatedWrite(
        'rotate-recovery',
        '/api/v2/auth/recovery-code/rotate',
        'POST',
        undefined,
        signal,
      ),
    )
  },
  async updateMemoryDefault(mode: 'on' | 'off', signal?: AbortSignal): Promise<void> {
    await authenticatedWrite(
      'account-preferences',
      '/api/v2/auth/account/preferences',
      'PATCH',
      { default_memory_mode: mode },
      signal,
    )
  },
  async deleteAccount(
    input: { current_password: string; confirm_username: string },
    signal?: AbortSignal,
  ): Promise<void> {
    await authenticatedWrite('delete-account', '/api/v2/auth/account', 'DELETE', input, signal)
    setCsrfToken(null)
  },
  async system(signal?: AbortSignal): Promise<SystemInfo> {
    return parseSystemInfo(await request('/api/v2/system', { signal }))
  },
}

function jsonRequest(
  method: string,
  body: unknown,
  signal: AbortSignal | undefined,
  authenticated: boolean,
  idempotencyKey?: string,
): RequestInit {
  return {
    method,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(authenticated ? csrfHeaders() : {}),
      ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  }
}

function newIdempotencyKey(action: string): string {
  return `web-${action}-${crypto.randomUUID()}`
}

async function authenticatedWrite(
  action: string,
  path: string,
  method: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  const bodyFingerprint = body === undefined ? '{}' : JSON.stringify(body)
  const pending = pendingAuthenticatedWrites.get(action)
  const key =
    pending?.bodyFingerprint === bodyFingerprint ? pending.key : newIdempotencyKey(action)
  pendingAuthenticatedWrites.set(action, { key, bodyFingerprint })
  try {
    const result = await request(path, jsonRequest(method, body, signal, true, key))
    if (pendingAuthenticatedWrites.get(action)?.key === key) {
      pendingAuthenticatedWrites.delete(action)
    }
    return result
  } catch (error) {
    if (
      error instanceof PublicApiError &&
      error.status !== null &&
      !error.retryable &&
      pendingAuthenticatedWrites.get(action)?.key === key
    ) {
      pendingAuthenticatedWrites.delete(action)
    }
    throw error
  }
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(path, { credentials: 'same-origin', ...init })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new PublicApiError('无法连接到 MemTrace 服务。', {
      code: 'NETWORK_ERROR',
      retryable: true,
      status: null,
    })
  }
  let body: unknown
  try {
    body = (await response.json()) as unknown
  } catch {
    throw new PublicApiError('服务返回了无法解析的响应。', {
      code: 'INVALID_RESPONSE',
      retryable: false,
      status: response.status,
    })
  }
  if (!response.ok) {
    if (response.status === 401) {
      setCsrfToken(null)
      globalThis.dispatchEvent(new Event('memtrace:auth-required'))
    }
    throw parseError(response.status, body)
  }
  return body
}

function parseError(status: number, body: unknown): PublicApiError {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return new PublicApiError('请求未完成，请稍后重试。', {
      code: 'HTTP_ERROR',
      retryable: status >= 500,
      status,
    })
  }
  const envelope = body as Record<string, unknown>
  if (typeof envelope.error !== 'object' || envelope.error === null) {
    return new PublicApiError('请求未完成，请稍后重试。', {
      code: 'HTTP_ERROR',
      retryable: status >= 500,
      status,
    })
  }
  const error = envelope.error as Record<string, unknown>
  const details =
    typeof error.details === 'object' && error.details !== null
      ? (error.details as Record<string, unknown>)
      : {}
  return new PublicApiError(
    typeof error.message === 'string' ? error.message : '请求未完成，请稍后重试。',
    {
      code: typeof error.code === 'string' ? error.code : 'HTTP_ERROR',
      retryable: error.retryable === true,
      status,
      retryAfterSeconds:
        typeof details.retry_after_seconds === 'number' ? details.retry_after_seconds : null,
    },
  )
}
