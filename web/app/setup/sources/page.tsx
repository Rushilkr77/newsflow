import { redirect } from 'next/navigation'
import { getSessionUser } from '@/lib/session'
import { createServiceClient } from '@/lib/supabase'
import { ALL_SOURCES } from '@/lib/sources'
import SourcesForm from './SourcesForm'

export default async function SetupSourcesPage() {
  const user = await getSessionUser()
  if (!user) redirect('/')

  const db = createServiceClient()

  // Load which sources user picked at signup
  const { data: signup } = await db
    .from('waitlist_signups')
    .select('newsletter_picks')
    .eq('email', user.email)
    .maybeSingle()

  const signupPicks: string[] = signup?.newsletter_picks ?? []

  // Load existing user_sources (if returning to this page)
  const { data: existingSources } = await db
    .from('user_sources')
    .select('source_id, enabled, lookback_days')
    .eq('user_id', user.id)

  const enabledMap: Record<string, boolean> = {}
  for (const s of existingSources ?? []) {
    enabledMap[s.source_id] = s.enabled
  }

  // Pre-select sources from signup if no existing user_sources
  const isFirstTime = !existingSources || existingSources.length === 0
  const sources = ALL_SOURCES.filter((s) => signupPicks.includes(s.id))

  // If signup had no picks (edge case), show all supported
  const displaySources = sources.length > 0 ? sources : ALL_SOURCES

  const initialEnabled = displaySources.map((s) => ({
    ...s,
    checked: isFirstTime ? true : (enabledMap[s.id] ?? false),
  }))

  return (
    <SourcesForm
      userId={user.id}
      email={user.email}
      sources={initialEnabled}
      initialBio={user.bio}
      initialDeliveryTime={user.delivery_local_time}
      initialTz={user.tz}
      isFirstTime={isFirstTime}
    />
  )
}
