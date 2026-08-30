import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { PublicApiError } from '../auth/api'
import { useSession } from '../auth/useSession'
import { AuthFrame, fieldClass, primaryButtonClass } from '../components/AuthFrame'

export function LoginPage() {
  const { phase, login } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (phase === 'authenticated') return <Navigate replace to="/" />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login({ username, password })
      const target =
        typeof location.state === 'object' &&
        location.state !== null &&
        'from' in location.state &&
        typeof location.state.from === 'string'
          ? location.state.from
          : '/'
      navigate(target, { replace: true })
    } catch (reason) {
      setError(publicMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame
      description="使用本地账号进入。登录失败始终返回相同提示，不会泄露用户名是否存在。"
      eyebrow="Public account"
      footer={
        <p>
          没有账号？<Link className="font-bold text-emerald-700" to="/register">使用邀请码注册</Link>
          {' · '}
          <Link className="font-bold text-emerald-700" to="/recover">使用恢复码</Link>
        </p>
      }
      title="登录 MemTrace"
    >
      <form className="space-y-4" onSubmit={(event) => void submit(event)}>
        <label className="block text-sm font-bold">
          用户名
          <input
            autoComplete="username"
            className={fieldClass}
            maxLength={32}
            onChange={(event) => setUsername(event.target.value)}
            required
            value={username}
          />
        </label>
        <label className="block text-sm font-bold">
          密码
          <input
            autoComplete="current-password"
            className={fieldClass}
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {error ? <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">{error}</p> : null}
        <button className={primaryButtonClass} disabled={busy} type="submit">
          {busy ? '正在登录…' : '登录'}
        </button>
      </form>
      <p className="mt-5 rounded-xl bg-stone-50 px-3 py-3 text-xs leading-5 text-slate-500">
        为提供对话和记忆能力，你提交的对话会存储在本服务，并发送给配置的 DeepSeek 模型处理。API Key 仅保存在服务端。
      </p>
    </AuthFrame>
  )
}

function publicMessage(reason: unknown): string {
  if (reason instanceof PublicApiError) {
    if (reason.code === 'RATE_LIMITED' && reason.retryAfterSeconds !== null) {
      return `尝试次数过多，请在约 ${reason.retryAfterSeconds} 秒后重试。`
    }
    return reason.message
  }
  return '登录未完成，请稍后重试。'
}
