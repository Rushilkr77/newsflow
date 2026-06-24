import { NextRequest, NextResponse } from 'next/server'
import { google } from 'googleapis'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

function getOAuthClient() {
  return new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    `${process.env.NEXT_PUBLIC_BASE_URL}/api/auth/google/callback`
  )
}

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get('code')
  const error = req.nextUrl.searchParams.get('error')
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000'

  if (error || !code) {
    return NextResponse.redirect(`${baseUrl}/setup/gmail?error=declined`)
  }

  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return NextResponse.redirect(`${baseUrl}/`)

  const oauth2Client = getOAuthClient()
  let tokens
  try {
    const result = await oauth2Client.getToken(code)
    tokens = result.tokens
  } catch {
    return NextResponse.redirect(`${baseUrl}/setup/gmail?error=token_exchange`)
  }

  if (!tokens.refresh_token) {
    return NextResponse.redirect(`${baseUrl}/setup/gmail?error=no_refresh_token`)
  }

  // Verify gmail.readonly was actually granted (user may have unchecked it on consent screen)
  const grantedScopes = (tokens.scope ?? '').split(' ')
  if (!grantedScopes.includes('https://www.googleapis.com/auth/gmail.readonly')) {
    return NextResponse.redirect(`${baseUrl}/setup/gmail?error=gmail_scope_missing`)
  }

  // Verify the authed Google account matches the signup email
  oauth2Client.setCredentials(tokens)
  const oauth2 = google.oauth2({ version: 'v2', auth: oauth2Client })
  const { data: profile } = await oauth2.userinfo.get()

  const db = createServiceClient()
  const { data: user } = await db
    .from('users')
    .select('email')
    .eq('id', userId)
    .single()

  if (!user) return NextResponse.redirect(`${baseUrl}/`)

  if (profile.email !== user.email) {
    return NextResponse.redirect(
      `${baseUrl}/setup/gmail?error=wrong_account&authed=${encodeURIComponent(profile.email ?? '')}`
    )
  }

  // Store encrypted refresh token (encrypt in production — storing plaintext for v0 dev)
  await db.from('gmail_credentials').upsert({
    user_id: userId,
    refresh_token_encrypted: tokens.refresh_token,
    updated_at: new Date().toISOString(),
  })

  // Mark user active
  await db.from('users').update({ active: true }).eq('id', userId)

  // First-time connect → set up sources; reconnect → go straight to dashboard
  const { data: existingSources } = await db
    .from('user_sources')
    .select('id')
    .eq('user_id', userId)
    .limit(1)

  const dest = existingSources && existingSources.length > 0 ? '/dashboard' : '/setup/sources'
  return NextResponse.redirect(`${baseUrl}${dest}`)
}
