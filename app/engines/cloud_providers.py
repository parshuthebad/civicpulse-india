"""Live Real-Time API Connectors for CivicPulse Portal."""
import asyncio
import httpx
from app.config import settings


async def check_reality_defender(raw_bytes: bytes, filename: str) -> dict:
    if not settings.REALITY_DEFENDER_API_KEY:
        return {"provider": "Reality Defender", "status": "skipped", "reason": "API key not configured"}

    headers = {
        "X-API-KEY": settings.REALITY_DEFENDER_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            presign = await client.post(
                "https://api.prd.realitydefender.xyz/api/files/aws-presigned",
                headers=headers,
                json={"fileName": filename or "audit_media.jpg"},
            )
            if presign.status_code >= 400:
                return {"provider": "Reality Defender", "status": "error", "http_status": presign.status_code, "detail": presign.text[:220]}

            p_data = presign.json()
            signed_url = p_data.get("response", {}).get("signedUrl") or p_data.get("signedUrl")
            request_id = p_data.get("requestId") or p_data.get("mediaId")
            if not signed_url:
                return {"provider": "Reality Defender", "status": "error", "detail": "No signedUrl returned"}

            up = await client.put(signed_url, content=raw_bytes)
            if up.status_code >= 400:
                return {"provider": "Reality Defender", "status": "error", "detail": f"Upload failed ({up.status_code})"}

            if request_id:
                for _ in range(3):
                    await asyncio.sleep(1.3)
                    res = await client.get(
                        f"https://api.prd.realitydefender.xyz/api/media/users/{request_id}",
                        headers={"X-API-KEY": settings.REALITY_DEFENDER_API_KEY},
                    )
                    if res.status_code == 200:
                        body = res.json()
                        summary = body.get("resultsSummary", {})
                        status = summary.get("status")
                        if status and status not in ("ANALYZING", "QUEUED", "PROCESSING"):
                            return {
                                "provider": "Reality Defender",
                                "status": "live_ok",
                                "request_id": request_id,
                                "verdict": status,
                                "score": summary.get("metadata", {}).get("finalScore"),
                                "models_checked": len(body.get("models", [])),
                            }
                return {
                    "provider": "Reality Defender",
                    "status": "processing",
                    "request_id": request_id,
                    "detail": "Uploaded to Reality Defender cloud queue; async analysis in progress.",
                }
            return {"provider": "Reality Defender", "status": "uploaded", "detail": "Uploaded."}
    except Exception as e:
        return {"provider": "Reality Defender", "status": "error", "detail": str(e)}


async def check_walter_image(raw_bytes: bytes, filename: str) -> dict:
    if not settings.WALTER_API_KEY:
        return {"provider": "Walter AI Image", "status": "skipped", "reason": "API key not configured"}
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            resp = await client.post(
                "https://developer-portal.walterwrites.ai/api/image-detector/predict/",
                headers={"X-API-Key": settings.WALTER_API_KEY},
                files={"file": (filename or "image.png", raw_bytes)},
            )
            if resp.status_code >= 400:
                return {"provider": "Walter AI Image", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220]}
            return {"provider": "Walter AI Image", "status": "live_ok", "data": resp.json()}
    except Exception as e:
        return {"provider": "Walter AI Image", "status": "error", "detail": str(e)}


async def check_walter_voice(raw_bytes: bytes, filename: str) -> dict:
    if not settings.WALTER_API_KEY:
        return {"provider": "Walter AI Voice", "status": "skipped", "reason": "API key not configured"}
    try:
        async with httpx.AsyncClient(timeout=22.0) as client:
            resp = await client.post(
                "https://developer-portal.walterwrites.ai/api/voice-detector/detect/",
                headers={"X-API-Key": settings.WALTER_API_KEY},
                files={"file": (filename or "audio.wav", raw_bytes)},
            )
            if resp.status_code >= 400:
                return {"provider": "Walter AI Voice", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220]}
            return {"provider": "Walter AI Voice", "status": "live_ok", "data": resp.json()}
    except Exception as e:
        return {"provider": "Walter AI Voice", "status": "error", "detail": str(e)}


async def check_walter_text(text: str) -> dict:
    if not settings.WALTER_API_KEY:
        return {"provider": "Walter AI Text", "status": "skipped", "reason": "API key not configured"}
    try:
        async with httpx.AsyncClient(timeout=14.0) as client:
            resp = await client.post(
                "https://developer-portal.walterwrites.ai/api/detector/",
                headers={"X-API-Key": settings.WALTER_API_KEY, "Content-Type": "application/json"},
                json={"content": text},
            )
            if resp.status_code >= 400:
                return {"provider": "Walter AI Text", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220]}
            return {"provider": "Walter AI Text", "status": "live_ok", "data": resp.json()}
    except Exception as e:
        return {"provider": "Walter AI Text", "status": "error", "detail": str(e)}


async def check_resemble_detect(raw_bytes: bytes, filename: str) -> dict:
    if not settings.RESEMBLE_API_KEY:
        return {"provider": "Resemble AI Detect", "status": "skipped", "reason": "API key not configured"}
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            resp = await client.post(
                "https://app.resemble.ai/api/v2/detect",
                headers={"Authorization": f"Bearer {settings.RESEMBLE_API_KEY}"},
                files={"file": (filename or "audio.wav", raw_bytes)},
            )
            if resp.status_code >= 400:
                return {"provider": "Resemble AI Detect", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220]}
            return {"provider": "Resemble AI Detect", "status": "live_ok", "data": resp.json()}
    except Exception as e:
        return {"provider": "Resemble AI Detect", "status": "error", "detail": str(e)}


async def query_google_factcheck(query: str) -> dict:
    if not settings.GOOGLE_FACTCHECK_API_KEY:
        return {"provider": "Google Fact Check Tools", "status": "skipped", "claims": []}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://factchecktools.googleapis.com/v1alpha1/claims:search",
                params={"query": query, "languageCode": "en", "pageSize": 6, "key": settings.GOOGLE_FACTCHECK_API_KEY},
            )
            if resp.status_code >= 400:
                return {"provider": "Google Fact Check Tools", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220], "claims": []}
            data = resp.json()
            claims = []
            for c in data.get("claims", []):
                review = (c.get("claimReview") or [{}])[0]
                claims.append({
                    "text": c.get("text", ""),
                    "claimant": c.get("claimant", "Public Source"),
                    "publisher": review.get("publisher", {}).get("name", "Fact-Checker"),
                    "rating": review.get("textualRating", "Reviewed"),
                    "url": review.get("url", ""),
                    "title": review.get("title", ""),
                    "reviewDate": review.get("reviewDate", ""),
                })
            return {"provider": "Google Fact Check Tools", "status": "live_ok", "claims": claims}
    except Exception as e:
        return {"provider": "Google Fact Check Tools", "status": "error", "detail": str(e), "claims": []}


async def query_parallel_search(query: str) -> dict:
    if not settings.PARALLEL_API_KEY:
        return {"provider": "Parallel AI Search", "status": "skipped", "results": []}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.parallel.ai/v1/search",
                headers={"x-api-key": settings.PARALLEL_API_KEY, "Content-Type": "application/json"},
                json={"objective": query, "search_queries": [query], "max_results": 5},
            )
            if resp.status_code >= 400:
                return {"provider": "Parallel AI Search", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220], "results": []}
            data = resp.json()
            results = []
            for r in data.get("results", []):
                excerpts = r.get("excerpts") or []
                snippet = excerpts[0] if excerpts else r.get("snippet", "")
                results.append({"title": r.get("title", "Parallel Result"), "url": r.get("url", ""), "snippet": str(snippet)[:260]})
            return {"provider": "Parallel AI Search", "status": "live_ok", "results": results}
    except Exception as e:
        return {"provider": "Parallel AI Search", "status": "error", "detail": str(e), "results": []}


async def query_tavily_search(query: str) -> dict:
    if not settings.TAVILY_API_KEY:
        return {"provider": "Tavily Search", "status": "skipped", "reason": "Add TAVILY_API_KEY in .env", "results": []}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}", "Content-Type": "application/json"},
                json={"query": query, "search_depth": "advanced", "max_results": 4, "include_answer": True},
            )
            if resp.status_code >= 400:
                return {"provider": "Tavily Search", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220], "results": []}
            data = resp.json()
            results = [
                {"title": r.get("title", "Tavily"), "url": r.get("url", ""), "snippet": r.get("content", "")[:260]}
                for r in data.get("results", [])
            ]
            return {"provider": "Tavily Search", "status": "live_ok", "answer": data.get("answer"), "results": results}
    except Exception as e:
        return {"provider": "Tavily Search", "status": "error", "detail": str(e), "results": []}


async def query_newsdata(query: str) -> dict:
    if not settings.NEWSDATA_API_KEY:
        return {"provider": "NewsData.io", "status": "skipped", "reason": "Add NEWSDATA_API_KEY in .env", "articles": []}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://newsdata.io/api/1/latest",
                params={"apikey": settings.NEWSDATA_API_KEY, "q": query, "language": "en"},
            )
            if resp.status_code >= 400:
                return {"provider": "NewsData.io", "status": "error", "http_status": resp.status_code, "detail": resp.text[:220], "articles": []}
            data = resp.json()
            articles = [
                {
                    "title": a.get("title", ""),
                    "url": a.get("link", ""),
                    "source": a.get("source_id", "News"),
                    "pubDate": a.get("pubDate", ""),
                    "snippet": (a.get("description") or "")[:240],
                }
                for a in (data.get("results") or [])[:5]
            ]
            return {"provider": "NewsData.io", "status": "live_ok", "articles": articles}
    except Exception as e:
        return {"provider": "NewsData.io", "status": "error", "detail": str(e), "articles": []}


async def query_mediawiki(query: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "CivicPulseIndiaPortal/4.0"}) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 4},
            )
            if resp.status_code >= 400:
                return {"provider": "Wikipedia (MediaWiki API)", "status": "error", "results": []}
            data = resp.json()
            results = []
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "")
                snippet = item.get("snippet", "").replace('<span class="searchmatch">', "").replace("</span>", "")
                results.append({
                    "title": f"Wikipedia: {title}",
                    "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    "snippet": snippet[:240],
                })
            return {"provider": "Wikipedia (MediaWiki API)", "status": "live_ok", "results": results}
    except Exception as e:
        return {"provider": "Wikipedia (MediaWiki API)", "status": "error", "detail": str(e), "results": []}
