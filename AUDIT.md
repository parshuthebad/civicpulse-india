# CivicPulse India — Pre-Upgrade Audit (`AUDIT.md`)

## 1. Stack & Architecture
- **Backend:** FastAPI (`app/main.py`), Uvicorn, SQLite (`app/database.py`), Pydantic, NumPy, OpenCV, Pillow, SciPy, httpx.
- **Frontend:** Vanilla HTML/JS + Tailwind CSS (`static/index.html`, `static/app.js`) with 5 tabs:
  1. Fact-Check & RAG (`app/engines/fact_rag_engine.py`)
  2. Live Civic Pulse (`GET /api/v1/live-feed`)
  3. Visual & Video Forensics (`app/engines/visual_forensics.py`, `app/engines/provenance_engine.py`)
  4. Audio Voice-Clone (`app/engines/audio_forensics.py`)
  5. Live Camera Audit (WebSocket `/ws/live-audit` + browser COCO-SSD in `static/app.js`)
- **Env Loading:** `python-dotenv` via `load_dotenv()` in `app/config.py`.

## 2. Issues Identified & Fixed
| Area | Finding in Original Code | Fix Applied |
|---|---|---|
| **Header & Mesh UI** | `Live Multi-API (x/y Active)` badge counted env vars instead of real health; `Real-Time Verification Mesh` strip cluttered the top layout. | Removed both UI sections per request; added cached `GET /api/health` endpoint for real provider diagnostics. |
| **Fact-Check & RAG** | Wikipedia keyword matches (e.g., 2016 demonetisation) were counted as corroboration, causing the false RBI Rs 500 note claim to return `Verified 79%`. Simulated "Origin & Virality Cascade" (`T+14m`, `T+38m`, bot %). Naive `#The`/`#Reserve` tokens. | Wikipedia restricted strictly to **background only** (never proof). Added keyless GDELT DOC 2.0 + Google News RSS + PIB/RBI feeds + short-query Google Fact Check. Removed simulated cascade & bot %. Honest verdicts (`True`, `False`, `Misleading`, `Unverified`, `Outdated`). |
| **Live Civic Pulse** | Raw HTML entities (`&#039;`, `&quot;`) and mid-sentence cuts in Wikipedia; empty cards when paid keys missing. | Switched Wikipedia to REST summary with HTML unescaping & sentence-boundary trimming; added keyless GDELT/RSS fallbacks so cards are never empty. |
| **Visual/Video/Doc Forensics** | Extension-only routing; stripped EXIF treated as suspicious; single uncalibrated ELA/FFT heuristics could push verdicts past Inconclusive; no PDF/DOCX certificate inspection. | Added magic-byte router (`file_router.py`), PDF/DOCX forensic inspector (`document_forensics.py`), 3-state verdicts (`Likely authentic` / `Inconclusive - needs analyst review` / `Likely manipulated or synthetic`), EXIF stripping marked informational only. |
| **Audio Voice-Clone** | 3.5s clips scored 84% clone risk from heuristics alone; `0.0` silence/floor values on short clips; missing keys shown as red errors. | Enforced `>= 6.0s` minimum duration for firm verdicts (shorter => `Inconclusive: clip too short`), fixed DSP floor/cadence math, added Indian scam-call pattern detector, neutral `unavailable` chips for unconfigured cloud APIs. |
| **Live Camera Audit** | Uncalibrated FFT threshold (`0.76`) flagged genuine live webcams; PRNU used as sensor proof; screen-recapture banner fired without a screen detected. | Removed PRNU from risk score (relabeled informational), calibrated webcam FFT threshold, required `>= 2` agreeing signals over consecutive frames for screen-recapture, added Active Liveness Challenge. |
