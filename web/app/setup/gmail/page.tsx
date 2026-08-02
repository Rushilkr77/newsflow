// Gmail OAuth connect step removed — NewsFlow no longer accesses user inboxes.
// All newsletter ingestion runs from a single shared NewsFlow inbox.
// This page now redirects to setup/sources.
import { redirect } from 'next/navigation'

export default function SetupGmailPage() {
  redirect('/setup/sources')
}
