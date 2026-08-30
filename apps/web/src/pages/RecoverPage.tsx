import { useState } from 'react'
import { Link } from 'react-router-dom'

import { publicApi, PublicApiError } from '../auth/api'
import type { RecoverInput } from '../auth/types'
import { AuthFrame, fieldClass, primaryButtonClass } from '../components/AuthFrame'

const initial: RecoverInput = {
  username: '',
  recovery_code: '',
  new_password: '',
  new_password_confirmation: '',
}

export function RecoverPage() {
  const [form, setForm] = useState(initial)
  const [nextCode, setNextCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await publicApi.recover(form)
      setNextCode(result.recovery_code)
    } catch (reason) {
      setError(reason instanceof PublicApiError ? reason.message : '账号恢复未完成。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame
      description="恢复成功会撤销全部旧会话、更新密码并轮换恢复码。"
      eyebrow="Account recovery"
      footer={<p><Link className="font-bold text-emerald-700" to="/login">返回登录</Link></p>}
      title="使用恢复码重设密码"
    >
      {nextCode ? (
        <div>
          <p className="text-sm font-bold">新恢复码（仅显示一次）</p>
          <code className="mt-2 block break-all rounded-xl bg-slate-950 p-4 text-sm text-emerald-200">{nextCode}</code>
          <Link className={`${primaryButtonClass} mt-4 block text-center`} to="/login">我已安全保存，返回登录</Link>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <RecoveryField label="用户名" value={form.username} onChange={(value) => setForm({ ...form, username: value.toLocaleLowerCase() })} />
          <RecoveryField label="恢复码" value={form.recovery_code} onChange={(value) => setForm({ ...form, recovery_code: value })} />
          <RecoveryField label="新密码" type="password" value={form.new_password} onChange={(value) => setForm({ ...form, new_password: value })} />
          <RecoveryField label="确认新密码" type="password" value={form.new_password_confirmation} onChange={(value) => setForm({ ...form, new_password_confirmation: value })} />
          {error ? <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">{error}</p> : null}
          <button className={primaryButtonClass} disabled={busy || form.new_password !== form.new_password_confirmation} type="submit">
            {busy ? '正在恢复…' : '重设密码并轮换恢复码'}
          </button>
        </form>
      )}
    </AuthFrame>
  )
}

function RecoveryField({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="block text-sm font-bold">{label}<input className={fieldClass} maxLength={256} minLength={type === 'password' ? 12 : undefined} onChange={(event) => onChange(event.target.value)} required type={type} value={value} /></label>
}
