import time
import httpx
from app.config import settings

_HEALTH_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL_SEC = 600.0  # ~10 minutes


async def check_providers_health(force: bool = False) -> dict:
    """Check provider readiness without burning scarce paid/free quotas (Reality Defender, Sightengine, Tavily)."""
    now = time.time()
    if not force and _HEALTH_CACHE["data"] and (now - _HEALTH_CACHE["ts"]) < _CACHE_TTL_SEC:
        return _HEALTH_CACHE["data"]

    providers = []

    # 1. Quota-sensitive cloud APIs: check configuration only (never burn scan credits on health checks)
    quota_sensitive = [
        ("reality_defender", bool(settings.REALITY_DEFENDER_API_KEY), "Configured (quota-safe check)"),
        ("sightengine", bool(settings.SIGHTENGINE_USER and settings.SIGHTENGINE_SECRET), "Configured (quota-safe check)"),
        ("tavily_search", bool(settings.TAVILY_API_KEY), "Configured (quota-safe check)"),
        ("resemble_ai", bool(settings.RESEMBLE_API_KEY), "Configured (quota-safe check)"),
        ("newsdata_io", bool(settings.NEWSDATA_API_KEY), "Configured (~12h delayed free tier)"),
        ("gemini_llm", bool(settings.GEMINI_API_KEY), f"Configured ({settings.GEMINI_MODEL})"),
        ("groq_llm", bool(settings.GROQ_API_KEY), "Configured (quota-safe check)"),
        ("google_factcheck", bool(settings.GOOGLE_FACTCHECK_API_KEY), "Configured (quota-safe check)"),
    ]
    for name, has_key, ok_detail in quota_sensitive:
        providers.append({
            "name": name,
            "status": "ok" if has_key else "missing_key",
            "latency_ms": 0,
            "detail": ok_detail if has_key else "API key not set in .env",
        })

    # 2. Keyless public endpoints: lightweight HEAD/GET ping
    async with httpx.AsyncClient(timeout=4.0, headers={"User-Agent": "CivicPulseIndia/4.1 (health-check)"}) as client:
        for name, url in [
            ("mediawiki_wikipedia", "https://en.wikipedia.org/api/rest_v1/page/summary/India"),
            ("gdelt_doc", "https://api.gdeltproject.org/api/v2/doc/doc?query=India&mode=artlist&maxrecords=1&format=json"),
        ]:
            t0 = time.perf_counter()
            try:
                r = await client.get(url)
                ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code == 200:
                    providers.append({"name": name, "status": "ok", "latency_ms": ms, "detail": "Reachable (keyless)"})
                else:
                    providers.append({"name": name, "status": "error", "latency_ms": ms, "detail": f"HTTP {r.status_code}"})
            except httpx.TimeoutException:
                providers.append({"name": name, "status": "timeout", "latency_ms": 4000, "detail": "Request timed out"})
            except Exception as exc:
                providers.append({"name": name, "status": "error", "latency_ms": 0, "detail": str(exc)[:120]})

    active = sum(1 for p in providers if p["status"] == "ok")
    payload = {
        "status": "ok",
        "cached_ttl_sec": int(_CACHE_TTL_SEC),
        "active_count": active,
        "total_count": len(providers),
        "providers": providers,
    }
    _HEALTH_CACHE["ts"] = now
    _HEALTH_CACHE["data"] = payload
    return payload
