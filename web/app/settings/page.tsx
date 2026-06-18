import { redirect } from 'next/navigation'
import { getSessionUser } from '@/lib/session'
import { createServiceClient } from '@/lib/supabase'
import SettingsClient from './SettingsClient'

const ALL_SOURCES = [
  { id: 'tldr_ai',        label: 'TLDR AI',       domain: 'tldr.tech/ai' },
  { id: 'tldr_tech',      label: 'TLDR Tech',      domain: 'tldr.tech' },
  { id: 'tldr_dev',       label: 'TLDR Dev',       domain: 'tldr.tech/dev' },
  { id: 'techcrunch',     label: 'TechCrunch',     domain: 'techcrunch.com' },
  { id: 'ettech',         label: 'ETtech',         domain: 'economictimes.com' },
  { id: 'harper_carroll', label: 'Harper Carroll', domain: 'harpercarroll.com' },
  { id: 'et_ai',          label: 'ET AI',          domain: 'economictimes.com/ai' },
]

export default async function SettingsPage() {
  const user = await getSessionUser()
  if (!user) redirect('/')

  const db = createServiceClient()
  const { data: userSources } = await db
    .from('user_sources')
    .select('source_id, enabled')
    .eq('user_id', user.id)

  const enabledSet = new Set((userSources ?? []).filter((s: { enabled: boolean }) => s.enabled).map((s: { source_id: string }) => s.source_id))

  const sources = ALL_SOURCES.map((s) => ({ ...s, checked: enabledSet.has(s.id) }))

  return <SettingsClient user={user} sources={sources} />
}
