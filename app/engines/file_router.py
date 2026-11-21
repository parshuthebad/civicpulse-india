import hashlib
import os
import re


def sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename or "upload.bin")
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:120] or "upload.bin"


def detect_magic_type(raw_bytes: bytes, filename: str = "") -> dict:
    """Detect real media type from magic bytes (never trust file extension alone)."""
    head = raw_bytes[:32] if raw_bytes else b""
    sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else ""
    size = len(raw_bytes)
    safe_name = sanitize_filename(filename)

    detected_type = "unsupported"
    mime = "application/octet-stream"

    if head.startswith(b"\xff\xd8\xff"):
        detected_type, mime = "image", "image/jpeg"
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_type, mime = "image", "image/png"
    elif head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        detected_type, mime = "image", "image/gif"
    elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        detected_type, mime = "image", "image/webp"
    elif head.startswith(b"BM"):
        detected_type, mime = "image", "image/bmp"
    elif head.startswith(b"%PDF-"):
        detected_type, mime = "document", "application/pdf"
    elif head.startswith(b"PK\x03\x04"):
        # Check if DOCX / Office Open XML
        if b"word/" in raw_bytes[:4096]:
            detected_type, mime = "document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            detected_type, mime = "unsupported", "application/zip"
    elif head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        detected_type, mime = "audio", "audio/wav"
    elif head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        detected_type, mime = "audio", "audio/mpeg"
    elif head.startswith(b"fLaC"):
        detected_type, mime = "audio", "audio/flac"
    elif head.startswith(b"OggS"):
        detected_type, mime = "audio", "audio/ogg"
    elif len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            detected_type, mime = "audio", "audio/mp4"
        else:
            detected_type, mime = "video", "video/mp4"
    elif head.startswith(b"\x1a\x45\xdf\xa3"):
        detected_type, mime = "video", "video/webm"
    elif head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        detected_type, mime = "video", "video/x-msvideo"

    return {
        "name": safe_name,
        "detected_type": detected_type,
        "mime": mime,
        "size": size,
        "sha256": sha256,
    }
