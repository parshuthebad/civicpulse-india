import asyncio
import base64
import hashlib
import io
import json
import wave
import numpy as np
from PIL import Image, ImageDraw
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.database import (
    init_db,
    save_history_item,
    list_history,
    get_history_item,
    delete_history_item,
    clear_section_history,
    save_complaint,
    list_complaints,
    delete_complaint,
)
from app.engines.visual_forensics import analyze_visual_bytes, analyze_visual_local
from app.engines.audio_forensics import analyze_audio_bytes
from app.engines.provenance_engine import audit_provenance
from app.engines.fact_rag_engine import (
    verify_claim_text,
    query_gdelt_doc,
    query_google_news_rss,
    query_wikipedia_summary,
)
from app.engines.health import check_providers_health
from app.engines.file_router import detect_magic_type
from app.engines.document_forensics import analyze_document_bytes
from app.engines.cloud_providers import query_google_factcheck, query_newsdata, query_parallel_search, query_mediawiki

init_db()

app = FastAPI(
    title="CivicPulse — National Deepfake & Fact-Verification Portal (Government of India)",
    version="4.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")


class ClaimRequest(BaseModel):
    claim: str
    category: str = "General"


class LiveSnapshotRequest(BaseModel):
    verdict: str
    synthetic_risk_score: float
    prnu_noise: float
    lighting_delta: float
    detected_objects: list[str] = []
    xai_summary: str


class ComplaintRequest(BaseModel):
    full_name: str
    mobile: str
    email: str
    age: int
    place: str
    category: str
    description: str
    source_section: str = "fact"
    evidence_ref: str = ""


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="#0B1F3A"/>'
        '<circle cx="16" cy="16" r="9" fill="none" stroke="#FF9933" stroke-width="2.5"/>'
        '<circle cx="16" cy="16" r="3" fill="#138808"/>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/v1/status")
async def get_system_status():
    return {
        "engine_mode": settings.mode,
        "zero_retention_mode": settings.ZERO_RETENTION_MODE,
        "connected_apis": settings.provider_status(),
    }


@app.get("/api/health")
async def get_provider_health(force: bool = Query(default=False)):
    return await check_providers_health(force=force)


@app.get("/api/v1/live-feed")
async def get_live_civic_feed(topic: str = Query(default="India election AI deepfake"), save: bool = Query(default=False)):
    g_fc, news, gdelt, rss, wiki = await asyncio.gather(
        query_google_factcheck(topic),
        query_newsdata(topic),
        query_gdelt_doc(topic, max_records=6),
        query_google_news_rss(topic, max_items=6),
        query_wikipedia_summary(topic),
    )
    # Merge keyless GDELT + Google News RSS into news articles so cards are never empty without paid keys
    merged_news = list(news.get("articles", []))
    seen_urls = {a.get("url") for a in merged_news if a.get("url")}
    for src in (gdelt.get("articles", []), rss.get("articles", [])):
        for a in src:
            if a.get("url") and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                merged_news.append(a)
    news_out = {**news, "articles": merged_news[:12], "status": "ok" if merged_news else news.get("status", "missing_key")}

    total_hits = (
        len(g_fc.get("claims", []))
        + len(news_out.get("articles", []))
        + len(wiki.get("results", []))
    )
    result = {
        "topic": topic,
        "total_live_signals": total_hits,
        "google_factchecks": g_fc,
        "newsdata": news_out,
        "parallel_search": {"status": "ok", "results": [{"title": a["title"], "url": a["url"], "snippet": a["snippet"]} for a in gdelt.get("articles", [])[:5]]},
        "wikipedia": wiki,
    }
    history_meta = None
    if save:
        sha = hashlib.sha256(topic.encode("utf-8")).hexdigest()
        history_meta = save_history_item(
            section="feed",
            input_label=topic,
            verdict=f"{total_hits} Live Sources",
            score=min(100.0, float(total_hits * 10)),
            sha256_ref=sha,
            payload=result,
        )
    return {**result, "history_item": history_meta}


@app.post("/api/v1/audit/media")
async def audit_media(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit.")
    try:
        meta = detect_magic_type(raw, file.filename or "upload.bin")
        fname = meta["name"]
        dtype = meta["detected_type"]
        if dtype == "document":
            visual = analyze_document_bytes(raw, meta)
        elif dtype in ("image", "video"):
            visual = await analyze_visual_bytes(raw, fname, use_cloud=True)
        else:
            raise ValueError(f"Unsupported file type detected from magic bytes ({meta['mime']}). Upload JPG, PNG, WebP, MP4, PDF, or DOCX.")

        provenance = audit_provenance(raw, fname)
        payload = {"filename": fname, "file_meta": meta, "visual_forensics": visual, "provenance": provenance}
        hist = save_history_item(
            section="visual",
            input_label=f"{fname} ({visual.get('dimensions', dtype)})",
            verdict=visual["verdict"],
            score=visual["synthetic_risk_score"],
            sha256_ref=provenance["sha256_certificate"],
            payload=payload,
        )
        return {**payload, "history_item": hist}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/audit/media/sample")
async def audit_media_sample():
    img = Image.new("RGB", (640, 420), color=(28, 46, 74))
    draw = ImageDraw.Draw(img)
    draw.rectangle([170, 95, 470, 325], fill=(225, 195, 160), outline=(255, 255, 255), width=4)
    draw.text((210, 200), "CivicPulse Demo Media", fill=(18, 18, 18))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()

    fname = "civicpulse_demo_sample.png"
    visual = await analyze_visual_bytes(raw, fname, use_cloud=True)
    provenance = audit_provenance(raw, fname)
    payload = {"filename": fname, "visual_forensics": visual, "provenance": provenance}
    hist = save_history_item(
        section="visual",
        input_label=f"{fname} ({visual['dimensions']})",
        verdict=visual["verdict"],
        score=visual["synthetic_risk_score"],
        sha256_ref=provenance["sha256_certificate"],
        payload=payload,
    )
    return {**payload, "history_item": hist}


@app.post("/api/v1/audit/audio")
async def audit_audio(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    try:
        fname = file.filename or "audio.wav"
        audio_res = await analyze_audio_bytes(raw, fname)
        sha = hashlib.sha256(raw).hexdigest()
        payload = {"filename": fname, "audio_forensics": audio_res, "sha256_certificate": sha}
        hist = save_history_item(
            section="audio",
            input_label=fname,
            verdict=audio_res["verdict"],
            score=audio_res["voice_clone_risk_score"],
            sha256_ref=sha,
            payload=payload,
        )
        return {**payload, "history_item": hist}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/audit/audio/sample")
async def audit_audio_sample():
    sr = 16000
    t = np.linspace(0, 3.5, int(sr * 3.5), endpoint=False)
    sig = 0.45 * np.sin(2 * np.pi * 440 * t) + 0.15 * np.sin(2 * np.pi * 1280 * t)
    pcm = (sig * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    raw = buf.getvalue()

    fname = "civicpulse_demo_voice.wav"
    audio_res = await analyze_audio_bytes(raw, fname)
    sha = hashlib.sha256(raw).hexdigest()
    payload = {"filename": fname, "audio_forensics": audio_res, "sha256_certificate": sha}
    hist = save_history_item(
        section="audio",
        input_label=fname,
        verdict=audio_res["verdict"],
        score=audio_res["voice_clone_risk_score"],
        sha256_ref=sha,
        payload=payload,
    )
    return {**payload, "history_item": hist}


@app.post("/api/v1/audit/claim")
async def audit_claim(payload: ClaimRequest):
    try:
        result = await verify_claim_text(payload.claim, payload.category)
        sha = hashlib.sha256(payload.claim.encode("utf-8")).hexdigest()
        full_out = {"fact_check": result, "sha256_certificate": sha}
        hist = save_history_item(
            section="fact",
            input_label=payload.claim.strip(),
            verdict=result["verdict"],
            score=result["confidence"],
            sha256_ref=sha,
            payload=full_out,
        )
        return {**full_out, "history_item": hist}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/audit/live-snapshot")
async def save_live_snapshot(snap: LiveSnapshotRequest):
    raw_str = json.dumps(snap.model_dump(), sort_keys=True)
    sha = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    obj_summary = ", ".join(snap.detected_objects[:5]) if snap.detected_objects else "No objects labeled"
    payload = {"live_snapshot": snap.model_dump(), "sha256_certificate": sha}
    hist = save_history_item(
        section="live",
        input_label=f"Live Camera: {obj_summary}",
        verdict=snap.verdict,
        score=snap.synthetic_risk_score,
        sha256_ref=sha,
        payload=payload,
    )
    return {**payload, "history_item": hist}


# === OFFICIAL CYBER COMPLAINT ENDPOINTS ===

@app.post("/api/v1/complaints")
async def create_complaint(req: ComplaintRequest):
    if len(req.full_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Please enter a valid full name.")
    if len(req.mobile.strip()) < 10:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number.")
    record = save_complaint(req.model_dump())
    return {"status": "submitted", "complaint": record}


@app.get("/api/v1/complaints")
async def api_list_complaints(limit: int = 30):
    return {"complaints": list_complaints(limit=limit)}


@app.delete("/api/v1/complaints/{complaint_id}")
async def api_delete_complaint(complaint_id: int):
    if not delete_complaint(complaint_id):
        raise HTTPException(status_code=404, detail="Complaint not found.")
    return {"deleted": True, "id": complaint_id}


# === PERSISTENT HISTORY CRUD & DOWNLOAD ENDPOINTS ===

@app.get("/api/v1/history/{section}")
async def api_list_history(section: str, limit: int = 25):
    return {"section": section, "items": list_history(section, limit=limit)}


@app.get("/api/v1/history/item/{item_id}")
async def api_get_history_item(item_id: int):
    item = get_history_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="History record not found.")
    return item


@app.get("/api/v1/history/item/{item_id}/download")
async def api_download_history_item(item_id: int):
    item = get_history_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="History record not found.")
    filename = f"CivicPulse_{item['section']}_audit_{item_id}.json"
    return JSONResponse(
        content=item,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/v1/history/item/{item_id}")
async def api_delete_history_item(item_id: int):
    if not delete_history_item(item_id):
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"deleted": True, "id": item_id}


@app.delete("/api/v1/history/section/{section}")
async def api_clear_section_history(section: str):
    count = clear_section_history(section)
    return {"cleared": count, "section": section}


@app.websocket("/ws/live-audit")
async def live_stream_audit(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data_url = await ws.receive_text()
            if "," in data_url:
                _, b64_data = data_url.split(",", 1)
                frame_bytes = base64.b64decode(b64_data)
                res = analyze_visual_local(frame_bytes, "webcam.jpg", is_live_webcam=True)
                await ws.send_json({
                    "synthetic_risk_score": res["synthetic_risk_score"],
                    "authenticity_trust_score": res["authenticity_trust_score"],
                    "verdict": res["verdict"],
                    "prnu_noise": res["signals"]["prnu_sensor_noise_std"],
                    "lighting_delta": res["signals"]["lighting_asymmetry_delta"],
                    "sensitive_warning": res["content_safety"]["sensitive_content_warning"],
                    "skin_exposure_pct": res["content_safety"]["skin_exposure_pct"],
                    "xai_summary": res["xai_summary"],
                })
    except WebSocketDisconnect:
        pass
