import type { Metadata } from 'next'
import { newsreader, jetbrainsMono } from '@/lib/fonts'
import './globals.css'

export const metadata: Metadata = {
  title: 'NewsFlow — Daily audio briefings from your newsletters',
  description:
    "A daily audio briefing from the newsletters you don't read. We pull what matters and send you a 30-minute episode every morning.",
  metadataBase: new URL('https://newsflow.ink'),
  openGraph: {
    title: 'NewsFlow — Daily audio briefings from your newsletters',
    description:
      "A daily audio briefing from the newsletters you don't read. Pulls your newsletters every morning, filters the noise, and sends you a 30-45 minute episode before you're awake.",
    url: 'https://newsflow.ink',
    siteName: 'NewsFlow',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'NewsFlow — Daily audio briefings from your newsletters',
    description: "A daily audio briefing from the newsletters you don't read.",
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${jetbrainsMono.variable}`}
    >
      <body>{children}</body>
    </html>
  )
}
