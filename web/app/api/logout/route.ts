import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'

export async function POST() {
  const cookieStore = cookies()
  cookieStore.set('nf_session', '', { maxAge: 0, path: '/' })
  return NextResponse.json({ ok: true })
}
