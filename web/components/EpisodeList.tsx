'use client'

import AudioPlayer from '@/components/AudioPlayer'
import { type Episode, STATUS_LABELS } from '@/lib/episodeStatus'

interface Props {
  episodes: Episode[]
  deliveryTime: string
  email: string
}

export default function EpisodeList({ episodes, deliveryTime, email }: Props) {
  if (episodes.length === 0) {
    return (
      <div>
        <p className="font-serif italic text-lg text-ink leading-relaxed">
          Your first edition arrives tomorrow at {deliveryTime}.
        </p>
        <p className="font-serif text-ink-muted text-sm mt-3 leading-relaxed">
          We'll send a link to {email}.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {episodes.map((ep) => {
        const label = new Date(ep.date + 'T12:00:00').toLocaleDateString('en-US', {
          weekday: 'long',
          month: 'long',
          day: 'numeric',
          year: 'numeric',
        })
        return (
          <div key={ep.id} className="pb-8 border-b border-rule last:border-0">
            <p className="font-mono text-[0.5625rem] text-ink-faint tracking-[0.12em] uppercase mb-3">
              {label}
            </p>
            {ep.status === 'ready' && ep.mp3_url ? (
              <div className="bg-surface px-4 py-4 md:px-5">
                <AudioPlayer title={`Episode — ${label}`} src={ep.mp3_url} />
              </div>
            ) : (
              <p className="font-serif italic text-base text-ink-muted">
                {STATUS_LABELS[ep.status] ?? ep.status}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
