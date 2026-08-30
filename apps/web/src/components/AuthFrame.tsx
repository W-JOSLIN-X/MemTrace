import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export function AuthFrame({
  eyebrow,
  title,
  description,
  children,
  footer,
}: {
  eyebrow: string
  title: string
  description: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-stone-50 px-4 py-10">
      <section className="w-full max-w-md rounded-3xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
        <Link className="inline-flex items-center gap-3 text-slate-900" to="/login">
          <span className="grid size-10 place-items-center rounded-2xl bg-emerald-700 font-black text-white">
            M
          </span>
          <span className="font-black">MemTrace</span>
        </Link>
        <header className="mt-8">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-emerald-700">
            {eyebrow}
          </p>
          <h1 className="mt-2 text-2xl font-black tracking-tight">{title}</h1>
          <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
        </header>
        <div className="mt-6">{children}</div>
        <footer className="mt-6 border-t border-stone-200 pt-5 text-sm text-slate-500">
          {footer}
        </footer>
      </section>
    </main>
  )
}

export const fieldClass =
  'mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100'

export const primaryButtonClass =
  'w-full rounded-xl bg-emerald-700 px-4 py-3 text-sm font-black text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50'
