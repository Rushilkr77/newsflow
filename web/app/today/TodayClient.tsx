'use client'

import { useState } from 'react'
import AudioPlayer from '@/components/AudioPlayer'
import type { SessionUser } from '@/lib/session'

interface Episode {
  id: string
  date: string
  mp3_url: string | null
  script_path: string | null
  status: string
}

interface Props {
  user: SessionUser
  dateline: string
  today: string
  episode: Episode | null
  prevEpisode: Episode | null
  sources: string[]
}

const STATUS_LABELS: Record<string, string> = {
  queued:      'Queued for assembly.',
  generating:  'Being assembled now.',
  ready:       'Ready.',
  failed:      "Didn't print today.",
  empty_inbox: 'No issues arrived overnight.',
}

export default function TodayClient({ user, dateline, episode, prevEpisode, sources }: Props) {
  const [showPlayer, setShowPlayer] = useState(false)

  const isFirstDay = !episode && !prevEpisode
  const isGenerating = episode?.status === 'generating' || episode?.status === 'queued'
  const isFailed = episode?.status === 'failed'
  const isEmpty = episode?.status === 'empty_inbox'
  const isReady = episode?.status === 'ready'

  const sourceLabel = sources
    .map((s) => s.replace(/_/g, '.'))
    .join(' · ')

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0">

        {/* Header */}
        <header className="pt-8 pb-0 md:pt-12">
          <div className="flex flex-col gap-1.5 md:flex-row md:items-baseline md:justify-between">
            <span className="masthead-text">Newsflow</span>
            <div className="flex items-center gap-4">
              <span className="font-mono text-2xs text-ink-muted tracking-wide">{user.email}</span>
              <a href="/settings" className="mono-caps hover:text-ink transition-colors">Settings</a>
            </div>
          </div>
        </header>

        <hr className="rule mt-4" />

        <section className="mt-8 md:mt-10 max-w-prose">

          {/* Dateline */}
          <p className="font-mono text-[0.5625rem] text-ink-faint tracking-[0.12em] uppercase">
            {dateline}
          </p>

          {/* Episode status */}
          {isFirstDay && (
            <div className="mt-6">
              <div className="w-8 h-0.5 bg-accent mb-5" />
              <p className="font-serif italic text-lg text-ink leading-relaxed">
                Your first edition arrives tomorrow at {user.delivery_local_time}.
              </p>
              <p className="font-serif text-ink-muted text-sm mt-3 leading-relaxed">
                We'll pull from {sources.length > 0 ? sourceLabel : 'your selected newsletters'} and
                send a link to {user.email}.
              </p>
            </div>
          )}

          {isGenerating && (
            <div className="mt-6">
              <div className="w-8 h-0.5 bg-accent mb-5" />
              <p className="font-serif italic text-lg text-ink">
                {STATUS_LABELS[episode?.status ?? 'queued']}
              </p>
              <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.1em] uppercase mt-3">
                Check your inbox when it's done — or refresh this page.
              </p>
            </div>
          )}

          {(isFailed || isEmpty) && (
            <div className="mt-6">
              <div className="w-8 h-0.5 bg-accent mb-5" />
              <p className="font-serif italic text-lg text-ink">
                {STATUS_LABELS[episode?.status ?? 'failed']}
              </p>
              {prevEpisode?.status === 'ready' && (
                <p className="font-serif text-ink-muted text-sm mt-3">
                  Yesterday's edition is below.
                </p>
              )}
            </div>
          )}

          {isReady && episode?.mp3_url && (
            <div className="mt-6">
              <div className="w-8 h-0.5 bg-accent mb-5" />
              <p className="font-serif italic text-lg md:text-xl text-ink leading-[1.2]">
                Today's edition is ready.
              </p>

              {!showPlayer ? (
                <div className="mt-5">
                  <p className="font-serif text-ink-muted text-sm">
                    Sent to {user.email} at {user.delivery_local_time}.{' '}
                    <button
                      onClick={() => setShowPlayer(true)}
                      className="text-ink underline underline-offset-2 hover:no-underline transition-all"
                    >
                      Listen on web
                    </button>
                  </p>
                </div>
              ) : (
                <div className="mt-5 bg-surface px-4 py-4 md:px-5">
                  <AudioPlayer title="Today's episode" src={episode.mp3_url} />
                </div>
              )}
            </div>
          )}

          {/* Previous episode fallback when today failed/empty */}
          {(isFailed || isEmpty) && prevEpisode?.status === 'ready' && prevEpisode.mp3_url && (
            <div className="mt-8 pt-8 border-t border-rule">
              <p className="mono-caps text-ink-faint mb-4">
                {new Date(prevEpisode.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </p>
              <div className="bg-surface px-4 py-4 md:px-5">
                <AudioPlayer title="Yesterday's episode" src={prevEpisode.mp3_url} />
              </div>
            </div>
          )}

          {/* Source footer */}
          {sourceLabel && (
            <div className="mt-12 pt-6 border-t border-rule">
              <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase">
                Sources: {sourceLabel}
              </p>
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
