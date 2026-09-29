import { useState, type FormEvent } from 'react'
import { ApiError, checkSalary } from '../api'
import type { SalaryResult, SalaryVerdict } from '../types'
import { VerdictBadge, type Tone } from './VerdictBadge'

const VERDICT_COPY: Record<SalaryVerdict, { label: string; tone: Tone }> = {
  meets: { label: 'Meets requirement', tone: 'good' },
  below: { label: 'Below requirement', tone: 'bad' },
  occupation_ineligible: { label: 'Occupation ineligible', tone: 'bad' },
  going_rate_unavailable: { label: 'No published rate', tone: 'neutral' },
  unknown_occupation: { label: 'Unknown occupation code', tone: 'neutral' },
}

function gbp(amount?: number | null): string {
  return amount == null ? 'unpublished' : `£${Math.round(amount).toLocaleString('en-GB')}`
}

export function SalaryCheck() {
  const [salary, setSalary] = useState('')
  const [socCode, setSocCode] = useState('')
  const [newEntrant, setNewEntrant] = useState(false)
  const [result, setResult] = useState<SalaryResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const amount = Number(salary)
    if (!amount || !socCode.trim()) return
    setLoading(true)
    setError('')
    try {
      setResult(await checkSalary(amount, socCode.trim(), newEntrant))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={salary}
            onChange={(e) => setSalary(e.target.value)}
            type="number"
            min={0}
            placeholder="Annual salary, e.g. 45000"
            className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900
                       placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2
                       focus:ring-indigo-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100
                       dark:placeholder:text-slate-500 dark:focus:ring-indigo-900"
          />
          <input
            value={socCode}
            onChange={(e) => setSocCode(e.target.value)}
            placeholder="SOC code, e.g. 2136"
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900
                       placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2
                       focus:ring-indigo-200 sm:w-48 dark:border-slate-700 dark:bg-slate-900
                       dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-indigo-900"
          />
          <button
            type="submit"
            disabled={loading || !salary || !socCode.trim()}
            className="rounded-lg bg-indigo-600 px-5 py-2.5 font-semibold text-white transition
                       hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? 'Checking…' : 'Check'}
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <input
            type="checkbox"
            checked={newEntrant}
            onChange={(e) => setNewEntrant(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          I qualify for the new entrant rate (under 26, recent graduate, in training, or an
          eligible postdoc role)
        </label>
      </form>

      {error && (
        <p className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <VerdictBadge {...VERDICT_COPY[result.verdict]} />
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Thresholds published {result.thresholds.effective_date}
            </span>
          </div>

          {result.occupation && (
            <p className="text-sm text-slate-700 dark:text-slate-300">
              <span className="font-medium">{result.soc_code}</span> — {result.occupation}
              {result.skill_level && (
                <span className="text-slate-500 dark:text-slate-400"> ({result.skill_level})</span>
              )}
            </p>
          )}

          {result.required_salary != null && (
            <p className="text-sm text-slate-700 dark:text-slate-300">
              Required: <span className="font-semibold">{gbp(result.required_salary)}</span>
              {result.verdict === 'below' && result.shortfall ? (
                <span className="text-rose-600 dark:text-rose-400">
                  {' '}
                  — short by {gbp(result.shortfall)}
                </span>
              ) : null}
            </p>
          )}

          {result.rule && (
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/60 dark:text-slate-400">
              {result.rule}
            </p>
          )}

          {result.other_options && result.other_options.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                Other ways this salary could qualify
              </p>
              <ul className="space-y-1.5">
                {result.other_options.map((o) => (
                  <li key={o.option} className="flex items-start gap-2 text-sm">
                    <span
                      className={
                        o.meets
                          ? 'mt-0.5 text-emerald-600 dark:text-emerald-400'
                          : 'mt-0.5 text-slate-400 dark:text-slate-600'
                      }
                    >
                      {o.meets ? '✓' : '·'}
                    </span>
                    <span className="text-slate-600 dark:text-slate-400">
                      <span className="font-medium text-slate-800 dark:text-slate-200">
                        {o.label}
                      </span>{' '}
                      — {gbp(o.required_salary)} — {o.condition}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <ul className="space-y-1 border-t border-slate-100 pt-3 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-400">
            {result.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
