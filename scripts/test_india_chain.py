"""
Manual end-to-end test for the India fallback scraper chain.
Run this from your Mac to verify DDG search + scraping works for ET article titles.

Usage:
    cd /path/to/newsflow
    source venv/bin/activate
    python scripts/test_india_chain.py

Optional — also test summarization (needs ANTHROPIC_API_KEY in .env):
    python scripts/test_india_chain.py --summarize
"""
import argparse
import sys
import textwrap
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scraper.inc42_scraper import Inc42Scraper

INDIA_SCRAPERS = [
    Inc42Scraper("inc42.com",     ("/features/", "/news/", "/buzz/", "/startups/")),
    Inc42Scraper("yourstory.com", ("/stories/", "/startup/", "/tech/", "/companies/",
                                   "/2024/", "/2025/", "/2026/")),
    Inc42Scraper("entrackr.com",  ("/story/", "/news/")),
]

# Today's failing ET article titles from the 2026-05-12 run
TEST_ARTICLES = [
    ("P0", "ettech", "Jio IPO set to be fully fresh funding; no OFS"),
    ("P0", "ettech", "DailyObjects in talks to close Rs 300 crore funding round"),
    ("P1", "ettech", "Wingreens World snaps up Safe Harvest in all-stock deal"),
]


def run_fetch_test() -> dict[str, tuple[str | None, str | None]]:
    """Run the India scraper chain. Returns {title: (site, text)}."""
    results = {}
    print("\n" + "=" * 70)
    print("STEP 1 — India Scraper Chain (DDG site: search + trafilatura)")
    print("=" * 70)

    for priority, source, title in TEST_ARTICLES:
        print(f"\n[{priority}] ({source}) {title}")
        print("-" * 60)
        found_site = None
        found_text = None

        for scraper in INDIA_SCRAPERS:
            url = scraper._find_article_url(title)
            if url:
                text = scraper._scrape_url(url)
                chars = len(text) if text else 0
                if text and chars > 150:
                    print(f"  ✓ {scraper._site}")
                    print(f"    URL    : {url}")
                    print(f"    Chars  : {chars}")
                    preview = text[:500].replace("\n", " ")
                    print(f"    Preview: {textwrap.shorten(preview, 280)}")
                    found_site = scraper._site
                    found_text = text
                    break
                else:
                    print(f"  ⚠ {scraper._site}: found URL but content too short ({chars} chars)")
                    print(f"    URL: {url}")
            else:
                print(f"  ✗ {scraper._site}: no result")

        if not found_site:
            print("  → All India sites missed — would fall through to general DDG")
        results[title] = (found_site, found_text)

    return results


def run_summarize_test(fetch_results: dict[str, tuple[str | None, str | None]]) -> None:
    """Run a quick summarization preview using the pipeline's LLM client."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n[--summarize] Skipped: ANTHROPIC_API_KEY not set in .env")
        return

    from anthropic import Anthropic
    client = Anthropic()

    print("\n" + "=" * 70)
    print("STEP 2 — Summarization Preview (P0 format)")
    print("=" * 70)

    for priority, source, title in TEST_ARTICLES:
        site, text = fetch_results.get(title, (None, None))
        content = text or f"[SNIPPET ONLY — no full text fetched for: {title}]"

        print(f"\n[{priority}] {title}")
        print(f"  Content source: {site or 'snippet-only'} ({len(content)} chars)")

        prompt = (
            f"Summarize this India tech article for a podcast listener who is an SDE "
            f"transitioning to Product Manager. Keep it under 150 words. "
            f"Focus on: what happened, why it matters, one PM insight.\n\n"
            f"Title: {title}\n\nContent:\n{content[:3000]}"
        )

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = msg.content[0].text
            print(f"  Summary:\n")
            for line in textwrap.wrap(summary, 65):
                print(f"    {line}")
        except Exception as e:
            print(f"  Summarization failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test India fallback scraper chain")
    parser.add_argument("--summarize", action="store_true",
                        help="Also run a summarization preview (needs ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    fetch_results = run_fetch_test()

    fetched = sum(1 for s, _ in fetch_results.values() if s)
    print(f"\n{'=' * 70}")
    print(f"RESULT: {fetched}/{len(TEST_ARTICLES)} articles fetched by India chain")
    missed = [t for t, (s, _) in fetch_results.items() if not s]
    if missed:
        print("Missed (will fall to general DDG or snippet-only):")
        for t in missed:
            print(f"  - {t}")

    if args.summarize:
        run_summarize_test(fetch_results)


if __name__ == "__main__":
    main()
