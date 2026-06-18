interface Props {
  searchParams: { msg?: string }
}

export default function ActivateErrorPage({ searchParams }: Props) {
  const message = searchParams.msg ?? 'This link is no longer valid.'

  return (
    <main className="min-h-screen bg-paper text-ink flex items-start">
      <div className="w-full max-w-content mx-auto px-5 xs:px-6 md:px-8 xl:px-0 pt-16 md:pt-24">
        <span className="masthead-text">Newsflow</span>
        <div className="mt-12 max-w-prose">
          <div className="w-8 h-0.5 bg-accent mb-6" />
          <p className="font-serif text-ink text-lg leading-relaxed">{message}</p>
        </div>
      </div>
    </main>
  )
}
