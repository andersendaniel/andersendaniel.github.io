#!/usr/bin/env python3
"""Fetch European fintech/banking RSS feeds and generate articles.json for SB1 Pulse."""

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

FEEDS = [
    {"url": "https://www.finextra.com/rss/headlines.aspx",        "name": "Finextra"},
    {"url": "https://www.bankingtech.com/feed/",                  "name": "Banking Technology"},
    {"url": "https://www.fintechfutures.com/feed/",               "name": "Fintech Futures"},
    {"url": "https://techcrunch.com/tag/fintech/feed/",           "name": "TechCrunch Fintech"},
    {"url": "https://www.pymnts.com/feed/",                       "name": "PYMNTS"},
    {"url": "https://nordicfintech.io/feed/",                     "name": "Nordic Fintech"},
    {"url": "https://sifted.eu/feed/",                            "name": "Sifted"},
    {"url": "https://thepaypers.com/rss/",                        "name": "The Paypers"},
    {"url": "https://www.computerweekly.com/rss/IT-industry.xml", "name": "Computer Weekly"},
    {"url": "https://feeds.feedburner.com/LeMondeInformatique",   "name": "Finance Forward"},
    {"url": "https://www.euromoney.com/rss.xml",                  "name": "Euromoney"},
]

HIGH_KW = [
    "sparebank", "vipps", "bankid", "nordic bank", "norwegian bank",
    "open banking", "psd2", "psd3", "dora", "instant payment", "sepa instant",
    "core banking", "cloud banking", "ai in banking", "generative ai bank",
    "digital banking", "mobile banking", "embedded finance", "buy now pay later",
    "fraud detection", "anti money laundering", "aml", "kyc",
    "banking as a service", "baas", "open finance",
]

MEDIUM_KW = [
    "cloud", "aws", "azure", "google cloud", "microservices",
    "fintech", "neobank", "challenger bank", "payments", "paytech",
    "artificial intelligence", "machine learning", "large language model", "llm",
    "cybersecurity", "data breach", "ransomware", "zero trust",
    "gdpr", "regulation", "compliance", "eba", "ecb", "financial stability",
    "account aggregation", "data sharing", "blockchain", "stablecoin", "cbdc",
    "norway", "norwegian", "nordic", "scandinavian",
]

LOW_KW = [
    "bank", "finance", "financial", "digital", "innovation", "technology",
    "data", "security", "risk", "customer", "european", "payment", "mobile",
    "investment", "insurance", "insurtech", "wealthtech",
]

TAGS_CONFIG = [
    {"filter": "ai",           "kw": ["artificial intelligence", "machine learning", "llm", "gpt", "generative ai", "chatbot", "neural", "deep learning", "mlops", "ai model", "foundation model", "copilot", "large language"]},
    {"filter": "cloud",        "kw": ["cloud", "aws", "azure", "google cloud", "saas", "paas", "kubernetes", "microservice", "serverless", "devops", "infrastructure"]},
    {"filter": "payments",     "kw": ["payment", "vipps", "sepa", "wallet", "card", "pos", "checkout", "instant pay", "buy now pay later", "bnpl", "remittance", "swift", "paytech"]},
    {"filter": "security",     "kw": ["security", "cyber", "fraud", "breach", "hack", "phishing", "ransomware", "authentication", "zero trust", "bankid", "biometric", "dora", "identity theft"]},
    {"filter": "regulation",   "kw": ["regulation", "gdpr", "psd2", "psd3", "compliance", "eba", "ecb", "fsb", "dora", "mifid", "basel", "regtech", "finanstilsynet", "directive", "legislation", "central bank"]},
    {"filter": "open-banking", "kw": ["open banking", "open finance", "account aggregation", "plaid", "tink", "data sharing", "consent", "api banking"]},
    {"filter": "nordic",       "kw": ["nordic", "norway", "norwegian", "scandinavian", "sweden", "denmark", "finland", "sparebank", "dnb", "vipps", "mobilepay", "swish"]},
    {"filter": "banking",      "kw": ["bank", "banking", "core banking", "retail bank", "commercial bank", "deposit", "loan", "mortgage", "credit", "neobank", "challenger bank"]},
]


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def strip_html(html: str) -> str:
    try:
        s = _HTMLStripper()
        s.feed(html or "")
        return s.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", "", html or "").strip()


def score(text: str) -> int:
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


def get_tags(text: str) -> list[str]:
    t = text.lower()
    return [rule["filter"] for rule in TAGS_CONFIG if any(kw in t for kw in rule["kw"])][:3]


def parse_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def fetch_feed(feed):
    print(f"  {feed['name']}...", end=" ", flush=True)
    try:
        parsed = feedparser.parse(
            feed["url"],
            request_headers={"User-Agent": "SB1Pulse/1.0 (+https://andersendaniel.github.io)"},
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        articles = []

        for entry in parsed.entries[:30]:
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

            search = (title + " " + summary).lower()
            relevance = score(search)
            if relevance < 3:
                continue

            articles.append({
                "title": title,
                "summary": summary,
                "url": link,
                "date": date_str or "",
                "source": feed["name"],
                "relevance": relevance,
                "tags": get_tags(search),
            })

        print(f"{len(articles)} articles")
        return articles

    except Exception as e:
        print(f"error — {e}")
        return []


def main():
    out = Path(__file__).parent / "articles.json"
    print("SB1 Pulse — fetching news\n")

    all_articles = []
    for feed in FEEDS:
        all_articles.extend(fetch_feed(feed))

    # Deduplicate by title
    seen = set()
    deduped = []
    for a in all_articles:
        key = a["title"].lower()[:70]
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    # Sort: relevance desc, then date desc
    deduped.sort(key=lambda a: (
        -a["relevance"],
        -(datetime.fromisoformat(a["date"]).timestamp() if a["date"] else 0),
    ))

    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "sources": len(FEEDS),
        "articles": deduped,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✓ {len(deduped)} articles written to {out}")


if __name__ == "__main__":
    main()
