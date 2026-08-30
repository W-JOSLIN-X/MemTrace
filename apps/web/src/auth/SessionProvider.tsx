import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'

import { publicApi, setCsrfToken } from './api'
import { SessionContext } from './sessionContext'
import type { SessionContextValue } from './sessionContext'
import type { AuthSession, LoginInput, RegisterInput } from './types'

export function SessionProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<SessionContextValue['phase']>('loading')
  const [session, setSession] = useState<AuthSession | null>(null)

  const clear = useCallback(() => {
    setCsrfToken(null)
    setSession(null)
    setPhase('unauthenticated')
  }, [])

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const current = await publicApi.session(signal)
      setSession(current)
      setPhase('authenticated')
      return current
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      clear()
      return null
    }
  }, [clear])

  useEffect(() => {
    const controller = new AbortController()
    void publicApi.session(controller.signal).then(
      (current) => {
        setSession(current)
        setPhase('authenticated')
      },
      (error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        clear()
      },
    )
    const authRequired = () => clear()
    globalThis.addEventListener('memtrace:auth-required', authRequired)
    return () => {
      controller.abort()
      globalThis.removeEventListener('memtrace:auth-required', authRequired)
    }
  }, [clear])

  const login = useCallback(async (input: LoginInput, signal?: AbortSignal) => {
    const current = await publicApi.login(input, signal)
    setSession(current)
    setPhase('authenticated')
    globalThis.dispatchEvent(new Event('memtrace:session-changed'))
    return current
  }, [])

  const register = useCallback(async (input: RegisterInput, signal?: AbortSignal) => {
    const result = await publicApi.register(input, signal)
    setSession(result.session)
    setPhase('authenticated')
    globalThis.dispatchEvent(new Event('memtrace:session-changed'))
    return result
  }, [])

  const logout = useCallback(async (signal?: AbortSignal) => {
    try {
      await publicApi.logout(signal)
    } finally {
      clear()
    }
  }, [clear])

  const logoutAll = useCallback(async (signal?: AbortSignal) => {
    try {
      await publicApi.logoutAll(signal)
    } finally {
      clear()
    }
  }, [clear])

  const value = useMemo<SessionContextValue>(
    () => ({ phase, session, login, register, logout, logoutAll, refresh, clear }),
    [clear, login, logout, logoutAll, phase, refresh, register, session],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
