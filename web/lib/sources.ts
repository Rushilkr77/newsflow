// Source catalog — must stay in sync with config/senders.yaml.
// source_ids here use the web convention (e.g. 'tldr_tech' for base TLDR);
// orchestrator/user_sources.py SOURCE_ID_ALIASES maps them to pipeline Source enum values.
export const ALL_SOURCES = [
  // TLDR family — all variants subscribed in the shared ingestion inbox
  { id: 'tldr_ai',      label: 'TLDR AI',         domain: 'tldr.tech/ai',      description: 'Daily AI research & product news' },
  { id: 'tldr_tech',    label: 'TLDR Tech',        domain: 'tldr.tech',         description: 'Top tech stories of the day' },
  { id: 'tldr_dev',     label: 'TLDR Dev',         domain: 'tldr.tech/dev',     description: 'Software engineering & open source' },
  { id: 'tldr_devops',  label: 'TLDR DevOps',      domain: 'tldr.tech/devops',  description: 'Cloud, infra & DevOps' },
  { id: 'tldr_fintech', label: 'TLDR Fintech',     domain: 'tldr.tech/fintech', description: 'Finance & payments tech' },
  { id: 'tldr_crypto',  label: 'TLDR Crypto',      domain: 'tldr.tech/crypto',  description: 'Crypto & Web3' },
  // Other supported sources
  { id: 'techcrunch',     label: 'TechCrunch',     domain: 'techcrunch.com',              description: 'Tech news & startup coverage' },
  { id: 'ettech',         label: 'ETtech',         domain: 'economictimes.com',           description: 'Indian tech & business news' },
  { id: 'et_ai',          label: 'ET AI',          domain: 'economictimes.com/ai',        description: 'AI news from Economic Times' },
  { id: 'harper_carroll', label: 'Harper Carroll', domain: 'harpercarroll.com',           description: 'Weekly AI industry deep-dive' },
] as const

export type SourceId = (typeof ALL_SOURCES)[number]['id']
