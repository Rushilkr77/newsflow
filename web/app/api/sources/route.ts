import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 })

  let body: { sources?: string[]; bio?: string; delivery_time?: string; tz?: string }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid body.' }, { status: 400 })
  }

  const { sources = [], bio = '', delivery_time = '07:00', tz = 'Asia/Kolkata' } = body

  if (sources.length === 0) {
    return NextResponse.json({ error: 'Select at least one source.' }, { status: 400 })
  }

  const db = createServiceClient()

  // Upsert user preferences
  await db.from('users').update({ bio, delivery_local_time: delivery_time, tz }).eq('id', userId)

  // Replace user_sources — delete all then insert enabled ones
  await db.from('user_sources').delete().eq('user_id', userId)
  await db.from('user_sources').insert(
    sources.map((source_id) => ({ user_id: userId, source_id, enabled: true, lookback_days: 7 }))
  )

  return NextResponse.json({ ok: true })
}
