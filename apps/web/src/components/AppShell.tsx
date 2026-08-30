import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { publicApi } from '../auth/api'
import { useSession } from '../auth/useSession'
import type { SystemInfo } from '../auth/types'
import { RouteErrorBoundary } from './RouteErrorBoundary'

type NavigationItem = {
  label: string
  shortLabel: string
  to: string
  end?: boolean
  icon: ReactNode
}

const navigation: NavigationItem[] = [
  {
    label: '普通对话',
    shortLabel: '对话',
    to: '/',
    end: true,
    icon: <ChatIcon />,
  },
  {
    label: '记忆中心',
    shortLabel: '记忆',
    to: '/memories',
    icon: <MemoryIcon />,
  },
  {
    label: '评测面板',
    shortLabel: '评测',
    to: '/evals',
    icon: <ChartIcon />,
  },
  {
    label: '系统设置',
    shortLabel: '设置',
    to: '/settings',
    icon: <SettingsIcon />,
  },
]

export function AppShell() {
  const { session, logout } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [system, setSystem] = useState<SystemInfo | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void publicApi.system(controller.signal).then(setSystem).catch(() => undefined)
    return () => controller.abort()
  }, [])

  async function signOut() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-stone-50 text-slate-950">
      <header className="border-b border-stone-200/90 bg-stone-50/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-5 py-4 lg:px-8">
          <NavLink
            aria-label="返回 MemTrace 对话页"
            className="group flex items-center gap-3 rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-4"
            to="/"
          >
            <span className="grid size-10 place-items-center rounded-2xl bg-emerald-700 text-sm font-black tracking-tight text-white shadow-sm transition-transform group-hover:-rotate-3">
              M
            </span>
            <span>
              <span className="block text-base font-black tracking-tight">
                MemTrace
              </span>
              <span className="block text-xs font-medium text-slate-500">
                忆迹 · 反馈记忆 Agent
              </span>
            </span>
          </NavLink>

          <div className="flex items-center gap-3">
            <div
              aria-label="服务状态"
              className="hidden items-center gap-2 rounded-full border border-stone-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 shadow-sm sm:flex"
            >
              <span className={`size-2 rounded-full ${system?.provider_mode === 'real' && system.key_configured ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              {system ? `${system.version} · ${system.provider_mode === 'real' ? '真实模型' : system.provider_mode}` : '正在读取服务状态'}
            </div>
            <div className="text-right">
              <p className="text-sm font-black">{session?.account.display_name}</p>
              <p className="text-xs text-slate-500">今日剩余 {session?.quota.remaining ?? 0} 轮</p>
            </div>
            <button
              className="rounded-xl border border-stone-200 px-3 py-2 text-xs font-bold hover:bg-stone-100"
              onClick={() => void signOut()}
              type="button"
            >
              退出
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1440px] gap-6 px-4 pb-24 pt-5 sm:px-5 lg:grid-cols-[232px_minmax(0,1fr)] lg:px-8 lg:pb-8 lg:pt-8">
        <aside className="hidden lg:block">
          <nav
            aria-label="主要导航"
            className="sticky top-8 space-y-1 rounded-3xl border border-stone-200 bg-white p-3 shadow-sm"
          >
            {navigation.map((item) => (
              <NavigationLink item={item} key={item.to} />
            ))}
          </nav>
        </aside>

        <main className="min-w-0">
          <RouteErrorBoundary key={location.pathname}>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </div>

      <nav
        aria-label="移动端主要导航"
        className="fixed inset-x-3 bottom-3 z-10 grid grid-cols-4 rounded-2xl border border-stone-200 bg-white/95 p-1.5 shadow-lg backdrop-blur lg:hidden"
      >
        {navigation.map((item) => (
          <NavigationLink compact item={item} key={item.to} />
        ))}
      </nav>
    </div>
  )
}

function NavigationLink({
  compact = false,
  item,
}: {
  compact?: boolean
  item: NavigationItem
}) {
  return (
    <NavLink
      className={({ isActive }) =>
        [
          'flex rounded-2xl font-bold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2',
          compact
            ? 'flex-col items-center justify-center gap-1 px-2 py-2 text-[11px]'
            : 'items-center gap-3 px-3 py-3 text-sm',
          isActive
            ? 'bg-emerald-50 text-emerald-800'
            : 'text-slate-500 hover:bg-stone-50 hover:text-slate-900',
        ].join(' ')
      }
      end={item.end}
      to={item.to}
    >
      <span aria-hidden="true" className="size-5 shrink-0">
        {item.icon}
      </span>
      <span>{compact ? item.shortLabel : item.label}</span>
    </NavLink>
  )
}

function ChatIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24">
      <path
        d="M7 17.5 3.5 20v-4.2A8.5 8.5 0 1 1 7 17.5Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  )
}

function MemoryIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24">
      <path
        d="M8 5.5h8M8 9.5h5m-7.5 10h13a2 2 0 0 0 2-2v-13a2 2 0 0 0-2-2h-13a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  )
}

function ChartIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24">
      <path
        d="M5 19V9m7 10V5m7 14v-7M3 21h18"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24">
      <path
        d="M12 15.25A3.25 3.25 0 1 0 12 8.75a3.25 3.25 0 0 0 0 6.5Zm7-3.25 1.5-1.2-1.75-3.04-1.8.72a7 7 0 0 0-1.62-.94L15 5.62h-3.5l-.3 1.92a7 7 0 0 0-1.63.94l-1.81-.72L6 10.8 7.5 12 6 13.2l1.76 3.04 1.8-.72c.5.39 1.05.7 1.64.94l.3 1.92H15l.32-1.92a7 7 0 0 0 1.62-.94l1.81.72 1.75-3.04L19 12Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
    </svg>
  )
}
