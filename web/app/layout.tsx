import type { Metadata } from 'next'
import { newsreader, jetbrainsMono } from '@/lib/fonts'
import './globals.css'

export const metadata: Metadata = {
  title: 'NewsFlow — Daily audio briefings from your newsletters',
  description:
    "A daily audio briefing from the newsletters you don't read. We pull what matters and send you a 30-minute episode every morning.",
  openGraph: {
    title: 'NewsFlow',
    description: "A daily audio briefing from the newsletters you don't read.",
    type: 'website',
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
