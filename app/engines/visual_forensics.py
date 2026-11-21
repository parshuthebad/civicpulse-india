import asyncio
import base64
import io
import os
import tempfile
from datetime import datetime, timezone
import cv2
import numpy as np
from PIL import Image, ImageChops, ImageEnhance
from app.config import settings
from app.engines.cloud_providers import check_reality_defender, check_walter_image


def _encode_png_b64(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        return ""
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")


def _extract_frame_if_video(raw_bytes: bytes, filename: str) -> tuple[bytes, str]:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in (".mp4", ".mov", ".webm", ".avi", ".mkv"):
        return raw_bytes, "image"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name
        cap = cv2.VideoCapture(tmp_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(total // 2, max(0, total - 1)))
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise ValueError("Could not decode video frame.")
        ok_enc, buf = cv2.imencode(".png", frame)
        if not ok_enc:
            raise ValueError("Failed to encode extracted video frame.")
        return buf.tobytes(), f"video (keyframe {min(total // 2, total)}/{total})"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def _check_content_safety(img_bgr: np.ndarray, synthetic_risk: float) -> dict:
    ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    lower = np.array([0, 133, 77], dtype=np.uint8)
    upper = np.array([255, 173, 127], dtype=np.uint8)
    skin_mask = cv2.inRange(ycrcb, lower, upper)
    skin_ratio = round(float(np.count_nonzero(skin_mask)) / float(skin_mask.size) * 100.0, 1)

    sensitive_flag = skin_ratio >= 48.0
    harmful_deepfake_flag = synthetic_risk >= 60.0

    alerts = []
    if sensitive_flag:
        alerts.append(f"High skin-exposure region detected ({skin_ratio}%). If this is non-consensual, morphed, or explicit deepfake media, please file an official complaint immediately.")
    if harmful_deepfake_flag:
        alerts.append("Elevated synthetic manipulation markers detected. You may report this media to the Cyber Cell using the official Complaint Form.")

    return {
        "skin_exposure_pct": skin_ratio,
        "sensitive_content_warning": sensitive_flag,
        "suggest_complaint": sensitive_flag or harmful_deepfake_flag,
        "suggested_category": (
            "Non-Consensual / Explicit / Morphed Content"
            if sensitive_flag
            else ("Deepfake Image / Video Manipulation" if harmful_deepfake_flag else "General Verification")
        ),
        "safety_alerts": alerts,
    }


def analyze_visual_local(raw_bytes: bytes, filename: str = "upload.png", is_live_webcam: bool = False) -> dict:
    """Calibrated local visual forensics.
    - Accepts raw image/video bytes.
    - Classical heuristics (ELA, FFT, noise residual) are supporting evidence only.
    - One classical heuristic alone never pushes verdict past Inconclusive.
    - For live webcams, PRNU/noise residual is informational only and genuine live faces read Low.
    """
    frame_bytes, media_kind = _extract_frame_if_video(raw_bytes, filename)
    np_arr = np.frombuffer(frame_bytes, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError("Unsupported or corrupted image/video file. Please upload JPG, PNG, WebP, MP4, or PDF/DOCX.")

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # 1. Noise residual (informational only — cannot prove camera sensor without reference fingerprint)
    blurred = cv2.GaussianBlur(gray.astype(np.float32), (5, 5), 0)
    noise_residual = round(float(np.std(gray.astype(np.float32) - blurred)), 3)

    # 2. 2D-FFT spectral ratio
    f = np.fft.fft2(gray.astype(np.float32))
    fshift = np.fft.fftshift(f)
    mag = np.log1p(np.abs(fshift))
    cy, cx = h // 2, w // 2
    r_inner = max(8, min(h, w) // 8)
    y_idx, x_idx = np.ogrid[:h, :w]
    high_mask = ((y_idx - cy) ** 2 + (x_idx - cx) ** 2) > (r_inner ** 2)
    fft_ratio = round(float(np.mean(mag[high_mask]) / (np.mean(mag) + 1e-6)), 4)

    # 3. ELA (JPEG re-save difference)
    pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    resaved = Image.open(buf)
    ela_diff = ImageChops.difference(pil_img, resaved)
    ela_mean = round(float(np.mean(np.asarray(ela_diff, dtype=np.float32))), 2)

    # 4. Lighting symmetry
    left_mean = float(np.mean(gray[:, : w // 2]))
    right_mean = float(np.mean(gray[:, w // 2 :]))
    lighting_delta = round(abs(left_mean - right_mean), 2)

    if is_live_webcam:
        risk = 12.0
        fft_flagged = fft_ratio > 0.92
        if fft_flagged:
            risk += 14.0
        if ela_mean > 14.0:
            risk += 10.0
        risk = round(min(48.0, risk), 1)
        verdict_label = "Low" if risk < 30.0 else "Inconclusive - needs analyst review"
        safety = _check_content_safety(img_bgr, risk)
        return {
            "media_kind": "live_webcam",
            "dimensions": f"{w}x{h}",
            "synthetic_risk_score": risk,
            "authenticity_trust_score": round(100.0 - risk, 1),
            "verdict": verdict_label,
            "signals": {
                "prnu_sensor_noise_std": noise_residual,
                "lighting_asymmetry_delta": lighting_delta,
                "fft_spectral_ratio": fft_ratio,
                "ela_mean": ela_mean,
            },
            "content_safety": safety,
            "xai_summary": f"Live webcam check: {verdict_label} ({risk}%). Noise residual ({noise_residual}) is informational only.",
            "disclaimer": "Probabilistic evidence, not legal proof.",
        }

    # Static image / video keyframe analysis
    signals_list = []
    factors = []
    flags = 0
    risk = 15.0

    if ela_mean > 12.0:
        flags += 1
        risk += 18.0
        signals_list.append({"name": "Error Level Analysis (ELA)", "value": ela_mean, "unit": "delta", "threshold": "<= 12.0", "status": "flag", "weight": 0.30, "explanation": f"Elevated JPEG re-compression variance ({ela_mean}); can indicate localized edits or heavy re-saving.", "engine": "local_classical"})
        factors.append({"signal": "Error Level Analysis (ELA)", "status": "FLAG", "detail": f"Elevated JPEG re-compression variance ({ela_mean})."})
    else:
        signals_list.append({"name": "Error Level Analysis (ELA)", "value": ela_mean, "unit": "delta", "threshold": "<= 12.0", "status": "pass", "weight": 0.30, "explanation": f"Uniform compression profile ({ela_mean}).", "engine": "local_classical"})
        factors.append({"signal": "Error Level Analysis (ELA)", "status": "PASS", "detail": f"Uniform compression profile ({ela_mean})."})

    if fft_ratio > 0.90:
        flags += 1
        risk += 18.0
        signals_list.append({"name": "2D FFT Spectral Energy", "value": fft_ratio, "unit": "ratio", "threshold": "<= 0.90", "status": "flag", "weight": 0.30, "explanation": f"High-frequency spectral energy ({fft_ratio}) above baseline.", "engine": "local_classical"})
        factors.append({"signal": "2D FFT Spectral Energy", "status": "FLAG", "detail": f"High-frequency spectral energy ({fft_ratio}) above baseline."})
    else:
        signals_list.append({"name": "2D FFT Spectral Energy", "value": fft_ratio, "unit": "ratio", "threshold": "<= 0.90", "status": "pass", "weight": 0.30, "explanation": f"Spectral energy ({fft_ratio}) within natural range.", "engine": "local_classical"})
        factors.append({"signal": "2D FFT Spectral Energy", "status": "PASS", "detail": f"Spectral energy ({fft_ratio}) within natural range."})

    signals_list.append({
        "name": "Noise Residual (Informational)",
        "value": noise_residual,
        "unit": "std",
        "threshold": "informational",
        "status": "info",
        "weight": 0.0,
        "explanation": "Single-image noise residual cannot prove camera sensor identity without a reference fingerprint.",
        "engine": "local_classical",
    })
    factors.append({
        "signal": "Noise Residual (Informational)",
        "status": "PASS",
        "detail": f"Noise residual std={noise_residual} (informational only; not sensor proof).",
    })

    if flags == 1:
        risk = min(risk, 48.0)

    risk = round(min(92.0, risk), 1)
    if risk >= 60.0:
        label = "Likely manipulated or synthetic"
    elif risk >= 35.0 or (w < 256 or h < 256):
        label = "Inconclusive - needs analyst review"
    else:
        label = "Likely authentic"

    ela_vis = ImageEnhance.Brightness(ela_diff).enhance(12.0)
    ela_bgr = cv2.cvtColor(np.asarray(ela_vis), cv2.COLOR_RGB2BGR)
    mag_norm = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    fft_bgr = cv2.applyColorMap(mag_norm, cv2.COLORMAP_INFERNO)
    safety = _check_content_safety(img_bgr, risk)

    return {
        "media_kind": media_kind,
        "dimensions": f"{w}x{h}",
        "synthetic_risk_score": risk,
        "authenticity_trust_score": round(100.0 - risk, 1),
        "confidence_interval": [round(max(0.0, risk - 8.0), 1), round(min(100.0, risk + 8.0), 1)],
        "verdict": label,
        "signals": {
            "fft_spectral_ratio": fft_ratio,
            "ela_mean": ela_mean,
            "prnu_sensor_noise_std": noise_residual,
            "lighting_asymmetry_delta": lighting_delta,
        },
        "signals_schema": signals_list,
        "content_safety": safety,
        "counterfactual_factors": factors,
        "xai_summary": " ".join(f["detail"] for f in factors[:3]),
        "visualizations": {
            "fft_spectrum_b64": _encode_png_b64(cv2.resize(fft_bgr, (420, 260))),
            "ela_saliency_b64": _encode_png_b64(cv2.resize(ela_bgr, (420, 260))),
        },
        "limitations": [
            "Probabilistic evidence, not legal proof.",
            "Classical forensics (ELA, FFT, noise residual) are supporting evidence only; WhatsApp/social compression can mask or mimic artifacts.",
        ],
        "disclaimer": "Probabilistic evidence, not legal proof.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def analyze_visual_bytes(raw_bytes: bytes, filename: str = "upload.png", use_cloud: bool = True) -> dict:
    local_res = analyze_visual_local(raw_bytes, filename, is_live_webcam=False)
    cloud_ensemble = []

    if use_cloud:
        if settings.REALITY_DEFENDER_API_KEY:
            rd = await check_reality_defender(raw_bytes, filename)
            cloud_ensemble.append(rd)
        else:
            cloud_ensemble.append({"provider": "Reality Defender", "status": "unavailable", "detail": "Not configured (optional)"})

        if settings.WALTER_API_KEY:
            wi = await check_walter_image(raw_bytes, filename)
            cloud_ensemble.append(wi)
        else:
            cloud_ensemble.append({"provider": "Walter AI Image", "status": "unavailable", "detail": "Not configured (optional)"})

    local_res["cloud_ensemble"] = cloud_ensemble
    return local_res
