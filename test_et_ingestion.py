"""
Quick smoke test: run ingestion for ET sources only and print results.
Usage:
    python test_et_ingestion.py              # uses today's date
    python test_et_ingestion.py 2026-03-19   # use specific date
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import structlog
structlog.configure(processors=[structlog.dev.ConsoleRenderer()])

from agents.ingestion import IngestionAgent

date = sys.argv[1] if len(sys.argv) > 1 else None

print(f"\n=== ET Ingestion Test | date={date or 'today (wall clock)'} ===\n")

agent = IngestionAgent()
articles = agent.run(date=date)

et_articles = [a for a in articles if a.source in ("et_ai", "ettech")]
all_by_source = {}
for a in articles:
    all_by_source.setdefault(a.source, []).append(a)

print("All sources fetched:")
for src, arts in sorted(all_by_source.items()):
    print(f"  {src}: {len(arts)} articles")

print(f"\nET sources ({len(et_articles)} total):")
for a in et_articles:
    print(f"\n  [{a.source}] {a.title}")
    print(f"    URL:     {a.url}")
    print(f"    Snippet: {(a.snippet or '')[:100]}")

if not et_articles:
    print("  *** 0 ET articles — check sender emails + lookback cutoff ***")
