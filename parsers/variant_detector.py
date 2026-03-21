"""
Variant detection functions for newsletter senders that share email addresses.
All detection is based on from_display_name or subject — NOT body content.
"""


def detect_tldr_variant(from_display_name: str) -> str | None:
    """
    Detect which TLDR newsletter variant this email is.
    All TLDR newsletters come from dan@tldrnewsletter.com.
    Confirmed from real email headers: "TLDR AI <dan@tldrnewsletter.com>"

    Returns source ID string or None (None = skip this email).
    Order matters: check specific variants before generic "TLDR".
    """
    name = from_display_name.upper()
    if "TLDR AI" in name:
        return "tldr_ai"
    if "TLDR DEV" in name:
        return "tldr_dev"
    if "TLDR CRYPTO" in name:
        return None  # skip
    if "TLDR FINTECH" in name:
        return None  # skip
    if "TLDR FOUNDERS" in name:
        return None  # skip
    if "TLDR" in name:
        return "tldr"  # plain "TLDR" display name = base TLDR newsletter
    return None


def detect_et_variant(from_display_name: str, subject: str) -> str | None:
    """
    Detect ET AI newsletter from newsletter@economictimesnews.com.
    Returns "et_ai" if this is the AI edition, None otherwise (skip).
    """
    if "ET AI" in from_display_name or subject.startswith("ET AI:"):
        return "et_ai"
    return None


def is_harper_carroll_news(subject: str) -> bool:
    """
    Filter Harper Carroll emails to news digests only, skip promotional emails.
    """
    news_keywords = ["what's new in ai", "this week's ai news", "ai news"]
    return any(kw in subject.lower() for kw in news_keywords)
