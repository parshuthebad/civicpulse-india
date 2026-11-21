import hashlib
import io
import os
import tempfile
from datetime import datetime, timezone
from PIL import Image, ExifTags

try:
    import c2pa
    HAS_C2PA = True
except Exception:
    HAS_C2PA = False


def audit_provenance(raw_bytes: bytes, filename: str) -> dict:
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
    audit_timestamp = datetime.now(timezone.utc).isoformat()

    exif_data = {}
    anomalies = []
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        raw_exif = img.getexif()
        if raw_exif:
            for tag_id, val in raw_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                exif_data[tag_name] = str(val)[:120]
        else:
            anomalies.append("EXIF camera headers stripped (common in AI generators or WhatsApp/social re-uploads).")

        software = exif_data.get("Software", "").lower()
        if any(tool in software for tool in ["photoshop", "gimp", "stable diffusion", "midjourney", "firefly", "dall"]):
            anomalies.append(f"Editing/generative software tag detected: {exif_data.get('Software')}")
    except Exception:
        anomalies.append("Non-EXIF media container (e.g., MP4 video or binary stream).")

    head_bytes = raw_bytes[:2048]
    hex_flags = []
    for sig in [b"Lavf", b"Adobe", b"c2pa", b"jumb", b"SynthID"]:
        if sig in head_bytes or sig in raw_bytes[-4096:]:
            hex_flags.append(sig.decode("utf-8", errors="ignore"))

    c2pa_status = "No C2PA Manifest Found"
    c2pa_details = None
    if HAS_C2PA:
        suffix = os.path.splitext(filename)[1] or ".jpg"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            try:
                with c2pa.Reader(tmp_path) as reader:
                    c2pa_details = reader.json()[:600]
                    c2pa_status = "Valid C2PA Manifest Present"
            except Exception:
                c2pa_status = "No C2PA Content Credentials embedded"
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception:
            pass

    return {
        "sha256_certificate": sha256_hash,
        "audit_timestamp_utc": audit_timestamp,
        "c2pa_status": c2pa_status,
        "c2pa_manifest_preview": c2pa_details,
        "exif_fields_found": len(exif_data),
        "exif_sample": dict(list(exif_data.items())[:8]),
        "hex_signatures_detected": hex_flags,
        "metadata_anomalies": anomalies,
    }
