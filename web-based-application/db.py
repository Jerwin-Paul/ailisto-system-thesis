"""
Database connection and helper functions for Ai-Listo.

Uses psycopg2 to connect to a Supabase PostgreSQL database.
Tables: users, subjects, schedules, sessions
"""

import os
import json
import hashlib
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

APP_TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Manila"))


def _to_app_timezone(dt: datetime | None) -> datetime | None:
    """Convert UTC (or naive UTC) datetimes to configured app timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(APP_TIMEZONE)


def _normalize_session_times(row: dict) -> dict:
    row["start_time"] = _to_app_timezone(row.get("start_time"))
    row["end_time"] = _to_app_timezone(row.get("end_time"))
    return row


def _normalize_user_row(row: dict | None) -> dict | None:
    if not row:
        return None

    avatar_bytes = row.pop("avatar_image", None)
    row.pop("avatar_mime_type", None)
    row["avatar_url"] = f"/api/users/{row['id']}/avatar" if avatar_bytes else None
    return row


# ─── Connection Helpers ───────────────────────────────────────────────

def get_connection():
    """Return a new psycopg2 connection using DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(commit=True):
    """Context manager that yields a dict-cursor and auto-commits."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ─── Schema Bootstrap ────────────────────────────────────────────────

def init_db():
    """Create tables if they don't already exist."""
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          SERIAL PRIMARY KEY,
                email       TEXT NOT NULL UNIQUE,
                password    TEXT NOT NULL,
                first_name  TEXT NOT NULL,
                last_name   TEXT NOT NULL,
                avatar_image BYTEA,
                avatar_mime_type TEXT,
                role        TEXT NOT NULL DEFAULT 'teacher',
                approval_status TEXT NOT NULL DEFAULT 'approved',
                approved_by INTEGER REFERENCES users(id),
                approved_at TIMESTAMP,
                created_at  TIMESTAMP DEFAULT NOW()
            );
        """)
        # Keep older databases compatible by adding the approval column if missing.
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'approved';
        """)
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS approved_by INTEGER;
        """)
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;
        """)
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS avatar_image BYTEA;
        """)
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime_type TEXT;",
        )
        cur.execute(
            """
            UPDATE users
            SET avatar_image = NULL,
                avatar_mime_type = NULL
            WHERE avatar_mime_type IS NOT NULL
              AND avatar_image IS NULL;
            """,
        )
        # Backfill audit timestamp for legacy approved accounts.
        cur.execute("""
            UPDATE users
            SET approved_at = created_at
            WHERE approval_status = 'approved' AND approved_at IS NULL;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id          SERIAL PRIMARY KEY,
                teacher_id  INTEGER NOT NULL REFERENCES users(id),
                name        TEXT NOT NULL,
                course_code TEXT NOT NULL,
                section     TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id          SERIAL PRIMARY KEY,
                subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                day         TEXT NOT NULL,
                start_time  TEXT NOT NULL,
                end_time    TEXT NOT NULL,
                room        TEXT DEFAULT ''
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id            SERIAL PRIMARY KEY,
                subject_id    INTEGER NOT NULL REFERENCES subjects(id),
                start_time    TIMESTAMP DEFAULT NOW(),
                end_time      TIMESTAMP,
                status        TEXT NOT NULL DEFAULT 'active',
                summary_stats JSONB
            );
        """)
        # Keep older databases compatible by backfilling missing session columns.
        cur.execute("""
            ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS start_time TIMESTAMP DEFAULT NOW();
        """)
        cur.execute("""
            ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS end_time TIMESTAMP;
        """)
        cur.execute("""
            ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
        """)
        cur.execute("""
            ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS summary_stats JSONB;
        """)


# ─── Password Hashing ────────────────────────────────────────────────

def update_user_password(user_id: int, new_password: str):
    """Hash and persist a new password for the given user."""
    hashed = hash_password(new_password)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (hashed, user_id),
        )


def hash_password(password: str) -> str:
    """Hash a password with scrypt + random salt. Returns 'hex.salt'."""
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return f"{hashed.hex()}.{salt}"


def verify_password(supplied: str, stored: str) -> bool:
    """Verify a password against a stored 'hex.salt' hash."""
    if "." not in stored:
        # Plain-text fallback (legacy)
        return supplied == stored
    hashed_hex, salt = stored.rsplit(".", 1)
    hashed = hashlib.scrypt(supplied.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return secrets.compare_digest(hashed.hex(), hashed_hex)


# ─── User Operations ─────────────────────────────────────────────────

def get_user_by_id(user_id: int) -> dict | None:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return _normalize_user_row(dict(row) if row else None)


def get_user_by_email(email: str) -> dict | None:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        return _normalize_user_row(dict(row) if row else None)


def update_user_profile(user_id: int, first_name: str, last_name: str, email: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE users
               SET first_name = %s,
                   last_name = %s,
                   email = %s
               WHERE id = %s
               RETURNING *""",
            (first_name, last_name, email, user_id),
        )
        row = cur.fetchone()
        return _normalize_user_row(dict(row) if row else None)


def update_user_avatar(user_id: int, avatar_image: bytes | None, avatar_mime_type: str | None) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE users
               SET avatar_image = %s,
                   avatar_mime_type = %s
               WHERE id = %s
               RETURNING *""",
            (psycopg2.Binary(avatar_image) if avatar_image is not None else None, avatar_mime_type, user_id),
        )
        row = cur.fetchone()
        return _normalize_user_row(dict(row) if row else None)


def get_user_avatar_blob(user_id: int) -> tuple[bytes, str] | None:
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT avatar_image, avatar_mime_type FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row or not row.get("avatar_image"):
            return None
        return bytes(row["avatar_image"]), row.get("avatar_mime_type") or "image/png"


def create_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: str = "teacher",
    approval_status: str = "approved",
) -> dict:
    hashed = hash_password(password)
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO users (email, password, first_name, last_name, role, approval_status)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (email, hashed, first_name, last_name, role, approval_status),
        )
        return _normalize_user_row(dict(cur.fetchone()))


def list_users() -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                u.*,
                CASE
                    WHEN reviewer.id IS NULL THEN NULL
                    ELSE reviewer.first_name || ' ' || reviewer.last_name
                END AS approved_by_name
            FROM users u
            LEFT JOIN users reviewer ON reviewer.id = u.approved_by
            ORDER BY u.created_at DESC, u.id DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_pending_users() -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                u.*,
                CASE
                    WHEN reviewer.id IS NULL THEN NULL
                    ELSE reviewer.first_name || ' ' || reviewer.last_name
                END AS approved_by_name
            FROM users u
            LEFT JOIN users reviewer ON reviewer.id = u.approved_by
            WHERE u.approval_status = 'pending'
            ORDER BY u.created_at ASC, u.id ASC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_approved_teachers() -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT id, first_name, last_name, email
            FROM users
            WHERE role = 'teacher' AND approval_status = 'approved'
            ORDER BY first_name, last_name
        """)
        return [dict(r) for r in cur.fetchall()]


def update_user_role(user_id: int, role: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE users
               SET role = %s
               WHERE id = %s
               RETURNING *""",
            (role, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_user_approval_status(user_id: int, approval_status: str, reviewed_by_user_id: int | None = None) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE users
               SET approval_status = %s,
                   approved_by = %s,
                   approved_at = NOW()
               WHERE id = %s
               RETURNING *""",
            (approval_status, reviewed_by_user_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─── Subject Operations ──────────────────────────────────────────────

def get_subjects(teacher_id: int) -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM subjects WHERE teacher_id = %s ORDER BY id", (teacher_id,))
        subjects = [dict(r) for r in cur.fetchall()]

        for subj in subjects:
            cur.execute("SELECT * FROM schedules WHERE subject_id = %s ORDER BY id", (subj["id"],))
            subj["schedules"] = [dict(r) for r in cur.fetchall()]

        return subjects


def create_subject(teacher_id: int, name: str, course_code: str, section: str,
                   schedule_entries: list[dict] | None = None) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO subjects (teacher_id, name, course_code, section)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (teacher_id, name, course_code, section),
        )
        subject = dict(cur.fetchone())
        subject["schedules"] = []

        if schedule_entries:
            for entry in schedule_entries:
                cur.execute(
                    """INSERT INTO schedules (subject_id, day, start_time, end_time, room)
                       VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                    (subject["id"], entry["day"], entry["startTime"], entry["endTime"], entry.get("room", "")),
                )
                subject["schedules"].append(dict(cur.fetchone()))

        return subject


def delete_subject(subject_id: int):
    with get_cursor() as cur:
        cur.execute("DELETE FROM schedules WHERE subject_id = %s", (subject_id,))
        cur.execute("DELETE FROM sessions WHERE subject_id = %s", (subject_id,))
        cur.execute("DELETE FROM subjects WHERE id = %s", (subject_id,))


# ─── Schedule Operations ─────────────────────────────────────────────

def update_subject_schedules(subject_id: int, entries: list[dict]) -> list[dict]:
    with get_cursor() as cur:
        cur.execute("DELETE FROM schedules WHERE subject_id = %s", (subject_id,))
        result = []
        for entry in entries:
            cur.execute(
                """INSERT INTO schedules (subject_id, day, start_time, end_time, room)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (subject_id, entry["day"], entry["startTime"], entry["endTime"], entry.get("room", "")),
            )
            result.append(dict(cur.fetchone()))
        return result


# ─── Session Operations ──────────────────────────────────────────────

def get_sessions(teacher_id: int) -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
            ORDER BY s.start_time DESC
        """, (teacher_id,))
        return [_normalize_session_times(dict(r)) for r in cur.fetchall()]


def get_sessions_paginated(teacher_id: int, page: int = 1, per_page: int = 25) -> tuple[list[dict], int]:
    """Get paginated sessions for a teacher.
    
    Args:
        teacher_id: The teacher's user ID
        page: Page number (1-indexed)
        per_page: Number of sessions per page
    
    Returns:
        Tuple of (sessions_list, total_count)
    """
    offset = (page - 1) * per_page
    with get_cursor(commit=False) as cur:
        # Get total count
        cur.execute("""
            SELECT COUNT(*) as total
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
        """, (teacher_id,))
        total_count = cur.fetchone()["total"]
        
        # Get paginated results
        cur.execute("""
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
            ORDER BY s.start_time DESC
            LIMIT %s OFFSET %s
        """, (teacher_id, per_page, offset))
        sessions = [_normalize_session_times(dict(r)) for r in cur.fetchall()]
    
    return sessions, total_count


def get_sessions_for_month(teacher_id: int, year: int, month: int) -> list[dict]:
    """Get all sessions for a teacher within the given month."""
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
              AND s.start_time >= %s
              AND s.start_time < %s
            ORDER BY s.start_time DESC
            """,
            (teacher_id, month_start, month_end),
        )
        return [_normalize_session_times(dict(r)) for r in cur.fetchall()]


def get_session_month_options(teacher_id: int) -> list[str]:
    """Return distinct months with sessions for a teacher as YYYY-MM values."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT DATE_TRUNC('month', s.start_time) AS month_start
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
              AND s.start_time IS NOT NULL
            GROUP BY month_start
            ORDER BY month_start DESC
            """,
            (teacher_id,),
        )
        return [row["month_start"].strftime("%Y-%m") for row in cur.fetchall()]


def get_subject_for_teacher(subject_id: int, teacher_id: int) -> dict | None:
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM subjects WHERE id = %s AND teacher_id = %s",
            (subject_id, teacher_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_session(subject_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO sessions (subject_id, status, start_time)
               VALUES (%s, 'active', NOW()) RETURNING *""",
            (subject_id,),
        )
        return _normalize_session_times(dict(cur.fetchone()))


def end_session(session_id: int, summary_stats: dict) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE sessions SET status = 'completed', end_time = NOW(),
               summary_stats = %s WHERE id = %s RETURNING *""",
            (json.dumps(summary_stats), session_id),
        )
        return _normalize_session_times(dict(cur.fetchone()))


def get_sessions_by_date_range(
    teacher_id: int,
    start_date: str,
    end_date: str,
    subject_code: str = "",
    section: str = "",
) -> list[dict]:
    """Return teacher sessions in date range with optional subject and/or section filters."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
              AND s.start_time >= %s::date
              AND s.start_time < (%s::date + INTERVAL '1 day')
              AND (%s = '' OR sub.course_code = %s)
              AND (%s = '' OR sub.section = %s)
            ORDER BY s.start_time ASC
        """, (
            teacher_id,
            start_date,
            end_date,
            subject_code,
            subject_code,
            section,
            section,
        ))
        return [_normalize_session_times(dict(r)) for r in cur.fetchall()]


def get_dashboard_stats(teacher_id: int) -> dict:
    with get_cursor(commit=False) as cur:
        # Total sessions
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM sessions s JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
        """, (teacher_id,))
        total_sessions = cur.fetchone()["total"]

        # Average attention from summary_stats
        cur.execute("""
            SELECT AVG((summary_stats->>'avgAttention')::float) AS avg_att
            FROM sessions s JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s AND summary_stats IS NOT NULL
              AND summary_stats->>'avgAttention' IS NOT NULL
        """, (teacher_id,))
        row = cur.fetchone()
        avg_attention = round(row["avg_att"]) if row["avg_att"] else 0

        # Recent sessions
        cur.execute("""
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
            ORDER BY s.start_time DESC LIMIT 5
        """, (teacher_id,))
        recent = [_normalize_session_times(dict(r)) for r in cur.fetchall()]

        # Per-class attention summary for dashboard cards.
        cur.execute("""
            SELECT
                sub.id,
                sub.name,
                sub.course_code,
                sub.section,
                COUNT(s.id) AS total_sessions,
                AVG(
                    CASE
                        WHEN s.summary_stats IS NOT NULL
                         AND s.summary_stats->>'avgAttention' IS NOT NULL
                        THEN (s.summary_stats->>'avgAttention')::float
                        ELSE NULL
                    END
                ) AS avg_attention
            FROM subjects sub
            LEFT JOIN sessions s ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
            GROUP BY sub.id, sub.name, sub.course_code, sub.section
            ORDER BY sub.course_code ASC, sub.section ASC
        """, (teacher_id,))
        class_rows = cur.fetchall()
        class_attention = [
            {
                "id": row["id"],
                "name": row["name"],
                "course_code": row["course_code"],
                "section": row["section"],
                "total_sessions": row["total_sessions"],
                "avg_attention": round(row["avg_attention"]) if row["avg_attention"] is not None else None,
            }
            for row in class_rows
        ]

        return {
            "total_sessions": total_sessions,
            "avg_attention": avg_attention,
            "recent": recent,
            "class_attention": class_attention,
            # Weekly data is now loaded lazily via /api/weekly-attention.
            "weekly_attention": [],
        }


def get_history_summary_stats(teacher_id: int) -> dict:
    """Lightweight summary stats for history page cards."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                COUNT(s.id) AS total_sessions,
                AVG(
                    CASE
                        WHEN s.summary_stats IS NOT NULL
                         AND s.summary_stats->>'avgAttention' IS NOT NULL
                        THEN (s.summary_stats->>'avgAttention')::float
                        ELSE NULL
                    END
                ) AS avg_attention
            FROM subjects sub
            LEFT JOIN sessions s ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
            """,
            (teacher_id,),
        )
        row = cur.fetchone() or {}
        return {
            "total_sessions": int(row.get("total_sessions") or 0),
            "avg_attention": round(row.get("avg_attention")) if row.get("avg_attention") is not None else 0,
        }


def get_weekly_attention(teacher_id: int, week_start_date: datetime) -> dict:
    """Get attention data for a specific week (7 days starting from week_start_date).
    
    Args:
        teacher_id: The teacher's user ID
        week_start_date: The start date of the week (should be a Monday or any day in the week)
    
    Returns:
        Dictionary with 'dates' and 'week_range' keys
    """
    # Normalize to start of week (Monday) and end on Saturday.
    week_start = week_start_date.date()
    days_since_monday = week_start.weekday()  # Monday=0 ... Sunday=6
    week_start = week_start - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=5)
    
    with get_cursor(commit=False) as cur:
        cur.execute("""
            WITH days AS (
                SELECT generate_series(
                    %s::date,
                    %s::date,
                    INTERVAL '1 day'
                )::date AS day
            )
            SELECT
                d.day,
                AVG(
                    CASE
                        WHEN sub.id IS NOT NULL
                         AND s.summary_stats IS NOT NULL
                         AND s.summary_stats->>'avgAttention' IS NOT NULL
                        THEN (s.summary_stats->>'avgAttention')::float
                        ELSE NULL
                    END
                ) AS avg_attention
            FROM days d
            LEFT JOIN sessions s ON s.start_time::date = d.day
            LEFT JOIN subjects sub ON s.subject_id = sub.id AND sub.teacher_id = %s
            GROUP BY d.day
            ORDER BY d.day ASC
        """, (week_start, week_end, teacher_id))
        
        weekly_rows = cur.fetchall()
        weekly_attention = [
            {
                "label": row["day"].strftime("%a"),
                "value": round(row["avg_attention"]) if row["avg_attention"] is not None else None,
                "date": row["day"].isoformat(),
            }
            for row in weekly_rows
        ]
        
        return {
            "weekly_attention": weekly_attention,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        }
