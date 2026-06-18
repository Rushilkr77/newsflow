import { redirect } from 'next/navigation'
import { getSessionUser } from '@/lib/session'
import { createServiceClient } from '@/lib/supabase'
import TodayClient from './TodayClient'

export default async function TodayPage() {
  const user = await getSessionUser()
  if (!user) redirect('/')
  if (!user.active) redirect('/setup/gmail')

  const today = new Date().toISOString().split('T')[0]
  const yesterday = new Date(Date.now() - 864e5).toISOString().split('T')[0]

  const db = createServiceClient()

  const [{ data: episode }, { data: prevEpisode }, { data: sources }] = await Promise.all([
    db.from('episodes').select('*').eq('user_id', user.id).eq('date', today).maybeSingle(),
    db.from('episodes').select('*').eq('user_id', user.id).eq('date', yesterday).maybeSingle(),
    db.from('user_sources').select('source_id').eq('user_id', user.id).eq('enabled', true),
  ])

  const sourceIds = (sources ?? []).map((s: { source_id: string }) => s.source_id)

  const dateline = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  return (
    <TodayClient
      user={user}
      dateline={dateline}
      today={today}
      episode={episode}
      prevEpisode={prevEpisode}
      sources={sourceIds}
    />
  )
}
