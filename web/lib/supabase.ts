import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

// Client-side (uses anon key, respects RLS)
export const supabase = createClient(supabaseUrl, supabaseAnonKey)

// Server-side (uses service role key, bypasses RLS — never expose to client)
export function createServiceClient() {
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? supabaseAnonKey
  return createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false },
  })
}

export type WaitlistStatus = 'pending' | 'approved' | 'activated' | 'rejected'

export interface WaitlistSignup {
  id: string
  email: string
  newsletter_picks: string[]
  other_text: string
  status: WaitlistStatus
  magic_token: string | null
  magic_token_expires_at: string | null
  created_at: string
}
