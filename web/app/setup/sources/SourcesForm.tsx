'use client'

import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { TIMEZONES } from '@/lib/timezones'

interface Source {
  id: string
  label: string
  domain: string
  checked: boolean
}

interface Props {
  userId: string
  email: string
  sources: Source[]
  initialBio: string
  initialDeliveryTime: string
  initialTz: string
  isFirstTime: boolean
}

export default function SourcesForm({
  sources,
  initialBio,
  initialDeliveryTime,
  initialTz,
  isFirstTime,
}: Props) {
  const router = useRouter()
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(sources.map((s) => [s.id, s.checked]))
  )
  const [bio, setBio] = useState(initialBio)
  const [time, setTime] = useState(initialDeliveryTime || '07:00')
  const [tz, setTz] = useState(initialTz || 'Asia/Kolkata')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const bioRef = useRef<HTMLTextAreaElement>(null)

  const autoResize = () => {
    const el = bioRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }

  const handleSubmit = async () => {
    const enabledSources = Object.entries(checked)
      .filter(([, v]) => v)
      .map(([id]) => id)

    if (enabledSources.length === 0) {
      setError('Enable at least one newsletter.')
      return
    }

    setSaving(true)
    setError('')

    const res = await fetch('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sources: enabledSources, bio, delivery_time: time, tz }),
    })

    if (!res.ok) {
      const data = await res.json()
      setError(data.error ?? 'Something went wrong.')
      setSaving(false)
      return
    }

    router.push('/dashboard')
  }

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0 pt-10 md:pt-16 pb-24">
        <span className="masthead-text">Newsflow</span>

        <div className="mt-12 md:mt-16 max-w-prose">
          <div className="w-8 h-0.5 bg-accent mb-6" />
          <h1 className="font-serif italic text-[1.75rem] md:text-[2.5rem] leading-[1.12]">
            Set up your feed.
          </h1>
          <p className="font-serif text-ink-muted mt-4 text-sm md:text-base leading-relaxed">
            {isFirstTime
              ? "We've pre-selected the newsletters you requested. Adjust below."
              : 'Update your sources and preferences.'}
          </p>

          {/* Sources */}
          <div className="mt-10">
            <p className="mono-caps mb-1">Sources</p>
            <div className="mt-3">
              {sources.map((s) => (
                <label key={s.id} className="newsletter-row">
                  <input
                    type="checkbox"
                    className="nf-checkbox"
                    checked={checked[s.id] ?? false}
                    onChange={(e) =>
                      setChecked((prev) => ({ ...prev, [s.id]: e.target.checked }))
                    }
                  />
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="font-serif text-sm text-ink">{s.label}</span>
                    <span className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase">
                      {s.domain}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Bio */}
          <div className="mt-10">
            <label className="block">
              <p className="mono-caps mb-1">About you</p>
              <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase mt-1 mb-3">
                We use this to pick which articles matter most to you.
              </p>
              <textarea
                ref={bioRef}
                className="field-input"
                rows={2}
                placeholder="Senior backend engineer at a fintech, exploring AI infra and product roles."
                value={bio}
                onChange={(e) => { setBio(e.target.value); autoResize() }}
              />
            </label>
          </div>

          {/* Delivery */}
          <div className="mt-10">
            <p className="mono-caps mb-4">Delivery</p>
            <div className="space-y-6">
              <label className="block">
                <p className="font-serif text-sm text-ink-muted mb-2">
                  What time should your episode be ready?
                </p>
                <input
                  type="time"
                  className="field-input"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                />
                <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase mt-1.5">
                  We'll have your episode in your inbox by this time.
                </p>
              </label>

              <label className="block">
                <p className="font-serif text-sm text-ink-muted mb-2">Timezone</p>
                <select
                  className="field-input"
                  value={tz}
                  onChange={(e) => setTz(e.target.value)}
                >
                  {TIMEZONES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {error && <p className="field-error mt-6">{error}</p>}

          <div className="mt-10">
            <button
              className="submit-btn"
              onClick={handleSubmit}
              disabled={saving}
            >
              {saving ? 'Saving…' : isFirstTime ? 'Save and start tomorrow' : 'Save changes'}
            </button>
          </div>
        </div>
      </div>
    </main>
  )
}
