import { createContext } from 'react'

import type { AuthSession, LoginInput, RegisterInput, RegisterResult } from './types'

export type SessionContextValue = {
  phase: 'loading' | 'authenticated' | 'unauthenticated'
  session: AuthSession | null
  login: (input: LoginInput, signal?: AbortSignal) => Promise<AuthSession>
  register: (input: RegisterInput, signal?: AbortSignal) => Promise<RegisterResult>
  logout: (signal?: AbortSignal) => Promise<void>
  logoutAll: (signal?: AbortSignal) => Promise<void>
  refresh: (signal?: AbortSignal) => Promise<AuthSession | null>
  clear: () => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)
