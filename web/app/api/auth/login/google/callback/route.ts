import { NextRequest, NextResponse } from 'next/server'
import { google } from 'googleapis'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

function getLoginOAuthClient() {
  return new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    `${process.env.NEXT_PUBLIC_BASE_URL}/api/auth/login/google/callback`
  )
}

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get('code')
  const error = req.nextUrl.searchParams.get('error')
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000'

  if (error || !code) {
    return NextResponse.redirect(`${baseUrl}/login?error=declined`)
  }

  const oauth2Client = getLoginOAuthClient()
  let tokens
  try {
    const result = await oauth2Client.getToken(code)
    tokens = result.tokens
  } catch {
    return NextResponse.redirect(`${baseUrl}/login?error=token_exchange`)
  }

  oauth2Client.setCredentials(tokens)
  const oauth2Api = google.oauth2({ version: 'v2', auth: oauth2Client })

  let email: string | null | undefined
  try {
    const { data: profile } = await oauth2Api.userinfo.get()
    email = profile.email
  } catch {
    return NextResponse.redirect(`${baseUrl}/login?error=profile_fetch`)
  }

  if (!email) {
    return NextResponse.redirect(`${baseUrl}/login?error=no_email`)
  }

  const db = createServiceClient()
  const { data: user } = await db
    .from('users')
    .select('id')
    .ilike('email', email)
    .maybeSingle()

  if (!user) {
    return NextResponse.redirect(`${baseUrl}/login?error=no_account`)
  }

  const cookieStore = cookies()
  cookieStore.set('nf_session', user.id, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 30,
    path: '/',
  })

  return NextResponse.redirect(`${baseUrl}/dashboard`)
}
