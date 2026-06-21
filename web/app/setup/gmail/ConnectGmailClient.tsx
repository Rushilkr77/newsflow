'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

interface Props {
  email: string
}

function ConnectGmailInner({ email }: Props) {
  const params = useSearchParams()
  const error = params.get('error')
  const authedAs = params.get('authed')

  const handleConnect = () => {
    window.location.href = `/api/auth/google?hint=${encodeURIComponent(email)}`
  }

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0 pt-10 md:pt-16">
        <span className="masthead-text">Newsflow</span>

        <div className="mt-12 md:mt-16 max-w-prose">
          <div className="w-8 h-0.5 bg-accent mb-6" />

          <h1 className="font-serif italic text-[1.75rem] md:text-[2.5rem] leading-[1.12] text-ink">
            Connect {email}.
          </h1>

          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="mono-caps">Read-only</span>
            <span className="font-mono text-[0.45rem] text-ink-faint">·</span>
            <span className="mono-caps">Never sends</span>
            <span className="font-mono text-[0.45rem] text-ink-faint">·</span>
            <span className="mono-caps">Encrypted at rest</span>
          </div>

          <details className="mt-7 group">
            <summary className="mono-caps cursor-pointer list-none flex items-center gap-2 hover:text-ink transition-colors">
              <span className="text-ink-faint group-open:rotate-90 transition-transform inline-block">›</span>
              What we access
            </summary>
            <div className="mt-4 space-y-3 pl-4 border-l border-rule">
              {[
                ['gmail.readonly', 'Read newsletter emails from configured senders only. We never touch other mail.'],
                ['No compose access', "We can't send email from your account. Your outbox is untouched."],
                ['No delete access', 'Emails are never moved, archived, or deleted.'],
              ].map(([scope, desc]) => (
                <div key={scope}>
                  <p className="font-mono text-[0.5625rem] text-ink tracking-[0.08em]">{scope}</p>
                  <p className="font-serif text-sm text-ink-muted mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </details>

          {error === 'wrong_account' && authedAs && (
            <p className="mt-6 font-serif italic text-sm text-accent">
              You signed in as {authedAs} but requested access for {email}. Sign in with {email}.
            </p>
          )}

          {error === 'declined' && (
            <p className="mt-6 font-serif italic text-sm text-accent">
              Google declined the request. Try again, or use a different account.
            </p>
          )}

          {error === 'gmail_scope_missing' && (
            <p className="mt-6 font-serif italic text-sm text-accent">
              Gmail access was not granted. Make sure to allow the Gmail permission on Google's consent screen.
            </p>
          )}

          {error && error !== 'wrong_account' && error !== 'declined' && error !== 'gmail_scope_missing' && (
            <p className="mt-6 font-serif italic text-sm text-accent">
              Something went wrong. Try again.
            </p>
          )}

          <div className="mt-10">
            <button onClick={handleConnect} className="submit-btn">
              Continue with Google
            </button>
          </div>

          <p className="mt-4 font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase">
            <a href="/privacy" className="underline underline-offset-2 hover:text-ink-muted transition-colors">
              Privacy policy
            </a>
          </p>
        </div>
      </div>
    </main>
  )
}

export default function ConnectGmailClient({ email }: Props) {
  return (
    <Suspense fallback={null}>
      <ConnectGmailInner email={email} />
    </Suspense>
  )
}
