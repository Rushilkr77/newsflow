export interface Episode {
  id: string
  date: string
  mp3_url: string | null
  script_path: string | null
  status: string
}

export const STATUS_LABELS: Record<string, string> = {
  queued:      'Queued for assembly.',
  generating:  'Being assembled now.',
  ready:       'Ready.',
  failed:      "Didn't print today.",
  empty_inbox: 'No issues arrived overnight.',
}
