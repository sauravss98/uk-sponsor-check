// Mirrors the JSON shapes returned by src/sponsor_check/{register,salary}.py.
// Keep these in sync by hand: there's no shared schema between the Python and
// TypeScript sides yet (see the "next steps" note in web/README.md).

export interface Route {
  route: string
  rating: 'A' | 'B' | 'Provisional' | 'Unknown'
  type: string
}

export interface Match {
  name: string
  town: string
  county: string
  routes: Route[]
  score: number
}

export type SponsorVerdict = 'licensed' | 'licensed_other_routes' | 'possible_match' | 'not_found'

export interface CheckResult {
  query: string
  route: string
  register_date: string
  verdict: SponsorVerdict
  matches: Match[]
  notes: string[]
}

export interface RegisterInfo {
  source_url: string
  register_date: string
  built_at: string
  rows: string
  organisations: string
  thresholds_effective_date: string
  thresholds_source_url: string
}

export type SalaryVerdict =
  | 'meets'
  | 'below'
  | 'occupation_ineligible'
  | 'going_rate_unavailable'
  | 'unknown_occupation'

export interface SalaryOption {
  option: string
  label: string
  condition: string
  required_salary: number
  meets: boolean
}

export interface SalaryResult {
  salary: number
  soc_code: string
  route: string
  basis: 'standard' | 'new_entrant'
  thresholds: { effective_date: string; source_url: string }
  occupation?: string
  skill_level?: string
  general_threshold?: number
  going_rate?: number | null
  verdict: SalaryVerdict
  required_salary: number | null
  shortfall?: number
  rule: string
  other_options?: SalaryOption[]
  notes: string[]
}
