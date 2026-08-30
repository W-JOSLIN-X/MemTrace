import { useContext } from 'react'

import { SessionContext } from './sessionContext'
import type { SessionContextValue } from './sessionContext'

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (value === null) throw new Error('useSession must be used inside SessionProvider')
  return value
}
