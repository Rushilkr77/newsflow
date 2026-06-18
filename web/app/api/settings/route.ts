import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 })

  let body: { bio?: string; delivery_time?: string; tz?: string }
  try { body = await req.json() } catch {
    return NextResponse.json({ error: 'Invalid body.' }, { status: 400 })
  }

  const { bio = '', delivery_time = '07:00', tz = 'Asia/Kolkata' } = body
  const db = createServiceClient()
  await db.from('users').update({ bio, delivery_local_time: delivery_time, tz }).eq('id', userId)

  return NextResponse.json({ ok: true })
}
