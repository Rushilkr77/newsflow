export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0 pt-10 md:pt-16 pb-24">
        <span className="masthead-text">Newsflow</span>

        <div className="mt-12 md:mt-16 max-w-prose">
          <div className="w-8 h-0.5 bg-accent mb-6" />
          <h1 className="font-serif italic text-[1.75rem] md:text-[2.5rem] leading-[1.12]">Privacy</h1>

          <div className="mt-8 space-y-8 font-serif text-ink-muted leading-relaxed">

            <section>
              <h2 className="font-serif text-ink font-medium text-base mb-3">What we read</h2>
              <p>
                We access your Gmail inbox using Google's read-only OAuth scope
                (<span className="font-mono text-xs">gmail.readonly</span>). We only search for
                emails matching the newsletter senders you've configured — specific sender addresses
                like <span className="font-mono text-xs">dan@tldrnewsletter.com</span>. We never
                read unrelated messages, attachments, drafts, or sent mail.
              </p>
            </section>

            <section>
              <h2 className="font-serif text-ink font-medium text-base mb-3">What we store</h2>
              <p>
                We store: your email address, a bio you write yourself, your delivery preferences
                (time and timezone), the list of newsletters you've enabled, and the generated
                podcast scripts and MP3 files for each episode. We store a Gmail refresh token
                (encrypted at rest) so we can fetch your newsletters each morning without
                requiring you to re-authenticate daily.
              </p>
            </section>

            <section>
              <h2 className="font-serif text-ink font-medium text-base mb-3">What we don't store</h2>
              <p>
                We don't store the full content of your emails, your inbox metadata, your
                contacts, or any data from emails outside the configured sender list. We don't
                sell data. There are no third-party analytics or tracking pixels on this site.
              </p>
            </section>

            <section>
              <h2 className="font-serif text-ink font-medium text-base mb-3">Who has access</h2>
              <p>
                Only the NewsFlow service account (running on your host's Mac) can access your
                Gmail via the stored refresh token. No third party can access it. The encrypted
                token is stored in a Supabase database with row-level security enabled.
              </p>
            </section>

            <section>
              <h2 className="font-serif text-ink font-medium text-base mb-3">How to delete your data</h2>
              <p>
                Go to Settings → Disconnect to revoke Gmail access and stop episode generation.
                Your refresh token is deleted immediately. To delete your account and all
                associated data, reply to any episode email or contact{' '}
                <span className="font-mono text-xs">rushilmisc77@gmail.com</span>. Full deletion
                takes up to 30 days (MP3s stored on Google Drive are deleted from the shared
                folder; locally generated script files are purged from the workspace).
              </p>
            </section>

          </div>

          <div className="mt-12 pt-8 border-t border-rule">
            <p className="font-mono text-[0.5rem] text-ink-faint tracking-[0.08em] uppercase">
              Last updated: June 2026. Questions: rushilmisc77@gmail.com
            </p>
          </div>
        </div>
      </div>
    </main>
  )
}
