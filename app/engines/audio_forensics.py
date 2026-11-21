import asyncio
import io
import re
import wave
from datetime import datetime, timezone
import numpy as np
from scipy.fft import rfft, rfftfreq
from app.config import settings
from app.engines.cloud_providers import check_walter_voice, check_resemble_detect

SCAM_PATTERNS = [
    (r"digital\s+arrest", "Digital Arrest threat"),
    (r"\b(cbi|ed|customs|narcotics|cyber\s+crime\s+police)\b", "Law-enforcement impersonation"),
    (r"\b(otp|one\s+time\s+password|cvv|pin)\b", "OTP / credential harvesting"),
    (r"\b(kyc\s+update|kyc\s+expired|account\s+blocked|aadhaar\s+suspended)\b", "Fake KYC / account-block urgency"),
    (r"\b(upi\s+refund|scan\s+qr\s+to\s+receive|collect\s+request)\b", "UPI refund / QR scam"),
]


def detect_scam_patterns(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return {"scam_call_risk": 0.0, "status": "unavailable", "matched_phrases": [], "detail": "No transcript provided (configure GROQ_API_KEY for Whisper transcription)."}
    low = transcript.lower()
    hits = []
    for pat, label in SCAM_PATTERNS:
        for m in re.finditer(pat, low):
            hits.append({"pattern": label, "phrase": m.group(0)})
    risk = min(95.0, len(hits) * 30.0) if hits else 5.0
    return {
        "scam_call_risk": round(risk, 1),
        "status": "flag" if risk >= 45.0 else "pass",
        "matched_phrases": hits,
        "detail": f"Detected {len(hits)} Indian scam-call pattern(s)." if hits else "No common scam-call keywords detected in transcript.",
    }


async def analyze_audio_bytes(raw_bytes: bytes, filename: str = "audio.wav", transcript: str = "") -> dict:
    signals = []
    factors = []
    reasons = []
    cloud_ensemble = []
    limitations = [
        "Probabilistic evidence, not legal proof.",
        "Local DSP signals (spectral roll-off, noise floor, pause cadence) are supporting evidence only and cannot conclusively prove voice cloning on compressed or short clips.",
    ]

    duration_sec = None
    sample_rate = None
    clone_risk = 20.0
    too_short = False

    try:
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            pcm = wf.readframes(n_frames)

        dtype = np.int16 if sampwidth == 2 else np.uint8
        audio = np.frombuffer(pcm, dtype=dtype).astype(np.float32)
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        audio = audio / (peak + 1e-6)
        duration_sec = round(len(audio) / float(sample_rate), 2) if sample_rate else 0.0

        if duration_sec < 6.0:
            too_short = True
            msg = f"Clip is too short ({duration_sec}s < 6.0s minimum) for a reliable voice-clone verdict."
            reasons.append(msg)
            factors.append({"signal": "Clip Duration Gate", "status": "WARN", "detail": msg})
            signals.append({"name": "Clip Duration Gate", "value": duration_sec, "unit": "sec", "threshold": ">= 6.0s", "status": "info", "weight": 0.0, "explanation": msg, "engine": "local_audio_dsp"})

        spectrum = np.abs(rfft(audio)) if len(audio) > 0 else np.array([1.0])
        freqs = rfftfreq(len(audio), 1.0 / sample_rate) if len(audio) > 0 else np.array([0.0])
        cumsum = np.cumsum(spectrum)
        rolloff_idx = int(np.searchsorted(cumsum, 0.95 * cumsum[-1])) if cumsum[-1] > 0 else 0
        rolloff_hz = round(float(freqs[min(rolloff_idx, len(freqs) - 1)]), 1)

        chunk_size = max(256, int(sample_rate * 0.25))
        chunks = [audio[i : i + chunk_size] for i in range(0, len(audio), chunk_size) if len(audio[i : i + chunk_size]) >= 128]
        rms_values = [float(np.sqrt(np.mean(c ** 2))) for c in chunks] if chunks else [float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 1e-5]
        silence_ratio = round(sum(1 for r in rms_values if r < 0.015) / max(1, len(rms_values)), 3)
        noise_floor_std = round(float(np.std(rms_values)), 4)

        if rolloff_hz < 5500 and sample_rate >= 16000:
            clone_risk += 22.0
            detail = f"Sharp high-frequency roll-off at {rolloff_hz} Hz (possible neural vocoder or telephony compression)."
            factors.append({"signal": "Spectral Roll-Off (95%)", "status": "FLAG", "detail": detail})
            signals.append({"name": "Spectral Roll-Off (95%)", "value": rolloff_hz, "unit": "Hz", "threshold": ">= 5500 Hz", "status": "flag", "weight": 0.35, "explanation": detail, "engine": "local_audio_dsp"})
        else:
            detail = f"Broadband vocal spectrum preserved up to {rolloff_hz} Hz."
            factors.append({"signal": "Spectral Roll-Off (95%)", "status": "PASS", "detail": detail})
            signals.append({"name": "Spectral Roll-Off (95%)", "value": rolloff_hz, "unit": "Hz", "threshold": ">= 5500 Hz", "status": "pass", "weight": 0.35, "explanation": detail, "engine": "local_audio_dsp"})

        if not too_short:
            if silence_ratio < 0.03:
                clone_risk += 18.0
                detail = f"Very low pause/breath ratio ({silence_ratio}) over {duration_sec}s."
                factors.append({"signal": "Pause / Breath Cadence", "status": "FLAG", "detail": detail})
                signals.append({"name": "Pause / Breath Cadence", "value": silence_ratio, "unit": "ratio", "threshold": ">= 0.03", "status": "flag", "weight": 0.30, "explanation": detail, "engine": "local_audio_dsp"})
            else:
                detail = f"Natural pause/breath cadence ({silence_ratio}) observed."
                factors.append({"signal": "Pause / Breath Cadence", "status": "PASS", "detail": detail})
                signals.append({"name": "Pause / Breath Cadence", "value": silence_ratio, "unit": "ratio", "threshold": ">= 0.03", "status": "pass", "weight": 0.30, "explanation": detail, "engine": "local_audio_dsp"})
        else:
            factors.append({"signal": "Pause / Breath Cadence", "status": "WARN", "detail": "Skipped on clips shorter than 6 seconds to prevent false positives."})

        factors.append({"signal": "RMS Energy Variance", "status": "PASS", "detail": f"Dynamic range std = {noise_floor_std}."})
    except Exception as exc:
        too_short = True
        msg = f"Compressed/non-WAV audio container ({exc}); upload 16 kHz mono WAV for local DSP or enable cloud keys."
        reasons.append(msg)
        factors.append({"signal": "Audio Container", "status": "WARN", "detail": msg})

    if settings.RESEMBLE_API_KEY:
        cloud_ensemble.append(await check_resemble_detect(raw_bytes, filename))
    else:
        cloud_ensemble.append({"provider": "Resemble AI Detect", "status": "unavailable", "detail": "Not configured (optional)"})

    if settings.WALTER_API_KEY:
        cloud_ensemble.append(await check_walter_voice(raw_bytes, filename))
    else:
        cloud_ensemble.append({"provider": "Walter AI Voice", "status": "unavailable", "detail": "Not configured (optional)"})

    scam_res = detect_scam_patterns(transcript)

    if too_short:
        clone_risk = min(45.0, clone_risk)
        verdict_label = "Inconclusive - needs analyst review"
    elif clone_risk >= 65.0:
        verdict_label = "Likely manipulated or synthetic"
        reasons.append("Multiple acoustic signals flagged potential vocoder synthesis.")
    elif clone_risk >= 40.0:
        verdict_label = "Inconclusive - needs analyst review"
        reasons.append("Moderate acoustic anomalies detected; manual review recommended.")
    else:
        verdict_label = "Likely authentic"
        reasons.append("Acoustic spectrum and cadence fall within normal human speech ranges.")

    clone_risk = round(clone_risk, 1)
    return {
        "duration_seconds": duration_sec,
        "sample_rate_hz": sample_rate,
        "voice_clone_risk_score": clone_risk,
        "authenticity_trust_score": round(100.0 - clone_risk, 1),
        "scam_call_risk": scam_res["scam_call_risk"],
        "scam_analysis": scam_res,
        "suggest_complaint": clone_risk >= 65.0 or scam_res["scam_call_risk"] >= 45.0,
        "verdict": verdict_label,
        "signals_schema": signals,
        "counterfactual_factors": factors,
        "xai_summary": " ".join(reasons),
        "cloud_ensemble": cloud_ensemble,
        "limitations": limitations,
        "disclaimer": "Probabilistic evidence, not legal proof.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
