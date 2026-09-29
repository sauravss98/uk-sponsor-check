import { useEffect, useState } from 'react'
import { registerInfo } from '../api'
import type { RegisterInfo } from '../types'

export function Footer() {
  const [info, setInfo] = useState<RegisterInfo | null>(null)

  useEffect(() => {
    registerInfo().then(setInfo).catch(() => setInfo(null))
  }, [])

  return (
    <footer className="mt-12 space-y-2 border-t border-slate-200 pt-6 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-500">
      <p>
        Not legal or immigration advice. A licence means an employer <em>can</em> sponsor, not
        that it will sponsor a particular role. Always confirm with the employer.
      </p>
      {info && (
        <p>
          Register data: register {info.register_date} ({info.organisations} organisations),{' '}
          <a
            href={info.source_url}
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-slate-700 dark:hover:text-slate-300"
          >
            source
          </a>
          . Salary thresholds published {info.thresholds_effective_date},{' '}
          <a
            href={info.thresholds_source_url}
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-slate-700 dark:hover:text-slate-300"
          >
            source
          </a>
          . UK Visas and Immigration, Open Government Licence v3.0.
        </p>
      )}
      <p>
        <a
          href="https://github.com/sauravss98/uk-sponsor-check"
          target="_blank"
          rel="noreferrer"
          className="underline hover:text-slate-700 dark:hover:text-slate-300"
        >
          sponsor-check
        </a>{' '}
        is open source.
      </p>
    </footer>
  )
}
