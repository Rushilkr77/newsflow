import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

const BASE = () => process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000'

function errorRedirect(msg: string) {
  return NextResponse.redirect(`${BASE()}/activate/error?msg=${encodeURIComponent(msg)}`)
}

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('token')
  if (!token) return errorRedirect('No activation token provided.')

  const db = createServiceClient()

  const { data: signup } = await db
    .from('waitlist_signups')
    .select('id, email, status, magic_token_expires_at')
    .eq('magic_token', token)
    .maybeSingle()

  if (!signup) {
    return errorRedirect(
      'This link has expired or already been used. If you still need access, reply to the email and we\'ll send a new one.'
    )
  }

  if (signup.status === 'activated') {
    return errorRedirect('This link has already been used.')
  }

  if (new Date(signup.magic_token_expires_at) < new Date()) {
    return errorRedirect('This link has expired. Reply to the original email and we\'ll send a new one.')
  }

  // Create user row if not exists
  let userId: string
  const { data: existing } = await db
    .from('users')
    .select('id')
    .eq('email', signup.email)
    .maybeSingle()

  if (existing) {
    userId = existing.id
  } else {
    const { data: newUser, error } = await db
      .from('users')
      .insert({ email: signup.email })
      .select('id')
      .single()

    if (error || !newUser) {
      return errorRedirect('Something went wrong creating your account. Reply to the email and we\'ll sort it out.')
    }
    userId = newUser.id
  }

  // Mark signup activated
  await db.from('waitlist_signups').update({ status: 'activated' }).eq('id', signup.id)

  // Set session cookie
  const cookieStore = cookies()
  cookieStore.set('nf_session', userId, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 30,
    path: '/',
  })

  return NextResponse.redirect(`${BASE()}/setup/gmail`)
}
