import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

export async function POST(_req: NextRequest) {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 })

  const db = createServiceClient()
  await Promise.all([
    db.from('gmail_credentials').delete().eq('user_id', userId),
    db.from('users').update({ active: false }).eq('id', userId),
  ])

  return NextResponse.json({ ok: true })
}
