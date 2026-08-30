import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { ConversationPage } from './pages/ConversationPage'
import { EvalsPage } from './pages/EvalsPage'
import { MemoriesPage } from './pages/MemoriesPage'
import { SettingsPage } from './pages/SettingsPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ConversationPage />} />
        <Route path="memories" element={<MemoriesPage />} />
        <Route path="evals" element={<EvalsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/" />} />
    </Routes>
  )
}
