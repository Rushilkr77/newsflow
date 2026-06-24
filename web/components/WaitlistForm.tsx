'use client'

import { useState, useRef, useCallback } from 'react'

const NEWSLETTERS = [
  { id: 'tldr_ai',       name: 'TLDR AI',       domain: 'tldr.tech/ai' },
  { id: 'tldr_tech',     name: 'TLDR Tech',      domain: 'tldr.tech' },
  { id: 'tldr_dev',      name: 'TLDR Dev',       domain: 'tldr.tech/dev' },
  { id: 'techcrunch',    name: 'TechCrunch',     domain: 'techcrunch.com' },
  { id: 'ettech',        name: 'ETtech',          domain: 'economictimes.indiatimes.com' },
  { id: 'harper_carroll', name: 'Harper Carroll', domain: 'harpercarroll.com' },
  { id: 'et_ai',         name: 'ET AI',           domain: 'economictimes.indiatimes.com' },
] as const

type NewsletterID = (typeof NEWSLETTERS)[number]['id']

type SubmitState =
  | { type: 'idle' }
  | { type: 'loading' }
  | { type: 'error'; message: string }
  | { type: 'already_exists'; email: string }
  | { type: 'success'; email: string; count: number; status: 'approved' | 'pending' }

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

export default function WaitlistForm() {
  const [email, setEmail]       = useState('')
  const [checked, setChecked]   = useState<Set<NewsletterID>>(new Set())
  const [other, setOther]       = useState('')
  const [state, setState]       = useState<SubmitState>({ type: 'idle' })
  const [emailTouched, setEmailTouched] = useState(false)
  const textareaRef             = useRef<HTMLTextAreaElement>(null)

  const toggleNewsletter = useCallback((id: NewsletterID) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const handleOtherChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setOther(e.target.value)
    // Auto-grow
    const el = e.target
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [])

  const emailError =
    emailTouched && email.length > 0 && !isValidEmail(email)
      ? "That email doesn't look right."
      : null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setEmailTouched(true)

    if (!isValidEmail(email)) return
    if (checked.size === 0 && !other.trim()) return

    setState({ type: 'loading' })

    try {
      const res = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          newsletters: Array.from(checked),
          other_text: other.trim(),
        }),
      })

      const data = await res.json()

      if (!res.ok) {
        setState({ type: 'error', message: data.error ?? 'Something went wrong. Try again.' })
        return
      }

      if (data.already_signed_up) {
        setState({ type: 'already_exists', email: data.email })
        return
      }

      setState({
        type: 'success',
        email: data.email,
        count: data.newsletter_count,
        status: data.status,
      })
    } catch {
      setState({ type: 'error', message: 'Connection error. Check your internet and try again.' })
    }
  }

  if (state.type === 'already_exists') {
    return (
      <div className="confirmation-enter max-w-prose">
        <p className="font-serif text-xl text-ink mb-4 leading-snug">
          You already have an account.
        </p>
        <p className="font-serif text-sm text-ink leading-relaxed mb-8">
          Sign in with the Google account linked to {state.email}.
        </p>
        <button
          onClick={() => { window.location.href = '/login' }}
          className="submit-btn"
        >
          Sign in
        </button>
      </div>
    )
  }

  if (state.type === 'success') {
    return (
      <div className="confirmation-enter max-w-prose">
        <p className="font-serif text-xl text-ink mb-4 leading-snug">
          Request received.
        </p>
        <p className="font-serif text-sm text-ink leading-relaxed mb-8">
          {state.status === 'approved'
            ? "We already support every newsletter on your list. You'll have an invite link in your inbox within minutes."
            : "We'll email when your parsers are ready, usually within 1–2 days."}
        </p>
        <p className="font-mono text-2xs text-ink-muted tracking-wider uppercase leading-loose">
          EMAIL: {state.email}
          {' · '}
          NEWSLETTERS REQUESTED: {state.count}
          {' · '}
          STATUS: {state.status === 'approved' ? 'APPROVED' : 'REVIEWING'}
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="max-w-prose">
      {/* Section heading */}
      <h2 className="font-serif text-2xl text-ink mb-2 leading-tight">
        Request access.
      </h2>
      <p className="font-serif text-sm text-ink-muted leading-relaxed mb-10">
        v0 is invite-only. Tell us what you read; we'll get you in.
      </p>

      {/* Field 1: Gmail address */}
      <div className="mb-8">
        <label
          htmlFor="email"
          className="block font-serif text-xs text-ink-muted mb-2 tracking-wide"
        >
          Gmail address
        </label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onBlur={() => setEmailTouched(true)}
          placeholder="you@gmail.com"
          className="field-input"
          autoComplete="email"
          autoCapitalize="none"
          inputMode="email"
        />
        {emailError ? (
          <p className="field-error">{emailError}</p>
        ) : (
          <p className="mono-caps mt-2">This is the inbox we'll read newsletters from</p>
        )}
      </div>

      {/* Field 2: Newsletter checklist */}
      <div className="mb-8">
        <p className="font-serif text-xs text-ink-muted mb-1 tracking-wide">
          Which newsletters do you read?
        </p>
        <p className="mono-caps mb-4">Select all that apply</p>

        <div role="group" aria-label="Supported newsletters">
          {NEWSLETTERS.map((nl) => (
            <label key={nl.id} className="newsletter-row" htmlFor={`nl-${nl.id}`}>
              <input
                type="checkbox"
                id={`nl-${nl.id}`}
                className="nf-checkbox"
                checked={checked.has(nl.id)}
                onChange={() => toggleNewsletter(nl.id)}
              />
              <span className="flex-1 min-w-0">
                <span className="font-serif text-sm text-ink block leading-tight">
                  {nl.name}
                </span>
                <span className="font-mono text-2xs text-ink-faint block mt-0.5 leading-tight">
                  {nl.domain}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Field 3: Other newsletters */}
      <div className="mb-10">
        <label
          htmlFor="other"
          className="block font-serif text-xs text-ink-muted mb-2 tracking-wide"
        >
          Anything else?
        </label>
        <textarea
          ref={textareaRef}
          id="other"
          value={other}
          onChange={handleOtherChange}
          placeholder="Newsletter we don't have yet? List them here."
          className="field-input"
          rows={3}
        />
        <p className="mono-caps mt-2">
          Optionally forward a couple of recent issues to{' '}
          <span className="text-ink-muted not-italic">rushilmisc77@gmail.com</span>
          {' '}so we can build a parser.
        </p>
      </div>

      {/* Error state */}
      {state.type === 'error' && (
        <p className="field-error mb-4">{state.message}</p>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={state.type === 'loading'}
        className="submit-btn w-full md:w-auto"
      >
        {state.type === 'loading' ? (
          <span className="inline-flex items-center gap-2">
            <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
            Submitting
          </span>
        ) : (
          'Request access'
        )}
      </button>

      <p className="mono-caps mt-4">
        We read every request. Expect a reply within 24–48 hours.
      </p>
    </form>
  )
}
