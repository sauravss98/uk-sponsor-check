export type Tone = 'good' | 'warn' | 'bad' | 'neutral'

const TONE_CLASSES: Record<Tone, string> = {
  good: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  warn: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  bad: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  neutral: 'bg-slate-200 text-slate-700 dark:bg-slate-700/60 dark:text-slate-300',
}

export function VerdictBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  )
}
