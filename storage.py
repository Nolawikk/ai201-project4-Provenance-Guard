"""
SQLite-backed storage for submissions (the current state of each piece of
content) and the audit log (an append-only record of every classification
and appeal event).
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = "provenance_guard.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                content_id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                llm_score REAL,
                stylometric_score REAL,
                confidence REAL,
                attribution TEXT,
                label TEXT,
                status TEXT NOT NULL DEFAULT 'classified'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL,
                creator_id TEXT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                attribution TEXT,
                confidence REAL,
                llm_score REAL,
                stylometric_score REAL,
                status TEXT,
                appeal_reasoning TEXT
            )
            """
        )


def save_submission(creator_id, text, llm_score, style_score, confidence, attribution, label):
    content_id = str(uuid.uuid4())
    created_at = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO submissions
                (content_id, creator_id, text, created_at, llm_score,
                 stylometric_score, confidence, attribution, label, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'classified')
            """,
            (content_id, creator_id, text, created_at, llm_score, style_score,
             confidence, attribution, label),
        )
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, timestamp, event_type, attribution,
                 confidence, llm_score, stylometric_score, status, appeal_reasoning)
            VALUES (?, ?, ?, 'classification', ?, ?, ?, ?, 'classified', NULL)
            """,
            (content_id, creator_id, created_at, attribution, confidence, llm_score, style_score),
        )
    return content_id, created_at


def get_submission(content_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE content_id = ?", (content_id,)
        ).fetchone()
    return dict(row) if row else None


def file_appeal(content_id, creator_reasoning):
    submission = get_submission(content_id)
    if submission is None:
        return None
    timestamp = _now()
    with get_conn() as conn:
        conn.execute(
            "UPDATE submissions SET status = 'under_review' WHERE content_id = ?",
            (content_id,),
        )
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, timestamp, event_type, attribution,
                 confidence, llm_score, stylometric_score, status, appeal_reasoning)
            VALUES (?, ?, ?, 'appeal', ?, ?, ?, ?, 'under_review', ?)
            """,
            (content_id, submission["creator_id"], timestamp, submission["attribution"],
             submission["confidence"], submission["llm_score"], submission["stylometric_score"],
             creator_reasoning),
        )
    return timestamp


def get_log(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
