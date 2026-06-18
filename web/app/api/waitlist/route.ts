import { NextRequest, NextResponse } from 'next/server'
import { randomBytes } from 'crypto'
import { createServiceClient } from '@/lib/supabase'
import { sendMagicLink, sendAdminAlert } from '@/lib/email'

const SUPPORTED_SOURCES = new Set([
  'tldr_ai', 'tldr_tech', 'tldr_dev',
  'techcrunch', 'ettech', 'harper_carroll', 'et_ai',
])

export async function POST(req: NextRequest) {
  let body: { email?: string; newsletters?: string[]; other_text?: string }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid request body.' }, { status: 400 })
  }

  const { email = '', newsletters = [], other_text = '' } = body

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: "That email doesn't look right." }, { status: 400 })
  }

  if (newsletters.length === 0 && !other_text.trim()) {
    return NextResponse.json(
      { error: 'Select at least one newsletter or tell us what you read.' },
      { status: 400 }
    )
  }

  const db = createServiceClient()
  const allSupported = newsletters.every((n) => SUPPORTED_SOURCES.has(n))
  const hasOther = other_text.trim().length > 0
  const autoApprove = allSupported && !hasOther

  // Idempotent — return existing signup state
  const { data: existing } = await db
    .from('waitlist_signups')
    .select('id, status, email')
    .eq('email', email)
    .maybeSingle()

  if (existing) {
    return NextResponse.json({
      status: existing.status,
      email: existing.email,
      newsletter_count: newsletters.length + (hasOther ? 1 : 0),
      already_signed_up: true,
    })
  }

  let magic_token: string | null = null
  let magic_token_expires_at: string | null = null
  const status = autoApprove ? 'approved' : 'pending'

  if (autoApprove) {
    magic_token = randomBytes(32).toString('hex')
    const expires = new Date()
    expires.setDate(expires.getDate() + 7)
    magic_token_expires_at = expires.toISOString()
  }

  const { error: insertError } = await db.from('waitlist_signups').insert({
    email,
    newsletter_picks: newsletters,
    other_text: other_text.trim(),
    status,
    magic_token,
    magic_token_expires_at,
  })

  if (insertError) {
    console.error('Waitlist insert error:', insertError)
    return NextResponse.json({ error: 'Something went wrong. Try again.' }, { status: 500 })
  }

  if (autoApprove && magic_token) {
    sendMagicLink(email, magic_token).catch((err) =>
      console.error('Magic link email failed:', err)
    )
  } else {
    sendAdminAlert({ email, newsletter_picks: newsletters, other_text }).catch((err) =>
      console.error('Admin alert email failed:', err)
    )
  }

  return NextResponse.json({
    status,
    email,
    newsletter_count: newsletters.length + (hasOther ? 1 : 0),
  })
}
