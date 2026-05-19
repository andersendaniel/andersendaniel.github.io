#!/usr/bin/env python3
"""Fetch tech-vendor RSS feeds and generate articles.json for SB1 Pulse."""

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

try:
    import feedparser
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "feedparser", "-q"])
    import feedparser

# ---------------------------------------------------------------------------
# Feed definitions  (category drives sidebar grouping in the frontend)
# ---------------------------------------------------------------------------
FEEDS = [
    # Microsoft
    {"url": "https://azure.microsoft.com/en-us/blog/feed/",              "name": "Azure Blog",        "category": "microsoft", "limit": 15},
    {"url": "https://blogs.microsoft.com/ai/feed/",                      "name": "Microsoft AI",      "category": "microsoft", "limit": 15},
    {"url": "https://www.microsoft.com/en-us/microsoft-365/blog/feed/",  "name": "Microsoft 365",     "category": "microsoft", "limit": 10},
    # Amazon / AWS
    {"url": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",   "name": "AWS What's New",    "category": "aws",       "limit": 15},
    {"url": "https://aws.amazon.com/blogs/aws/feed/",                    "name": "AWS Blog",          "category": "aws",       "limit": 15},
    # Google
    {"url": "https://blog.google/technology/ai/rss/",                    "name": "Google AI",         "category": "google",    "limit": 20},
    {"url": "https://blog.google/products/google-cloud/rss/",            "name": "Google Cloud",      "category": "google",    "limit": 20},
    {"url": "https://cloudblog.withgoogle.com/products/gcp/rss/",        "name": "Google Cloud Blog", "category": "google",    "limit": 20},
    {"url": "https://security.googleblog.com/feeds/posts/default?alt=rss","name": "Google Security",  "category": "google",    "limit": 15},
    {"url": "https://deepmind.google/blog/rss.xml",                      "name": "Google DeepMind",   "category": "google",    "limit": 50},
    # OpenAI
    {"url": "https://openai.com/blog/rss.xml",                           "name": "OpenAI Blog",       "category": "openai",    "limit": 15},
    # Anthropic
    {"url": "https://www.anthropic.com/news/rss",                        "name": "Anthropic News",    "category": "anthropic", "limit": 15},
    # ServiceNow
    {"url": "https://www.servicenow.com/company/media/press-room/rss.xml", "name": "ServiceNow News", "category": "servicenow","limit": 10},
    # Salesforce
    {"url": "https://www.salesforce.com/blog/feed/",                     "name": "Salesforce Blog",   "category": "salesforce","limit": 15},
    # SAP
    {"url": "https://news.sap.com/feed/",                                "name": "SAP News",          "category": "sap",       "limit": 15},
    # Meta
    {"url": "https://engineering.fb.com/feed/",                          "name": "Meta Engineering",  "category": "meta",      "limit": 10},
    # IBM
    {"url": "https://research.ibm.com/blog/rss",                         "name": "IBM Research",      "category": "ibm",       "limit": 10},
    # NVIDIA
    {"url": "https://blogs.nvidia.com/feed/",                            "name": "NVIDIA Blog",       "category": "nvidia",    "limit": 15},
    # GitHub
    {"url": "https://github.blog/feed/",                                 "name": "GitHub Blog",       "category": "github",    "limit": 10},
    # Databricks
    {"url": "https://www.databricks.com/feed",                           "name": "Databricks Blog",   "category": "databricks","limit": 15},
    # Snowflake
    {"url": "https://www.snowflake.com/feed/",                           "name": "Snowflake Blog",    "category": "snowflake", "limit": 15},
]

# ---------------------------------------------------------------------------
# Relevance scoring  (tuned for banking/financial services sales context)
# ---------------------------------------------------------------------------
HIGH_KW = [
    # Direct banking/finance
    "bank", "banking", "financial services", "financial institution",
    "insurance", "wealth management", "asset management",
    "sparebank", "dnb", "nordic bank", "norwegian bank",
    # Banking AI/tech use cases
    "fraud detection", "anti money laundering", "aml", "kyc",
    "credit risk", "credit scoring", "loan origination", "mortgage",
    "payments", "open banking", "instant payment",
    # Regulatory
    "dora", "psd2", "psd3", "gdpr", "financial regulation", "fintech",
    "regulatory compliance", "financial compliance",
    # AI products (universally relevant to AI/cloud sales)
    "generative ai", "large language model", "llm", "foundation model",
    "agentic ai", "ai agent", "copilot", "gpt", "claude", "gemini",
    "bedrock", "watsonx", "vertex ai", "azure openai",
]

MEDIUM_KW = [
    "enterprise", "digital transformation", "cloud migration",
    "machine learning", "artificial intelligence", "deep learning",
    "cybersecurity", "zero trust", "identity", "data protection",
    "microservices", "kubernetes", "serverless", "devops",
    "analytics", "real-time", "data platform", "data lakehouse",
    "automation", "workflow", "low-code", "no-code",
    "saas", "paas", "cloud native", "hybrid cloud", "multicloud",
    "norway", "nordic", "scandinavian", "europe",
]

LOW_KW = [
    "cloud", "ai", "data", "security", "platform", "api",
    "integration", "developer", "open source", "innovation",
    "productivity", "collaboration", "model", "inference",
]

TAGS_CONFIG = [
    {"filter": "ai",         "kw": ["artificial intelligence", "machine learning", "llm", "gpt", "generative ai", "copilot", "agent", "agentic", "neural", "foundation model", "claude", "gemini", "bedrock", "watsonx", "deepmind", "chatbot", "nlp", "computer vision"]},
    {"filter": "cloud",      "kw": ["cloud", "aws", "azure", "google cloud", "kubernetes", "serverless", "infrastructure", "multicloud", "hybrid cloud", "data center", "paas", "iaas", "saas"]},
    {"filter": "security",   "kw": ["security", "cyber", "fraud", "breach", "zero trust", "identity", "authentication", "compliance", "dora", "ransomware", "threat", "vulnerability", "aml", "kyc"]},
    {"filter": "data",       "kw": ["data", "analytics", "database", "warehouse", "lakehouse", "fabric", "bi", "reporting", "pipeline", "etl", "real-time data", "streaming"]},
    {"filter": "banking",    "kw": ["bank", "banking", "financial services", "payments", "lending", "credit", "mortgage", "wealth", "insurance", "fintech", "fraud detection", "open banking"]},
    {"filter": "automation", "kw": ["automation", "workflow", "process", "rpa", "low-code", "no-code", "power automate", "integration", "api", "agentic", "servicenow", "salesforce flow"]},
    {"filter": "developer",  "kw": ["developer", "github", "devops", "copilot", "coding", "api", "sdk", "open source", "ci/cd", "devsecops", "platform engineering", "innersource"]},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def strip_html(html):
    try:
        s = _Stripper()
        s.feed(html or "")
        return s.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", "", html or "").strip()


def score(text):
    t = text.lower()
    s = 0
    for kw in HIGH_KW:
        if kw in t:
            s += 12
    for kw in MEDIUM_KW:
        if kw in t:
            s += 4
    for kw in LOW_KW:
        if kw in t:
            s += 1
    return min(s, 100)


def get_tags(text):
    t = text.lower()
    tags = []
    for rule in TAGS_CONFIG:
        hits = sum(1 for kw in rule["kw"] if kw in t)
        if hits >= 2:
            tags.append(rule["filter"])
    return tags[:3]


def parse_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def extract_image(entry):
    for attr in ("media_content", "media_thumbnail"):
        items = getattr(entry, attr, None)
        if items and isinstance(items, list):
            url = items[0].get("url", "")
            if url and url.startswith("http"):
                return url
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_feed(feed):
    print(f"  {feed['name']}...", end=" ", flush=True)
    try:
        parsed = feedparser.parse(
            feed["url"],
            request_headers={"User-Agent": "Mozilla/5.0 (compatible; SB1Pulse/1.0; +https://andersendaniel.github.io)"},
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        limit = feed.get("limit", 15)
        articles = []

        for entry in parsed.entries[:limit]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not title or not link:
                continue

            date_str = parse_date(entry)
            if date_str:
                try:
                    if datetime.fromisoformat(date_str) < cutoff:
                        continue
                except Exception:
                    pass

            raw = (
                entry.get("summary")
                or entry.get("description")
                or (entry.get("content") or [{}])[0].get("value", "")
            )
            summary = strip_html(raw)[:400]
            image = extract_image(entry)

            search = (title + " " + summary + " " + feed["name"]).lower()
            relevance = score(search)
            if relevance < 1:
                continue

            articles.append({
                "title": title,
                "summary": summary,
                "url": link,
                "date": date_str or "",
                "source": feed["name"],
                "category": feed["category"],
                "relevance": relevance,
                "tags": get_tags(search),
                "image": image,
            })

        print(f"{len(articles)} articles")
        return articles

    except Exception as e:
        print(f"error — {e}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    out = Path(__file__).parent / "articles.json"
    print("SB1 Pulse — fetching vendor news\n")

    all_articles = []
    for feed in FEEDS:
        all_articles.extend(fetch_feed(feed))

    # Deduplicate by URL (vendor blogs reuse title patterns)
    seen = set()
    deduped = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            deduped.append(a)

    # Sort: newest first
    def sort_key(a):
        if a["date"]:
            try:
                return datetime.fromisoformat(a["date"]).timestamp()
            except Exception:
                pass
        return 0

    deduped.sort(key=sort_key, reverse=True)

    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "sources": len(FEEDS),
        "articles": deduped,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✓ {len(deduped)} articles written to {out}")


if __name__ == "__main__":
    main()
