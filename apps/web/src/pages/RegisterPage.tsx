import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { PublicApiError } from '../auth/api'
import { useSession } from '../auth/useSession'
import type { RegisterInput } from '../auth/types'
import { AuthFrame, fieldClass, primaryButtonClass } from '../components/AuthFrame'

const initial: RegisterInput = {
  invitation_code: '',
  username: '',
  display_name: '',
  password: '',
  password_confirmation: '',
}

export function RegisterPage() {
  const { phase, register } = useSession()
  const navigate = useNavigate()
  const [form, setForm] = useState(initial)
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (phase === 'authenticated' && recoveryCode === null) return <Navigate replace to="/" />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await register(form)
      setRecoveryCode(result.recovery_code)
    } catch (reason) {
      setError(reason instanceof PublicApiError ? reason.message : '注册未完成，请检查输入。')
    } finally {
      setBusy(false)
    }
  }

  if (recoveryCode !== null) {
    return (
      <AuthFrame
        description="这是恢复码唯一一次显示。服务端只保存它的哈希；丢失后无法找回原值。"
        eyebrow="One-time recovery code"
        footer={<p>保存完成后即可开始普通对话。</p>}
        title="立即保存恢复码"
      >
        <code className="block break-all rounded-xl bg-slate-950 p-4 text-sm text-emerald-200">
          {recoveryCode}
        </code>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <button className={primaryButtonClass} onClick={() => downloadSecret(recoveryCode)} type="button">
            下载恢复码
          </button>
          <button className={primaryButtonClass} onClick={() => navigate('/', { replace: true })} type="button">
            我已安全保存
          </button>
        </div>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame
      description="注册需要一次性邀请码。用户名规范化后只允许小写字母、数字和下划线。"
      eyebrow="Invitation only"
      footer={<p>已有账号？<Link className="font-bold text-emerald-700" to="/login">返回登录</Link></p>}
      title="创建账号"
    >
      <form className="space-y-4" onSubmit={(event) => void submit(event)}>
        <Field label="邀请码" value={form.invitation_code} onChange={(value) => setForm({ ...form, invitation_code: value })} />
        <Field autoComplete="username" label="用户名" maxLength={32} value={form.username} onChange={(value) => setForm({ ...form, username: value.toLocaleLowerCase() })} />
        <Field label="显示名" maxLength={80} value={form.display_name} onChange={(value) => setForm({ ...form, display_name: value })} />
        <Field autoComplete="new-password" label="密码（至少 12 位）" minLength={12} type="password" value={form.password} onChange={(value) => setForm({ ...form, password: value })} />
        <Field autoComplete="new-password" label="确认密码" minLength={12} type="password" value={form.password_confirmation} onChange={(value) => setForm({ ...form, password_confirmation: value })} />
        <p className="rounded-xl bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-900">
          注册即表示你知悉：对话和记忆会存储在本服务，并发送给 DeepSeek 处理。请勿输入真实密钥或敏感个人信息。
        </p>
        {error ? <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">{error}</p> : null}
        <button className={primaryButtonClass} disabled={busy || form.password !== form.password_confirmation} type="submit">
          {busy ? '正在创建…' : '注册并生成恢复码'}
        </button>
      </form>
    </AuthFrame>
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  minLength,
  maxLength = 256,
  autoComplete,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  minLength?: number
  maxLength?: number
  autoComplete?: string
}) {
  return (
    <label className="block text-sm font-bold">
      {label}
      <input
        autoComplete={autoComplete}
        className={fieldClass}
        maxLength={maxLength}
        minLength={minLength}
        onChange={(event) => onChange(event.target.value)}
        required
        type={type}
        value={value}
      />
    </label>
  )
}

function downloadSecret(secret: string): void {
  const url = URL.createObjectURL(new Blob([`${secret}\n`], { type: 'text/plain;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'memtrace-recovery-code.txt'
  anchor.click()
  URL.revokeObjectURL(url)
}
