import AudioPlayer from '@/components/AudioPlayer'
import WaitlistForm from '@/components/WaitlistForm'

function getDateline(): string {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

const EXCERPT_ARTICLES = [
  {
    section: 'Headlines',
    source: 'TLDR AI · tldr.tech/ai',
    hed: 'OpenAI and Microsoft extend compute deal through 2030',
    body: "OpenAI and Microsoft signed a five-year extension this week, committing Azure as the primary training cloud through 2030. The quiet detail: the contract shifts from cost-sharing to dedicated capacity — OpenAI pays a fixed rate regardless of utilization. For product people, the strategic read is clear: compute constraints are now a fixed cost, not a variable one, which changes how OpenAI can price experimentation.",
  },
  {
    section: 'AI Updates',
    source: 'TLDR AI · tldr.tech/ai',
    hed: "Anthropic updated Claude's tool-use to support longer reasoning chains",
    body: "Anthropic shipped an update allowing Claude to reason for more steps before calling external tools. Agentic workflows that previously required explicit chain-of-thought prompting now self-organize their reasoning steps. The evaluation challenge this creates is harder than the feature itself: knowing when to stop reasoning and just act is a different problem than reasoning correctly.",
  },
  {
    section: 'Funding',
    source: 'TechCrunch · techcrunch.com',
    hed: 'Poolside raises $500M at $3B to build AI for enterprise dev teams',
    body: "Poolside closed a $500 million round targeting large software organizations. The pitch is not a copilot but a full-lifecycle tool: requirements through deployment. The interesting bet is that enterprises want a closed, auditable system rather than a public model with access to their codebase — a positioning that trades breadth for trust.",
  },
]

export default function LandingPage() {
  const dateline = getDateline()

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0">

        {/* ── HEADER ──────────────────────────────────────────────── */}
        <header className="pt-8 pb-0 md:pt-12">
          <div className="flex flex-col gap-1.5 md:flex-row md:items-baseline md:justify-between md:gap-0 reveal delay-0">
            <span className="masthead-text">Newsflow</span>
            <span className="font-mono text-2xs text-ink-muted tracking-wide">
              {dateline}.
            </span>
          </div>
        </header>

        {/* ── HERO ────────────────────────────────────────────────── */}
        <section className="mt-10 md:mt-14" aria-label="Introduction">

          {/* Short red accent bar — newspaper section rule */}
          <div className="w-8 h-0.5 bg-accent mb-5 reveal delay-0" />

          {/* Lede */}
          <h1
            className={[
              'font-serif italic text-ink reveal delay-75',
              'text-[2.125rem] leading-[1.13] max-w-[18ch]',
              'md:text-[3.875rem] md:leading-[1.08] md:max-w-[17ch]',
            ].join(' ')}
          >
            A daily audio briefing from the newsletters you don't read.
          </h1>

          {/* Value prop */}
          <p
            className={[
              'font-serif text-ink-muted leading-relaxed reveal delay-150',
              'mt-5 text-sm max-w-prose',
              'md:mt-8 md:text-md md:leading-[1.7]',
            ].join(' ')}
          >
            We pull the issues sitting in your inbox, surface what matters in your
            line of work, and send you a 30-minute episode every morning. You listen
            on the commute or at the gym.
          </p>

          {/* Audio player — snippet card */}
          <div className="mt-7 md:mt-9 reveal delay-250 max-w-prose">

            {/* Label row: badge + clip duration + date */}
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-3">
                <span className="excerpt-badge">Snippet</span>
                <span className="font-mono text-[0.5625rem] text-ink-faint tracking-[0.1em] uppercase">
                  2:00 of 37:35
                </span>
              </div>
              <span className="mono-caps">Jun 8, 2026</span>
            </div>

            {/* Player */}
            <div className="bg-surface px-4 py-4 md:px-5">
              <AudioPlayer title="What a full episode sounds like" src="/sample.mp3" />
            </div>

            {/* Full episode context */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
              <span className="mono-caps text-ink-faint">Full episode:</span>
              <span className="mono-caps">37 min</span>
              <span className="font-mono text-[0.5rem] text-ink-faint leading-none">·</span>
              <span className="mono-caps">22 articles</span>
              <span className="font-mono text-[0.5rem] text-ink-faint leading-none">·</span>
              <span className="mono-caps">6 sources</span>
            </div>
          </div>
        </section>

        {/* ── DIVIDER ─────────────────────────────────────────────── */}
        <hr className="rule mt-12 md:mt-16 reveal delay-350" />

        {/* ── SCRIPT EXCERPT ──────────────────────────────────────── */}
        <section className="mt-8 md:mt-12 reveal delay-450" aria-label="Sample episode excerpt">

          {/* Section header: SAMPLE EPISODE ——— JUNE 9, 2026 */}
          <div className="flex items-center gap-4 mb-7 max-w-prose">
            <span className="font-mono text-[0.5625rem] text-ink-muted tracking-[0.14em] uppercase shrink-0">
              Sample episode
            </span>
            <div className="flex-1 h-px bg-rule" />
            <span className="font-mono text-[0.5625rem] text-ink-faint tracking-[0.12em] uppercase shrink-0">
              Jun 8, 2026
            </span>
          </div>

          {/* Article cards */}
          <div className="max-w-prose space-y-3 md:space-y-4">
            {EXCERPT_ARTICLES.map((article, i) => (
              <div key={i} className="excerpt-card">
                <div className="flex items-center justify-between mb-3">
                  <span className="excerpt-badge">{article.section}</span>
                  <span className="font-mono text-[0.5625rem] tracking-[0.1em] text-ink-faint">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </div>
                <p className="excerpt-source-attr mb-2.5">{article.source}</p>
                <h2 className="excerpt-article-hed">{article.hed}</h2>
                <p className="excerpt-body mt-3">{article.body}</p>
              </div>
            ))}
          </div>

          <p className="mt-8 font-serif italic text-sm text-ink-muted">
            This is what the June 8 edition sounded like. Yours will cover your newsletters.
          </p>
        </section>

        {/* ── DIVIDER ─────────────────────────────────────────────── */}
        <hr className="rule mt-12 md:mt-16 reveal delay-550" />

        {/* ── WAITLIST FORM ───────────────────────────────────────── */}
        <section
          className="mt-12 md:mt-16 pb-20 md:pb-32 reveal delay-650"
          aria-label="Request early access"
        >
          <WaitlistForm />
        </section>

      </div>
    </main>
  )
}
