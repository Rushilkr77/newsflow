'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const ERROR_MESSAGES: Record<string, string> = {
  declined:      'Google sign-in was cancelled. Try again.',
  token_exchange: 'Could not complete sign-in. Try again.',
  profile_fetch: 'Could not read your Google account. Try again.',
  no_email:      'Could not read your Google email. Try again.',
  no_account:    'No NewsFlow account for this Google address. Request access below.',
}

function LoginInner() {
  const params = useSearchParams()
  const error = params.get('error')

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0 pt-10 md:pt-16 pb-24">
        <div className="flex items-baseline justify-between">
          <a href="/" className="masthead-text">Newsflow</a>
        </div>

        <div className="mt-12 md:mt-16 max-w-prose">
          <div className="w-8 h-0.5 bg-accent mb-6" />
          <h1 className="font-serif italic text-[1.75rem] md:text-[2.5rem] leading-[1.12]">
            Sign in.
          </h1>
          <p className="font-serif text-ink-muted mt-4 text-sm leading-relaxed">
            Use the Google account you signed up with.
          </p>

          {error && (
            <p className="field-error mt-6">
              {ERROR_MESSAGES[error] ?? 'Something went wrong. Try again.'}
            </p>
          )}

          <div className="mt-10">
            <button
              onClick={() => { window.location.href = '/api/auth/login/google' }}
              className="submit-btn"
            >
              Continue with Google
            </button>
          </div>

          <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase mt-6">
            No account?{' '}
            <a href="/" className="underline underline-offset-2 hover:text-ink-muted transition-colors">
              Request access
            </a>
          </p>
        </div>
      </div>
    </main>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  )
}
