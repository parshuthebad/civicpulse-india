import re
import zipfile
import io
from datetime import datetime, timezone


def analyze_document_bytes(raw_bytes: bytes, file_meta: dict) -> dict:
    """Inspect PDF/DOCX/certificate scans for incremental saves, edit traces, signatures, and links."""
    mime = file_meta.get("mime", "")
    signals = []
    reasons = []
    risk_score = 15.0
    limitations = [
        "Probabilistic evidence, not legal proof.",
        "Document forensics checks structural metadata, incremental saves, and signature markers; visual forgery on flattened scans requires manual analyst review.",
    ]

    if mime == "application/pdf":
        text_latin = raw_bytes.decode("latin-1", errors="ignore")
        eof_count = len(re.findall(r"%%EOF", text_latin))
        has_sig = bool(re.search(r"/Type\s*/Sig|/ByteRange", text_latin))
        producers = re.findall(r"/Producer\s*\(([^)]{1,120})\)", text_latin)
        creators = re.findall(r"/Creator\s*\(([^)]{1,120})\)", text_latin)
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s\)\]>\"']{4,120}", text_latin)))[:10]

        if eof_count > 1:
            risk_score += 35.0
            signals.append({
                "name": "PDF Incremental Saves (%%EOF)",
                "value": eof_count,
                "unit": "revisions",
                "threshold": "1",
                "status": "flag",
                "weight": 0.45,
                "explanation": f"Detected {eof_count} %%EOF markers indicating the PDF was modified/re-saved after initial creation.",
                "engine": "local_pdf_struct",
            })
            reasons.append(f"PDF contains {eof_count} incremental save revisions (%%EOF), indicating post-issuance edits.")
        else:
            signals.append({
                "name": "PDF Incremental Saves (%%EOF)",
                "value": eof_count,
                "unit": "revisions",
                "threshold": "1",
                "status": "pass",
                "weight": 0.45,
                "explanation": "Single %%EOF marker; no incremental save revisions detected.",
                "engine": "local_pdf_struct",
            })

        editor_hits = [p for p in (producers + creators) if any(k in p.lower() for k in ("photoshop", "illustrator", "canva", "sejda", "ilovepdf", "foxit", "acrobat", "pdfescape", "smallpdf"))]
        if editor_hits:
            risk_score += 25.0
            signals.append({
                "name": "PDF Producer / Editor Trace",
                "value": ", ".join(dict.fromkeys(editor_hits))[:100],
                "unit": "metadata",
                "threshold": "official issuer",
                "status": "flag",
                "weight": 0.30,
                "explanation": f"Document metadata references consumer/graphics editing software: {', '.join(dict.fromkeys(editor_hits))}.",
                "engine": "local_pdf_struct",
            })
            reasons.append(f"PDF metadata references editing tool(s): {', '.join(dict.fromkeys(editor_hits))}.")
        else:
            signals.append({
                "name": "PDF Producer / Editor Trace",
                "value": (producers[0] if producers else "Not specified"),
                "unit": "metadata",
                "threshold": "official issuer",
                "status": "info",
                "weight": 0.20,
                "explanation": "No consumer PDF/image editor strings found in header metadata.",
                "engine": "local_pdf_struct",
            })

        signals.append({
            "name": "Digital Signature Dictionary",
            "value": "Present" if has_sig else "Absent",
            "unit": "boolean",
            "threshold": "Present for e-signed certificates",
            "status": "pass" if has_sig else "info",
            "weight": 0.25,
            "explanation": "Cryptographic signature block (/Sig /ByteRange) found." if has_sig else "No cryptographic digital signature block embedded (informational; many scanned certificates lack one).",
            "engine": "local_pdf_struct",
        })

        if urls:
            signals.append({
                "name": "Embedded Links / QR URLs",
                "value": len(urls),
                "unit": "links",
                "threshold": "verify domain",
                "status": "info",
                "weight": 0.1,
                "explanation": f"Extracted {len(urls)} URL(s): {', '.join(urls[:3])}",
                "engine": "local_pdf_struct",
            })

    elif "wordprocessingml" in mime:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
                names = zf.namelist()
                core_xml = zf.read("docProps/core.xml").decode("utf-8", errors="ignore") if "docProps/core.xml" in names else ""
                rev_match = re.search(r"<cp:revision>(\d+)</cp:revision>", core_xml)
                rev = int(rev_match.group(1)) if rev_match else 1
                signals.append({
                    "name": "DOCX Revision Count",
                    "value": rev,
                    "unit": "revisions",
                    "threshold": "<= 2",
                    "status": "flag" if rev > 5 else "info",
                    "weight": 0.4,
                    "explanation": f"Document core.xml reports {rev} revision(s).",
                    "engine": "local_docx_struct",
                })
                if rev > 5:
                    risk_score += 20.0
                    reasons.append(f"DOCX has {rev} recorded revisions.")
        except Exception as exc:
            limitations.append(f"Could not parse DOCX archive cleanly: {exc}")

    risk_score = round(min(95.0, max(5.0, risk_score)), 1)
    if risk_score >= 60.0:
        label = "Likely manipulated or synthetic"
    elif risk_score >= 35.0:
        label = "Inconclusive - needs analyst review"
    else:
        label = "Likely authentic"

    if not reasons:
        reasons.append("No structural tampering markers (incremental saves or graphics-editor traces) were detected.")

    factors = [{"signal": s["name"], "status": s["status"].upper(), "detail": s["explanation"]} for s in signals]
    return {
        "file": file_meta,
        "media_kind": "document",
        "dimensions": f"{file_meta.get('mime', 'document')} ({file_meta.get('size', 0)} bytes)",
        "verdict": label,
        "verdict_detail": {
            "label": label,
            "risk_score": risk_score,
            "confidence": 72.0 if risk_score >= 60.0 else 58.0,
            "reasons": reasons,
        },
        "synthetic_risk_score": risk_score,
        "authenticity_trust_score": round(100.0 - risk_score, 1),
        "confidence_interval": [round(max(0.0, risk_score - 8.0), 1), round(min(100.0, risk_score + 8.0), 1)],
        "signals": signals,
        "counterfactual_factors": factors,
        "cloud_ensemble": [{"provider": "Local Document Forensics", "status": "ok", "detail": "Structural PDF/DOCX inspection"}],
        "visualizations": {},
        "content_safety": {
            "suggest_complaint": risk_score >= 60.0,
            "suggested_category": "Document / Certificate Forgery",
            "safety_alerts": reasons if risk_score >= 60.0 else [],
        },
        "limitations": limitations,
        "disclaimer": "Probabilistic evidence, not legal proof.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "xai_summary": " ".join(reasons),
    }
