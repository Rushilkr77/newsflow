import { NextResponse } from 'next/server'
import { google } from 'googleapis'

function getLoginOAuthClient() {
  return new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    `${process.env.NEXT_PUBLIC_BASE_URL}/api/auth/login/google/callback`
  )
}

export async function GET() {
  const oauth2Client = getLoginOAuthClient()

  const url = oauth2Client.generateAuthUrl({
    access_type: 'online',
    prompt: 'select_account',
    scope: [
      'openid',
      'https://www.googleapis.com/auth/userinfo.email',
    ],
  })

  return NextResponse.redirect(url)
}
