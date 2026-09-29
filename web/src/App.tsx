import { useState } from 'react'
import { Footer } from './components/Footer'
import { SalaryCheck } from './components/SalaryCheck'
import { SponsorCheck } from './components/SponsorCheck'

type Tab = 'sponsor' | 'salary'

const TABS: { id: Tab; label: string }[] = [
  { id: 'sponsor', label: 'Sponsor check' },
  { id: 'salary', label: 'Salary check' },
]

function App() {
  const [tab, setTab] = useState<Tab>('sponsor')

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        <header className="mb-8 space-y-2">
          <h1 className="text-2xl font-bold tracking-tight">sponsor-check</h1>
          <p className="text-slate-600 dark:text-slate-400">
            Check whether a UK employer holds a Home Office sponsor licence, and whether a
            salary meets the Skilled Worker requirement.
          </p>
        </header>

        <nav className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-900">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition ${
                tab === t.id
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <main>{tab === 'sponsor' ? <SponsorCheck /> : <SalaryCheck />}</main>

        <Footer />
      </div>
    </div>
  )
}

export default App
