type PlaceholderPageProps = {
  day: string
  description: string
  eyebrow: string
  title: string
}

export function PlaceholderPage({
  day,
  description,
  eyebrow,
  title,
}: PlaceholderPageProps) {
  return (
    <section
      aria-labelledby="placeholder-title"
      className="grid min-h-[560px] place-items-center rounded-[2rem] border border-stone-200 bg-white p-6 shadow-sm"
    >
      <div className="max-w-lg text-center">
        <span className="mx-auto mb-6 grid size-16 place-items-center rounded-3xl bg-emerald-50 text-2xl font-black text-emerald-800">
          {day}
        </span>
        <p className="text-xs font-black uppercase tracking-[0.22em] text-emerald-700">
          {eyebrow}
        </p>
        <h1
          className="mt-3 text-3xl font-black tracking-tight text-slate-950"
          id="placeholder-title"
        >
          {title}
        </h1>
        <p className="mt-4 text-base leading-7 text-slate-600">{description}</p>
        <p className="mt-7 rounded-2xl bg-stone-100 px-4 py-3 text-sm font-semibold text-slate-600">
          当前只是明确的功能占位，不包含模拟数据，也不代表功能已经完成。
        </p>
      </div>
    </section>
  )
}
