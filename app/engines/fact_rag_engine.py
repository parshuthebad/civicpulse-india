import asyncio
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus
import httpx

from app.config import settings
from app.engines.cloud_providers import (
    query_google_factcheck,
    query_tavily_search,
    query_newsdata,
)

INDIAN_FACTCHECK_DOMAINS = (
    "pib.gov.in",
    "boomlive.in",
    "altnews.in",
    "factly.in",
    "newschecker.in",
    "vishvasnews.com",
    "thequint.com",
    "rbi.org.in",
)

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "will", "have", "has",
    "are", "was", "were", "been", "about", "into", "over", "after", "next",
    "month", "year", "said", "says", "announced", "india", "indian", "rupee",
}


def _clean_text(raw: str, max_len: int = 260) -> str:
    if not raw:
        return ""
    txt = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) <= max_len:
        return txt
    cut = txt[:max_len]
    last_dot = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if last_dot > 60:
        return cut[: last_dot + 1].strip()
    return cut.rsplit(" ", 1)[0].strip() + "..."


def _short_keywords(claim: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9\u0900-\u097F\u0C00-\u0C7F]+", claim)
    kept = [t for t in tokens if len(t) > 2 and t.lower() not in STOPWORDS]
    return " ".join(kept[:6]) or claim[:60]


async def query_wikipedia_summary(topic: str) -> dict:
    """Fetch clean Wikipedia REST summary (strictly BACKGROUND ONLY, never proof)."""
    short_q = _short_keywords(topic)
    headers = {"User-Agent": "CivicPulseIndia/4.1 (fact-check-background; contact@civicpulse.local)"}
    try:
        async with httpx.AsyncClient(timeout=6.0, headers=headers) as client:
            sr = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": short_q, "limit": 2, "format": "json"},
            )
            if sr.status_code != 200:
                return {"status": "error", "results": [], "detail": f"HTTP {sr.status_code}"}
            data = sr.json()
            titles = data[1] if isinstance(data, list) and len(data) > 1 else []
            results = []
            for title in titles[:2]:
                sum_r = await client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title.replace(' ', '_'))}")
                if sum_r.status_code == 200:
                    j = sum_r.json()
                    extract = _clean_text(j.get("extract", ""), 280)
                    if extract:
                        results.append({
                            "title": j.get("title", title),
                            "url": j.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{quote_plus(title)}"),
                            "snippet": extract,
                            "role": "background_only",
                        })
            return {"status": "ok", "results": results, "detail": f"{len(results)} background article(s)"}
    except Exception as exc:
        return {"status": "error", "results": [], "detail": str(exc)[:120]}


async def query_gdelt_doc(query: str, max_records: int = 5) -> dict:
    """Keyless GDELT DOC 2.0 news & timeline retrieval."""
    short_q = _short_keywords(query)
    try:
        async with httpx.AsyncClient(timeout=7.0, headers={"User-Agent": "CivicPulseIndia/4.1"}) as client:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={"query": short_q, "mode": "artlist", "maxrecords": max_records, "format": "json", "sort": "DateDesc"},
            )
            if r.status_code != 200:
                return {"status": "error", "articles": [], "detail": f"HTTP {r.status_code}"}
            j = r.json()
            articles = []
            for a in j.get("articles", [])[:max_records]:
                articles.append({
                    "title": _clean_text(a.get("title", ""), 140),
                    "url": a.get("url", ""),
                    "publisher": a.get("domain", "GDELT"),
                    "published_at": a.get("seendate", ""),
                    "snippet": f"Published on {a.get('domain', 'news source')} ({a.get('seendate', '')[:8]}).",
                })
            return {"status": "ok", "articles": articles, "detail": f"{len(articles)} GDELT item(s)"}
    except Exception as exc:
        return {"status": "error", "articles": [], "detail": str(exc)[:120]}


async def query_google_news_rss(query: str, max_items: int = 5) -> dict:
    """Keyless Google News RSS fallback (India edition)."""
    short_q = _short_keywords(query)
    url = f"https://news.google.com/rss/search?q={quote_plus(short_q)}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        async with httpx.AsyncClient(timeout=7.0, headers={"User-Agent": "CivicPulseIndia/4.1"}) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return {"status": "error", "articles": [], "detail": f"HTTP {r.status_code}"}
            root = ET.fromstring(r.text)
            articles = []
            for item in root.findall(".//item")[:max_items]:
                title = _clean_text(item.findtext("title", ""), 150)
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                src = item.findtext("source", "Google News")
                articles.append({
                    "title": title,
                    "url": link,
                    "publisher": src,
                    "published_at": pub,
                    "snippet": f"{src} — {pub}",
                })
            return {"status": "ok", "articles": articles, "detail": f"{len(articles)} RSS item(s)"}
    except Exception as exc:
        return {"status": "error", "articles": [], "detail": str(exc)[:120]}


async def verify_claim_text(claim: str, category: str = "General") -> dict:
    cleaned = claim.strip()
    if not cleaned:
        raise ValueError("Claim text cannot be empty.")

    short_q = _short_keywords(cleaned)
    numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned)
    entities = [
        e for e in dict.fromkeys(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", cleaned))
        if e.lower() not in STOPWORDS
    ][:8]

    g_fc, tavily_res, news_res, gdelt_res, rss_res, wiki_res = await asyncio.gather(
        query_google_factcheck(short_q),
        query_tavily_search(f"{short_q} fact check PIB India"),
        query_newsdata(short_q),
        query_gdelt_doc(short_q),
        query_google_news_rss(f"{short_q} fact check"),
        query_wikipedia_summary(short_q),
    )

    providers = []
    evidence_sources = []
    background_sources = []

    # Track real provider statuses (failed/skipped excluded from sources_checked)
    if settings.GOOGLE_FACTCHECK_API_KEY:
        fc_claims = g_fc.get("claims", [])
        providers.append({"name": "Google Fact Check", "status": "ok" if not g_fc.get("error") else "error", "detail": f"{len(fc_claims)} match(es)" if not g_fc.get("error") else str(g_fc.get("error"))[:100]})
        for c in fc_claims:
            evidence_sources.append({
                "source_api": "Google Fact Check",
                "tier": "fact_checker",
                "publisher": c.get("publisher", "Fact Checker"),
                "rating": c.get("rating", ""),
                "title": f"[{c.get('rating', 'Checked')}] {c.get('publisher', '')}: {_clean_text(c.get('title') or c.get('text', ''), 120)}",
                "url": c.get("url", ""),
                "snippet": _clean_text(f"Claimant: {c.get('claimant', 'Unknown')} — Rating: {c.get('rating', 'N/A')}", 220),
            })
    else:
        providers.append({"name": "Google Fact Check", "status": "missing_key", "detail": "Set GOOGLE_FACT_CHECK_API_KEY in .env"})

    if settings.TAVILY_API_KEY:
        t_res = tavily_res.get("results", [])
        providers.append({"name": "Tavily Search", "status": "ok" if not tavily_res.get("error") else "error", "detail": f"{len(t_res)} result(s)"})
        for r in t_res:
            evidence_sources.append({
                "source_api": "Tavily",
                "tier": "news_web",
                "publisher": r.get("url", "").split("/")[2] if "://" in r.get("url", "") else "Web",
                "title": _clean_text(r.get("title", ""), 140),
                "url": r.get("url", ""),
                "snippet": _clean_text(r.get("snippet", ""), 220),
            })
    else:
        providers.append({"name": "Tavily Search", "status": "missing_key", "detail": "Set TAVILY_API_KEY in .env"})

    if settings.NEWSDATA_API_KEY:
        n_res = news_res.get("articles", [])
        providers.append({"name": "NewsData.io (~12h delayed)", "status": "ok" if not news_res.get("error") else "error", "detail": f"{len(n_res)} article(s)"})
        for a in n_res:
            evidence_sources.append({
                "source_api": "NewsData.io (recent)",
                "tier": "news_web",
                "publisher": "NewsData",
                "title": _clean_text(a.get("title", ""), 140),
                "url": a.get("url", ""),
                "snippet": _clean_text(a.get("snippet", ""), 220),
            })
    else:
        providers.append({"name": "NewsData.io", "status": "missing_key", "detail": "Set NEWSDATA_API_KEY in .env"})

    providers.append({"name": "GDELT DOC 2.0 (Keyless)", "status": gdelt_res["status"], "detail": gdelt_res["detail"]})
    for a in gdelt_res.get("articles", []):
        evidence_sources.append({
            "source_api": "GDELT",
            "tier": "news_web",
            "publisher": a["publisher"],
            "title": a["title"],
            "url": a["url"],
            "published_at": a.get("published_at", ""),
            "snippet": a["snippet"],
        })

    providers.append({"name": "Google News RSS (Keyless)", "status": rss_res["status"], "detail": rss_res["detail"]})
    for a in rss_res.get("articles", []):
        evidence_sources.append({
            "source_api": "Google News RSS",
            "tier": "news_web",
            "publisher": a["publisher"],
            "title": a["title"],
            "url": a["url"],
            "published_at": a.get("published_at", ""),
            "snippet": a["snippet"],
        })

    providers.append({"name": "Wikipedia REST (Background Only)", "status": wiki_res["status"], "detail": wiki_res["detail"]})
    for w in wiki_res.get("results", []):
        background_sources.append({
            "source_api": "Wikipedia (Background Only)",
            "tier": "background",
            "publisher": "Wikipedia",
            "title": w["title"],
            "url": w["url"],
            "snippet": w["snippet"],
        })

    # Honest verdict logic: Wikipedia NEVER proves or verifies a claim!
    verdict = "Unverified"
    confidence = 40.0
    reasoning_parts = []

    fc_matches = [s for s in evidence_sources if s.get("tier") == "fact_checker"]
    debunk_keywords = ("false", "fake", "hoax", "debunk", "baseless", "fabricated", "scam", "not true", "discontinued", "rumour", "rumor", "pib fact check")
    mislead_keywords = ("mislead", "altered", "partly", "out of context", "satire", "unfounded")

    if fc_matches:
        top = fc_matches[0]
        r_low = (top.get("rating", "") + " " + top.get("title", "")).lower()
        if any(w in r_low for w in debunk_keywords):
            verdict, confidence = "False", 92.0
            reasoning_parts.append(f"Direct fact-check match from {top['publisher']} rates this claim as {top.get('rating', 'False')}.")
        elif any(w in r_low for w in mislead_keywords):
            verdict, confidence = "Misleading", 82.0
            reasoning_parts.append(f"Fact-checker {top['publisher']} flags this claim as {top.get('rating', 'Misleading')}.")
        elif any(w in r_low for w in ("true", "correct", "accurate")):
            verdict, confidence = "True", 88.0
            reasoning_parts.append(f"Fact-checker {top['publisher']} confirms this claim ({top.get('rating', 'True')}).")
        else:
            verdict, confidence = "Unverified", 55.0
            reasoning_parts.append(f"Fact-check entry found from {top['publisher']} with rating '{top.get('rating', 'Unknown')}'.")
    else:
        # Check if Indian fact-checkers or official feeds in RSS/GDELT/Tavily explicitly debunk it
        debunk_hits = [
            s for s in evidence_sources
            if any(d in (s.get("url", "") + " " + s.get("publisher", "")).lower() for d in INDIAN_FACTCHECK_DOMAINS)
            or any(k in (s.get("title", "") + " " + s.get("snippet", "")).lower() for k in ("fact check", "fake", "hoax", "debunk", "pib fact check", "false"))
        ]
        if debunk_hits:
            verdict, confidence = "False", 78.0
            reasoning_parts.append(f"Retrieved {len(debunk_hits)} fact-check/debunk report(s) addressing this claim (e.g., {debunk_hits[0]['publisher']}).")
        else:
            verdict, confidence = "Unverified", 35.0
            reasoning_parts.append("No direct official statement or IFCN fact-check was found confirming or refuting this specific claim. Background context alone is never treated as proof.")

    active_ok = sum(1 for p in providers if p["status"] == "ok")
    all_sources = evidence_sources + background_sources

    harmful_keywords = ("digital arrest", "otp", "scam", "blackmail", "extortion", "deepfake")
    suggest_complaint = verdict in ("False", "Misleading") or any(k in cleaned.lower() for k in harmful_keywords)
    provider_diag = {p["name"]: p["status"] for p in providers}

    return {
        "claim": cleaned,
        "category": category,
        "short_query": short_q,
        "verdict": verdict,
        "confidence": confidence,
        "key_entities": entities,
        "numbers_extracted": numbers,
        "sources_checked": active_ok,
        "suggest_complaint": suggest_complaint,
        "reasoning": " ".join(reasoning_parts),
        "xai_summary": " ".join(reasoning_parts),
        "providers": providers,
        "provider_diagnostics": provider_diag,
        "sources": all_sources,
        "background_sources": background_sources,
        "disclaimer": "Probabilistic evidence, not legal proof.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine_mode": f"Evidence-Based RAG ({active_ok} active source(s))",
        # Explicitly NO simulated virality cascade or fake bot %
        "origin_trace": None,
    }
