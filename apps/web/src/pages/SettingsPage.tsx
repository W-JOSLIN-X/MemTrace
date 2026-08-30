import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { publicApi, PublicApiError } from '../auth/api'
import { useSession } from '../auth/useSession'
import type { SystemInfo } from '../auth/types'

export function SettingsPage() {
  const { session, refresh, clear } = useSession()
  const navigate = useNavigate()
  const [system, setSystem] = useState<SystemInfo | null>(null)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteUsername, setDeleteUsername] = useState('')
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void publicApi.system(controller.signal).then(setSystem).catch((reason) => {
      if (!controller.signal.aborted) setError(text(reason, '无法读取系统信息。'))
    })
    return () => controller.abort()
  }, [])

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await action()
      setStatus(success)
    } catch (reason) {
      setError(text(reason, '操作未完成。'))
    } finally {
      setBusy(false)
    }
  }

  async function changeDefault(mode: 'on' | 'off') {
    await run(async () => {
      await publicApi.updateMemoryDefault(mode)
      await refresh()
    }, '新对话默认记忆模式已更新。')
  }

  async function changePassword() {
    await run(async () => {
      await publicApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirmation: confirmPassword,
      })
      clear()
      navigate('/login', { replace: true })
    }, '密码已更新，所有设备需要重新登录。')
  }

  async function rotateRecovery() {
    setBusy(true)
    setError(null)
    try {
      const result = await publicApi.rotateRecoveryCode()
      setRecoveryCode(result.recovery_code)
      setStatus('旧恢复码已失效。新恢复码仅显示这一次。')
    } catch (reason) {
      setError(text(reason, '恢复码轮换未完成。'))
    } finally {
      setBusy(false)
    }
  }

  async function logoutEverywhere() {
    await run(async () => {
      await publicApi.logoutAll()
      clear()
      navigate('/login', { replace: true })
    }, '全部会话已退出。')
  }

  async function deleteAccount() {
    if (deleteUsername !== session?.account.username) {
      setError('手动输入的用户名与当前账号不一致。')
      return
    }
    await run(async () => {
      await publicApi.deleteAccount({
        current_password: deletePassword,
        confirm_username: deleteUsername,
      })
      clear()
      navigate('/login', { replace: true })
    }, '账号已永久删除。')
  }

  return (
    <div className="page-shell space-y-5" aria-labelledby="settings-title">
      <header className="page-heading">
        <p className="eyebrow">Public release</p>
        <h1 id="settings-title">系统设置</h1>
        <p>账号、额度、真实 Provider 诊断与安全操作。API Key 只在服务端配置。</p>
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {status ? <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">{status}</p> : null}

      <section className="memory-detail" aria-labelledby="account-settings">
        <h2 id="account-settings">当前账号与额度</h2>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <Info label="用户名" value={session?.account.username ?? '—'} />
          <Info label="显示名" value={session?.account.display_name ?? '—'} />
          <Info label="今日剩余真实模型轮次" value={`${session?.quota.remaining ?? 0} / ${session?.quota.limit ?? 50}`} />
          <Info label="额度重置时间（UTC）" value={session?.quota.resets_at ?? '—'} />
        </dl>
        <label className="mt-5 block text-sm font-bold">新对话默认记忆模式
          <select className="ml-3 rounded-xl border border-stone-300 px-3 py-2" disabled={busy} onChange={(event) => void changeDefault(event.target.value as 'on' | 'off')} value={session?.account.default_memory_mode ?? 'on'}>
            <option value="on">启用</option><option value="off">关闭</option>
          </select>
        </label>
      </section>

      <section className="memory-detail" aria-labelledby="runtime-settings">
        <h2 id="runtime-settings">运行与安全信息</h2>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <Info label="版本 / revision" value={system ? `${system.version} / ${system.revision}` : '载入中'} />
          <Info label="契约 / 迁移" value={system ? `${system.schema_version} / ${system.migration}` : '载入中'} />
          <Info label="Provider / 模型" value={system ? `${system.provider_mode} / ${system.model}` : '载入中'} />
          <Info label="Key 已配置" value={system?.key_configured ? '是（仅布尔值）' : '否'} />
          <Info label="记忆预算" value={system ? `${system.memory_budget_per_card} token/卡，${system.memory_budget_total} token/轮` : '载入中'} />
          <Info label="工具白名单" value={system?.tool_allowlist.join('、') ?? '载入中'} />
        </dl>
      </section>

      <section className="memory-detail" aria-labelledby="security-settings">
        <h2 id="security-settings">密码、恢复码与会话</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-3 rounded-2xl border border-stone-200 p-4">
            <h3 className="font-black">修改密码</h3>
            <SecretInput label="当前密码" value={currentPassword} onChange={setCurrentPassword} />
            <SecretInput label="新密码" value={newPassword} onChange={setNewPassword} />
            <SecretInput label="确认新密码" value={confirmPassword} onChange={setConfirmPassword} />
            <button disabled={busy || newPassword.length < 12 || newPassword !== confirmPassword} onClick={() => void changePassword()} type="button">修改并退出全部设备</button>
          </div>
          <div className="space-y-3 rounded-2xl border border-stone-200 p-4">
            <h3 className="font-black">恢复码与会话</h3>
            <button disabled={busy} onClick={() => void rotateRecovery()} type="button">轮换恢复码</button>
            <button disabled={busy} onClick={() => void logoutEverywhere()} type="button">退出全部设备</button>
            {recoveryCode ? <code className="block break-all rounded-xl bg-slate-950 p-3 text-xs text-emerald-200">{recoveryCode}</code> : null}
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-rose-200 bg-rose-50 p-5" aria-labelledby="delete-account">
        <h2 className="font-black text-rose-950" id="delete-account">永久删除账号</h2>
        <p className="mt-2 text-sm leading-6 text-rose-800">将事务级删除该 owner 的对话、记忆、事件、Pack 和全部会话，无法撤销。</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <SecretInput label="当前密码" value={deletePassword} onChange={setDeletePassword} />
          <label className="block text-sm font-bold text-rose-950">手动输入用户名<input className="mt-1 w-full rounded-xl border border-rose-300 bg-white px-3 py-2" onChange={(event) => setDeleteUsername(event.target.value)} value={deleteUsername} /></label>
        </div>
        <button className="mt-4 rounded-xl bg-rose-700 px-4 py-2 text-sm font-black text-white disabled:opacity-50" disabled={busy || !deletePassword || deleteUsername !== session?.account.username} onClick={() => void deleteAccount()} type="button">永久删除我的账号</button>
      </section>
    </div>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-stone-50 px-3 py-3"><dt className="text-xs font-bold text-slate-500">{label}</dt><dd className="mt-1 break-all text-sm font-black">{value}</dd></div>
}

function SecretInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block text-sm font-bold">{label}<input autoComplete="new-password" className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-2" maxLength={128} minLength={12} onChange={(event) => onChange(event.target.value)} type="password" value={value} /></label>
}

function text(reason: unknown, fallback: string): string {
  return reason instanceof PublicApiError ? reason.message : fallback
}
