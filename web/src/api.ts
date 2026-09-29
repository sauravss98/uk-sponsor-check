import type { CheckResult, Match, RegisterInfo, SalaryResult } from './types'

export class ApiError extends Error {}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join('; ')
      : typeof detail === 'string'
        ? detail
        : `Request failed (${resp.status})`
    throw new ApiError(message)
  }
  return resp.json() as Promise<T>
}

export function checkSponsor(company: string, route: string): Promise<CheckResult> {
  const params = new URLSearchParams({ company, route })
  return fetch(`/api/check?${params}`).then((r) => json(r))
}

export function searchSponsors(q: string, limit = 5): Promise<Match[]> {
  const params = new URLSearchParams({ q, limit: String(limit) })
  return fetch(`/api/search?${params}`).then((r) => json(r))
}

export function checkSalary(
  salary: number,
  socCode: string,
  newEntrant: boolean,
): Promise<SalaryResult> {
  return fetch('/api/salary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ salary, soc_code: socCode, new_entrant: newEntrant }),
  }).then((r) => json(r))
}

export function registerInfo(): Promise<RegisterInfo> {
  return fetch('/api/register-info').then((r) => json(r))
}
