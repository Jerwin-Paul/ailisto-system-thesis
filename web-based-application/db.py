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
from datetime import datetime

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Check your .env file.")


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
                role        TEXT NOT NULL DEFAULT 'teacher',
                created_at  TIMESTAMP DEFAULT NOW()
            );
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
        return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        return dict(row) if row else None


def create_user(email: str, password: str, first_name: str, last_name: str, role: str = "teacher") -> dict:
    hashed = hash_password(password)
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO users (email, password, first_name, last_name, role)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (email, hashed, first_name, last_name, role),
        )
        return dict(cur.fetchone())


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
        return [dict(r) for r in cur.fetchall()]


def create_session(subject_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO sessions (subject_id, status, start_time)
               VALUES (%s, 'active', NOW()) RETURNING *""",
            (subject_id,),
        )
        return dict(cur.fetchone())


def end_session(session_id: int, summary_stats: dict) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """UPDATE sessions SET status = 'completed', end_time = NOW(),
               summary_stats = %s WHERE id = %s RETURNING *""",
            (json.dumps(summary_stats), session_id),
        )
        return dict(cur.fetchone())


def get_sessions_by_date_range(teacher_id: int, start_date: str, end_date: str) -> list[dict]:
    """Return sessions for the teacher whose start_time falls within [start_date, end_date] (inclusive)."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT s.*, sub.name AS subject_name, sub.course_code, sub.section
            FROM sessions s
            JOIN subjects sub ON s.subject_id = sub.id
            WHERE sub.teacher_id = %s
              AND s.start_time >= %s::date
              AND s.start_time < (%s::date + INTERVAL '1 day')
            ORDER BY s.start_time ASC
        """, (teacher_id, start_date, end_date))
        return [dict(r) for r in cur.fetchall()]


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
        recent = [dict(r) for r in cur.fetchall()]

        return {
            "total_sessions": total_sessions,
            "avg_attention": avg_attention,
            "recent": recent,
        }
