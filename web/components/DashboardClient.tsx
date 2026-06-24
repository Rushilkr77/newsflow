'use client'

import { useState } from 'react'
import type { SessionUser } from '@/lib/session'
import type { Episode } from '@/lib/episodeStatus'
import EpisodeList from '@/components/EpisodeList'
import SettingsPanel from '@/components/SettingsPanel'

interface Source {
  id: string
  label: string
  domain: string
  checked: boolean
}

type View = 'episodes' | 'settings'

interface Props {
  user: SessionUser
  episodes: Episode[]
  sources: Source[]
}

export default function DashboardClient({ user, episodes, sources }: Props) {
  const [view, setView] = useState<View>('episodes')

  const signOut = async () => {
    await fetch('/api/logout', { method: 'POST' })
    window.location.href = '/'
  }

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0">

        {/* Mobile top nav */}
        <header className="flex md:hidden pt-8 flex-col">
          <div className="flex items-baseline justify-between">
            <span className="masthead-text">Newsflow</span>
            <button onClick={signOut} className="mono-caps text-ink-faint hover:text-ink transition-colors">
              Sign out
            </button>
          </div>
          <nav className="flex gap-6 mt-5">
            <button
              onClick={() => setView('episodes')}
              className={`mono-caps transition-colors ${view === 'episodes' ? 'text-ink' : 'text-ink-faint hover:text-ink-muted'}`}
            >
              Episodes
            </button>
            <button
              onClick={() => setView('settings')}
              className={`mono-caps transition-colors ${view === 'settings' ? 'text-ink' : 'text-ink-faint hover:text-ink-muted'}`}
            >
              Settings
            </button>
          </nav>
          <hr className="rule mt-4" />
        </header>

        {/* Layout wrapper — sidebar visible on desktop only */}
        <div className="md:flex md:gap-16 md:pt-12">

          {/* Desktop sidebar */}
          <aside className="hidden md:flex md:flex-col w-44 shrink-0">
            <span className="masthead-text block mb-10">Newsflow</span>
            <nav className="flex flex-col gap-3">
              <button
                onClick={() => setView('episodes')}
                className={`mono-caps text-left transition-colors ${view === 'episodes' ? 'text-ink' : 'text-ink-faint hover:text-ink-muted'}`}
              >
                Episodes
              </button>
              <button
                onClick={() => setView('settings')}
                className={`mono-caps text-left transition-colors ${view === 'settings' ? 'text-ink' : 'text-ink-faint hover:text-ink-muted'}`}
              >
                Settings
              </button>
            </nav>
            <div className="mt-10">
              <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase mb-2 break-all">
                {user.email}
              </p>
              <button onClick={signOut} className="mono-caps text-ink-faint hover:text-ink transition-colors">
                Sign out
              </button>
            </div>
          </aside>

          {/* Content — shared between mobile and desktop */}
          <div className="flex-1 min-w-0 pt-8 md:pt-0 pb-24">
            <div className="w-8 h-0.5 bg-accent mb-8" />
            {view === 'episodes' ? (
              <EpisodeList
                episodes={episodes}
                deliveryTime={user.delivery_local_time}
                email={user.email}
              />
            ) : (
              <SettingsPanel user={user} sources={sources} />
            )}
          </div>

        </div>
      </div>
    </main>
  )
}
