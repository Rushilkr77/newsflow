import { cookies } from 'next/headers'
import { createServiceClient } from './supabase'

export interface SessionUser {
  id: string
  email: string
  bio: string
  delivery_local_time: string
  tz: string
  active: boolean
  episode_generation_enabled: boolean
}

export async function getSessionUser(): Promise<SessionUser | null> {
  const cookieStore = cookies()
  const userId = cookieStore.get('nf_session')?.value
  if (!userId) return null

  const db = createServiceClient()
  const { data } = await db
    .from('users')
    .select('id, email, bio, delivery_local_time, tz, active, episode_generation_enabled')
    .eq('id', userId)
    .maybeSingle()

  return data ?? null
}
