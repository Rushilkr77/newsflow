import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { createServiceClient } from '@/lib/supabase'
import ConnectGmailClient from './ConnectGmailClient'

export default async function SetupGmailPage() {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value

  if (!userId) redirect('/')

  const db = createServiceClient()
  const { data: user } = await db
    .from('users')
    .select('email, active')
    .eq('id', userId)
    .maybeSingle()

  if (!user) redirect('/')
  if (user.active) redirect('/setup/sources')

  return <ConnectGmailClient email={user.email} />
}
