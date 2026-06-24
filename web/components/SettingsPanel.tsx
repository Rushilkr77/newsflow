'use client'

import { useState } from 'react'
import type { SessionUser } from '@/lib/session'
import { TIMEZONES } from '@/lib/timezones'

interface Source {
  id: string
  label: string
  domain: string
  checked: boolean
}

interface Props {
  user: SessionUser
  sources: Source[]
}

export default function SettingsPanel({ user, sources }: Props) {
  const [bio, setBio] = useState(user.bio)
  const [time, setTime] = useState(user.delivery_local_time)
  const [tz, setTz] = useState(user.tz)
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(sources.map((s) => [s.id, s.checked]))
  )
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [isActive, setIsActive] = useState(user.active)
  const [disconnecting, setDisconnecting] = useState(false)

  const save = async () => {
    setSaving(true)
    setSaved(false)
    setError('')

    const enabledSources = Object.entries(checked).filter(([, v]) => v).map(([id]) => id)

    const [settingsRes, sourcesRes] = await Promise.all([
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bio, delivery_time: time, tz }),
      }),
      fetch('/api/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources: enabledSources, bio, delivery_time: time, tz }),
      }),
    ])

    if (!settingsRes.ok || !sourcesRes.ok) {
      setError('Something went wrong. Try again.')
    } else {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    }
    setSaving(false)
  }

  const disconnect = async () => {
    if (!confirm('Disconnect Gmail? Your episodes will stop until you reconnect.')) return
    setDisconnecting(true)
    await fetch('/api/disconnect', { method: 'POST' })
    setIsActive(false)
    setDisconnecting(false)
  }

  return (
    <div className="max-w-prose">

      {/* Identity */}
      <div>
        <p className="mono-caps mb-4">Identity</p>
        <p className="font-mono text-[0.5625rem] text-ink-faint tracking-[0.08em] mb-3">{user.email}</p>
        <label className="block">
          <p className="font-serif text-sm text-ink-muted mb-2">Professional context</p>
          <textarea
            className="field-input"
            rows={2}
            placeholder="Senior backend engineer at a fintech, exploring AI infra and product roles."
            value={bio}
            onChange={(e) => setBio(e.target.value)}
          />
          <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase mt-1.5">
            Used to prioritise articles relevant to your role.
          </p>
        </label>
      </div>

      {/* Delivery */}
      <div className="mt-10">
        <p className="mono-caps mb-4">Delivery</p>
        <div className="space-y-5">
          <label className="block">
            <p className="font-serif text-sm text-ink-muted mb-2">Episode ready by</p>
            <input type="time" className="field-input" value={time} onChange={(e) => setTime(e.target.value)} />
          </label>
          <label className="block">
            <p className="font-serif text-sm text-ink-muted mb-2">Timezone</p>
            <select className="field-input" value={tz} onChange={(e) => setTz(e.target.value)}>
              {TIMEZONES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Sources */}
      <div className="mt-10">
        <p className="mono-caps mb-3">Sources</p>
        <div>
          {sources.map((s) => (
            <label key={s.id} className="newsletter-row">
              <input
                type="checkbox"
                className="nf-checkbox"
                checked={checked[s.id] ?? false}
                onChange={(e) => setChecked((prev) => ({ ...prev, [s.id]: e.target.checked }))}
              />
              <div className="flex flex-col gap-0.5">
                <span className="font-serif text-sm text-ink">{s.label}</span>
                <span className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase">{s.domain}</span>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Inbox */}
      <div className="mt-10">
        <p className="mono-caps mb-3">Inbox</p>
        {isActive ? (
          <p className="font-serif text-sm text-ink-muted">
            Connected as {user.email}.{' '}
            <button
              onClick={disconnect}
              disabled={disconnecting}
              className="underline underline-offset-2 hover:no-underline transition-all text-ink"
            >
              {disconnecting ? 'Disconnecting…' : 'Disconnect'}
            </button>
          </p>
        ) : (
          <div>
            <p className="font-serif text-sm text-ink-muted mb-4">
              Gmail disconnected. Reconnect to resume episode delivery.
            </p>
            <button
              onClick={() => { window.location.href = `/api/auth/google?hint=${encodeURIComponent(user.email)}` }}
              className="submit-btn"
            >
              Reconnect Gmail
            </button>
          </div>
        )}
      </div>

      {error && <p className="field-error mt-6">{error}</p>}
      {saved && <p className="font-serif italic text-sm text-ink-muted mt-6">Saved.</p>}

      <div className="mt-10">
        <button className="submit-btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>

    </div>
  )
}
