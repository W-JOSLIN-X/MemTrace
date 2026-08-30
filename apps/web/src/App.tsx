import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import { SessionProvider } from './auth/SessionProvider'
import { useSession } from './auth/useSession'
import { AppShell } from './components/AppShell'
import { AgentPage } from './pages/AgentPage'
import { EvalsPage } from './pages/EvalsPage'
import { MemoriesPage } from './pages/MemoriesPage'
import { SettingsPage } from './pages/SettingsPage'
import { LoginPage } from './pages/LoginPage'
import { RecoverPage } from './pages/RecoverPage'
import { RegisterPage } from './pages/RegisterPage'

export function AppRoutes() {
  return (
    <SessionProvider>
      <Routes>
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="recover" element={<RecoverPage />} />
        <Route element={<RequireSession />}>
          <Route element={<AppShell />}>
            <Route index element={<AgentPage />} />
            <Route path="memories" element={<MemoriesPage />} />
            <Route path="evals" element={<EvalsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </SessionProvider>
  )
}

function RequireSession() {
  const { phase } = useSession()
  const location = useLocation()
  if (phase === 'loading') {
    return (
      <main className="grid min-h-screen place-items-center bg-stone-50" aria-live="polite">
        <p className="text-sm font-bold text-slate-500">正在恢复安全会话…</p>
      </main>
    )
  }
  if (phase !== 'authenticated') {
    return <Navigate replace state={{ from: location.pathname }} to="/login" />
  }
  return <Outlet />
}
