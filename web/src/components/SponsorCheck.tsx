import { useState, type FormEvent } from 'react'
import { ApiError, checkSponsor } from '../api'
import type { CheckResult, SponsorVerdict } from '../types'
import { VerdictBadge, type Tone } from './VerdictBadge'

const ROUTES = [
  'Skilled Worker',
  'Global Business Mobility: Senior or Specialist Worker',
  'Scale-up',
  'Creative Worker',
  'Health and Care Worker',
]

const VERDICT_COPY: Record<SponsorVerdict, { label: string; tone: Tone }> = {
  licensed: { label: 'Licensed', tone: 'good' },
  licensed_other_routes: { label: 'Licensed, other routes only', tone: 'warn' },
  possible_match: { label: 'Possible match', tone: 'warn' },
  not_found: { label: 'Not found', tone: 'bad' },
}

export function SponsorCheck() {
  const [company, setCompany] = useState('')
  const [route, setRoute] = useState(ROUTES[0])
  const [result, setResult] = useState<CheckResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!company.trim()) return
    setLoading(true)
    setError('')
    try {
      setResult(await checkSponsor(company.trim(), route))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row">
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="Employer name, e.g. Synthesia"
          className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900
                     placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2
                     focus:ring-indigo-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100
                     dark:placeholder:text-slate-500 dark:focus:ring-indigo-900"
        />
        <select
          value={route}
          onChange={(e) => setRoute(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900
                     focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200
                     dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-indigo-900"
        >
          {ROUTES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={loading || !company.trim()}
          className="rounded-lg bg-indigo-600 px-5 py-2.5 font-semibold text-white transition
                     hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Checking…' : 'Check'}
        </button>
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
              Register date: {result.register_date}
            </span>
          </div>

          {result.matches.length > 0 ? (
            <ul className="space-y-3">
              {result.matches.map((m, i) => (
                <li key={i} className="rounded-lg border border-slate-100 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{m.name}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {[m.town, m.county].filter(Boolean).join(', ') || 'Location not given'} · score{' '}
                      {m.score}
                    </span>
                  </div>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {m.routes.map((r, j) => (
                      <li
                        key={j}
                        className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                      >
                        {r.route} · {r.rating}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">No candidates found.</p>
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
