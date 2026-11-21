"""SQLite persistence layer for per-section CivicPulse audit history and Cyber Complaints."""
import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("civicpulse_history.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                input_label TEXT NOT NULL,
                verdict TEXT NOT NULL,
                score REAL NOT NULL,
                sha256_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_no TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                email TEXT NOT NULL,
                age INTEGER NOT NULL,
                place TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                source_section TEXT NOT NULL,
                evidence_ref TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_section_created ON audit_history(section, id DESC)")
        conn.commit()


def save_history_item(
    section: str,
    input_label: str,
    verdict: str,
    score: float,
    sha256_ref: str,
    payload: dict,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    clean_payload = json.loads(json.dumps(payload, default=str))
    payload_str = json.dumps(clean_payload)

    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_history (section, input_label, verdict, score, sha256_ref, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (section, input_label[:220], verdict, float(score), sha256_ref, created_at, payload_str),
        )
        item_id = cur.lastrowid
        conn.commit()

    return {
        "id": item_id,
        "section": section,
        "input_label": input_label[:220],
        "verdict": verdict,
        "score": float(score),
        "sha256_ref": sha256_ref,
        "created_at": created_at,
    }


def list_history(section: Optional[str] = None, limit: int = 30) -> list[dict]:
    with _get_conn() as conn:
        if section and section != "all":
            rows = conn.execute(
                """
                SELECT id, section, input_label, verdict, score, sha256_ref, created_at
                FROM audit_history
                WHERE section = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (section, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, section, input_label, verdict, score, sha256_ref, created_at
                FROM audit_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_history_item(item_id: int) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_history WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def delete_history_item(item_id: int) -> bool:
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM audit_history WHERE id = ?", (item_id,))
        conn.commit()
        return cur.rowcount > 0


def clear_section_history(section: str) -> int:
    with _get_conn() as conn:
        if section == "all":
            cur = conn.execute("DELETE FROM audit_history")
        else:
            cur = conn.execute("DELETE FROM audit_history WHERE section = ?", (section,))
        conn.commit()
        return cur.rowcount


def save_complaint(data: dict) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    ref_no = f"CP-IND-{datetime.now().year}-{random.randint(100000, 999999)}"
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO complaints (reference_no, full_name, mobile, email, age, place, category, description, source_section, evidence_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref_no,
                data["full_name"],
                data["mobile"],
                data["email"],
                int(data["age"]),
                data["place"],
                data["category"],
                data["description"],
                data["source_section"],
                data.get("evidence_ref", ""),
                created_at,
            ),
        )
        cid = cur.lastrowid
        conn.commit()
    return {"id": cid, "reference_no": ref_no, "created_at": created_at, **data}


def list_complaints(limit: int = 30) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM complaints ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_complaint(complaint_id: int) -> bool:
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
        conn.commit()
        return cur.rowcount > 0
