from enum import Enum


class Source(str, Enum):
    TLDR_AI = "tldr_ai"
    TLDR_TECH = "tldr_tech"
    TLDR_DEV = "tldr_dev"
    TECHCRUNCH = "techcrunch"
    HARPER_CARROLL = "harper_carroll"
    ETTECH = "ettech"
    ET_AI = "et_ai"
    CUSTOM = "custom"  # Generic fallback for user-defined senders via NEWSLETTER_SENDERS env var


class Priority(str, Enum):
    P0 = "P0"  # Must include — deep dive
    P1 = "P1"  # High priority — standard coverage
    P2 = "P2"  # If space — quick hit
    P3 = "P3"  # Skip


class Category(str, Enum):
    BIG_TECH_LAUNCHES   = "big_tech_launches"    # Major announcements from Meta/Apple/NVIDIA/Google/OpenAI/Anthropic/Microsoft
    AI_PRODUCTS_TOOLS   = "ai_products_tools"    # AI-powered products & tools (startups + big co)
    PRODUCT_INNOVATIONS = "product_innovations"  # Non-AI products that are a real leap (phones, hardware, platforms)
    INDIA_STARTUPS      = "india_startups"       # Indian startup ecosystem, founders, local deals & policy
    FUNDING_MA          = "funding_ma"           # Funding rounds, M&A, acquisitions, valuations
    INDUSTRY_STRATEGY   = "industry_strategy"    # SaaS disruption, go-to-market, Series B+ company moves
    ENGINEERING_TECH    = "engineering_tech"     # Technical deep dives, infra, open source → P2
    POLICY_SAFETY       = "policy_safety"        # Regulations, AI safety, government policy, compliance → P2
