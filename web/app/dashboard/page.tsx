import { redirect } from 'next/navigation'
import { getSessionUser } from '@/lib/session'
import { createServiceClient } from '@/lib/supabase'
import { ALL_SOURCES } from '@/lib/sources'
import DashboardClient from '@/components/DashboardClient'

export default async function DashboardPage() {
  const user = await getSessionUser()
  if (!user) redirect('/')

  const db = createServiceClient()

  const [{ data: episodes }, { data: userSources }] = await Promise.all([
    db.from('episodes')
      .select('id, date, mp3_url, script_path, status')
      .eq('user_id', user.id)
      .order('date', { ascending: false })
      .limit(60),
    db.from('user_sources')
      .select('source_id, enabled')
      .eq('user_id', user.id),
  ])

  const enabledSet = new Set(
    (userSources ?? [])
      .filter((s: { enabled: boolean }) => s.enabled)
      .map((s: { source_id: string }) => s.source_id)
  )

  const sources = ALL_SOURCES.map((s) => ({ ...s, checked: enabledSet.has(s.id) }))

  return (
    <DashboardClient
      user={user}
      episodes={episodes ?? []}
      sources={sources}
    />
  )
}
