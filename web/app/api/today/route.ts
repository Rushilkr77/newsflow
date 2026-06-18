import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServiceClient } from '@/lib/supabase'

export async function GET(_req: NextRequest) {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 })

  const today = new Date().toISOString().split('T')[0]
  const db = createServiceClient()

  const { data: episode } = await db
    .from('episodes')
    .select('id, date, mp3_url, script_path, status')
    .eq('user_id', userId)
    .eq('date', today)
    .maybeSingle()

  // Also grab yesterday as fallback
  const yesterday = new Date(Date.now() - 864e5).toISOString().split('T')[0]
  const { data: prevEpisode } = await db
    .from('episodes')
    .select('id, date, mp3_url, status')
    .eq('user_id', userId)
    .eq('date', yesterday)
    .maybeSingle()

  const { data: sources } = await db
    .from('user_sources')
    .select('source_id')
    .eq('user_id', userId)
    .eq('enabled', true)

  return NextResponse.json({
    today,
    episode: episode ?? null,
    previous_episode: prevEpisode ?? null,
    sources: (sources ?? []).map((s) => s.source_id),
  })
}
