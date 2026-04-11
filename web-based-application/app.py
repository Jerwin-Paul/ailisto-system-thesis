import os
import io
import html
import json
import logging
import re
import secrets
import string
import time
import unicodedata
import requests
from requests.adapters import HTTPAdapter
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file,
)
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import db  # noqa: E402 — import after dotenv so DATABASE_URL is available

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(32).hex())

ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LOGIN_OTP_TTL_SECONDS = int(os.environ.get("LOGIN_OTP_TTL_SECONDS", "300"))
LOGIN_OTP_MAX_ATTEMPTS = int(os.environ.get("LOGIN_OTP_MAX_ATTEMPTS", "5"))
LOGIN_OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get("LOGIN_OTP_RESEND_COOLDOWN_SECONDS", "60"))
LOGIN_OTP_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_OTP_LOCKOUT_SECONDS", "300"))
LOGIN_OTP_ENABLED = os.environ.get("LOGIN_OTP_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
PASSWORD_REQUIRED_SYMBOLS = "!@#$%^&*"
TERMS_VERSION = "v1.0"
ADMIN_VIEW_MODE_SESSION_KEY = "admin_view_mode"
ADMIN_VIEW_MODE_ADMIN = "admin"
ADMIN_VIEW_MODE_TEACHER = "teacher"
ADMIN_VIEW_MODE_ALLOWED = {ADMIN_VIEW_MODE_ADMIN, ADMIN_VIEW_MODE_TEACHER}
ADMIN_HISTORY_TEACHER_SESSION_KEY = "admin_history_teacher_id"

TERMS_POLICY_SECTIONS = [
    {
        "heading": "1. Acceptance of Terms",
        "paragraphs": [
            "By creating an account and using the Ai-Listo system (\"Platform\"), you agree to comply with and be bound by these Terms of Service and Privacy Policy. If you do not agree, you should not use the Platform.",
        ],
    },
    {
        "heading": "2. Description of the Service",
        "paragraphs": [
            "Ai-Listo is a classroom-based system that uses real-time computer vision to analyze and provide insights into student attention levels during live class sessions. The system is intended solely for educational and instructional support.",
        ],
    },
    {
        "heading": "3. Nature of Data Collected",
        "paragraphs": [
            "The Platform collects and stores only non-personal, session-based data, including:",
        ],
        "bullets": [
            "Attention scores or classifications",
            "Session date",
            "Start and end times",
            "Session duration",
        ],
        "paragraphs_after": [
            "The system does not collect or store:",
        ],
        "bullets_after": [
            "Student names or personal identifiers",
            "Audio recordings",
            "Video or image recordings",
        ],
    },
    {
        "heading": "4. Local Processing and No Video Storage",
        "paragraphs": [
            "All video input used by the system is:",
        ],
        "bullets": [
            "Processed locally in real time",
            "Not recorded, stored, or uploaded",
            "Not accessible for playback, viewing, or monitoring",
        ],
        "paragraphs_after": [
            "No live classroom footage is transmitted or made available online.",
        ],
    },
    {
        "heading": "5. Privacy and Data Protection",
        "paragraphs": [
            "Ai-Listo is designed to prioritize privacy:",
        ],
        "bullets": [
            "No personally identifiable student data is collected",
            "Stored data is limited to aggregated session metrics",
            "Data is handled in accordance with applicable data privacy standards",
        ],
    },
    {
        "heading": "6. Use of Data",
        "paragraphs": ["Collected data may be used for:"],
        "bullets": [
            "Monitoring classroom engagement trends",
            "Supporting instructional decisions",
        ],
    },
    {
        "heading": "7. User Responsibilities",
        "paragraphs": ["As a Teacher using the Platform, you agree to:"],
        "bullets": [
            "Inform students that the system is being used in the classroom",
            "Ensure that a separate student consent/waiver has been obtained",
            "Use the system only for legitimate educational purposes",
            "Avoid misuse for surveillance or non-academic monitoring",
        ],
    },
    {
        "heading": "8. Limitations of the System",
        "paragraphs": ["You acknowledge that:"],
        "bullets": [
            "Attention detection results are estimates based on observable cues",
            "The system does not guarantee absolute accuracy",
            "Results should be used as supporting insights, not sole basis for decisions",
        ],
    },
    {
        "heading": "9. Account Responsibility",
        "paragraphs": ["You are responsible for:"],
        "bullets": [
            "Maintaining the confidentiality of your account",
            "All activities conducted under your account",
        ],
    },
    {
        "heading": "10. Modifications to the Service or Policy",
        "paragraphs": ["The developers of Ai-Listo reserve the right to:"],
        "bullets": [
            "Modify or update the system and these terms at any time",
            "Notify users of significant changes when applicable",
        ],
    },
    {
        "heading": "11. Consent",
        "paragraphs": ["By creating an account and using Ai-Listo, you:"],
        "bullets": [
            "Confirm that you have read and understood these Terms and Privacy Policy",
            "Agree to the collection and use of data as described",
            "Accept responsibility for complying with all applicable policies",
        ],
    },
]

# Bootstrap tables on startup
db.init_db()


def _resolve_month_selection(
    month_value: str | None = None,
    year_value: str | None = None,
    month_number_value: str | None = None,
) -> tuple[int, int, str]:
    """Resolve month selection from separate year/month or YYYY-MM inputs."""
    now = datetime.now()
    fallback_year = now.year
    fallback_month = now.month

    if year_value is not None or month_number_value is not None:
        try:
            year = int((year_value or "").strip())
            month_num = int((month_number_value or "").strip())
            if 1 <= month_num <= 12:
                return year, month_num, f"{year:04d}-{month_num:02d}"
        except (TypeError, ValueError):
            pass

    month_str = (month_value or "").strip()
    if not month_str:
        return fallback_year, fallback_month, f"{fallback_year:04d}-{fallback_month:02d}"

    try:
        parsed = datetime.strptime(month_str, "%Y-%m")
        return parsed.year, parsed.month, month_str
    except ValueError:
        return fallback_year, fallback_month, f"{fallback_year:04d}-{fallback_month:02d}"


def _duration_minutes_ignore_seconds(start_time: datetime | None, end_time: datetime | None) -> int | None:
    """Return duration in minutes using only HH:MM, ignoring seconds and microseconds."""
    if not start_time or not end_time:
        return None

    start_minute = start_time.replace(second=0, microsecond=0)
    end_minute = end_time.replace(second=0, microsecond=0)
    delta_seconds = (end_minute - start_minute).total_seconds()
    if delta_seconds < 0:
        # Guard against negative display values from clock/date edge cases.
        return 0
    return int(delta_seconds // 60)


def _parse_clock_to_minutes(value) -> int:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Missing time value.")

    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue

    raise ValueError(f"Invalid time value '{raw}'.")


def _minutes_to_clock(minutes: int) -> str:
    hour24 = (minutes // 60) % 24
    minute = minutes % 60
    period = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return f"{hour12}:{minute:02d} {period}"


def _normalize_schedule_day(value) -> str:
    return str(value or "").strip().lower()


def _build_schedule_slots(
    entries: list[dict] | None,
    *,
    source_label: str,
    require_complete_rows: bool,
) -> list[dict]:
    slots = []
    for idx, entry in enumerate(entries or [], start=1):
        day = str((entry or {}).get("day", "")).strip()
        start_raw = (entry or {}).get("startTime") or (entry or {}).get("start_time")
        end_raw = (entry or {}).get("endTime") or (entry or {}).get("end_time")

        has_any = bool(day or start_raw or end_raw)
        has_all = bool(day and start_raw and end_raw)

        if not has_any:
            continue

        if require_complete_rows and not has_all:
            raise ValueError(f"Schedule row #{idx} is incomplete. Please provide day, start time, and end time.")

        if not has_all:
            continue

        start_min = _parse_clock_to_minutes(start_raw)
        end_min = _parse_clock_to_minutes(end_raw)
        if start_min >= end_min:
            raise ValueError(f"Schedule row #{idx} has an invalid time range. End time must be after start time.")

        slots.append(
            {
                "source": source_label,
                "row": idx,
                "day": day,
                "day_key": _normalize_schedule_day(day),
                "start_min": start_min,
                "end_min": end_min,
                "start_label": _minutes_to_clock(start_min),
                "end_label": _minutes_to_clock(end_min),
            }
        )

    return slots


def _find_overlap(slots_a: list[dict], slots_b: list[dict]) -> tuple[dict, dict] | None:
    for first in slots_a:
        for second in slots_b:
            if first["day_key"] != second["day_key"]:
                continue
            if first["start_min"] < second["end_min"] and first["end_min"] > second["start_min"]:
                return first, second
    return None


def _validate_schedule_conflicts(
    teacher_id: int,
    candidate_entries: list[dict] | None,
    *,
    exclude_subject_id: int | None = None,
) -> None:
    candidate_slots = _build_schedule_slots(
        candidate_entries,
        source_label="new schedule",
        require_complete_rows=True,
    )

    # First, reject overlaps/duplicates within the payload itself.
    for i in range(len(candidate_slots)):
        for j in range(i + 1, len(candidate_slots)):
            first = candidate_slots[i]
            second = candidate_slots[j]
            if first["day_key"] != second["day_key"]:
                continue
            if first["start_min"] < second["end_min"] and first["end_min"] > second["start_min"]:
                raise ValueError(
                    "Schedule conflict in submitted entries: "
                    f"{first['day']} {first['start_label']} - {first['end_label']} overlaps with "
                    f"{second['day']} {second['start_label']} - {second['end_label']}."
                )

    existing_slots = []
    for subject in db.get_subjects(teacher_id):
        if exclude_subject_id is not None and subject.get("id") == exclude_subject_id:
            continue

        course_code = str(subject.get("course_code", "")).strip()
        section = str(subject.get("section", "")).strip()
        label = " ".join(part for part in [course_code, f"({section})" if section else ""] if part).strip() or "existing class"
        existing_slots.extend(
            _build_schedule_slots(
                subject.get("schedules") or [],
                source_label=label,
                require_complete_rows=False,
            )
        )

    conflict = _find_overlap(candidate_slots, existing_slots)
    if conflict:
        current, existing = conflict
        raise ValueError(
            "Schedule overlaps with an existing class: "
            f"{current['day']} {current['start_label']} - {current['end_label']} conflicts with "
            f"{existing['source']} ({existing['day']} {existing['start_label']} - {existing['end_label']})."
        )


# ─── Auth Helpers ─────────────────────────────────────────────────────

def _password_policy_unmet(password: str) -> list[str]:
    unmet = []
    symbol_pattern = f"[{re.escape(PASSWORD_REQUIRED_SYMBOLS)}]"
    if len(password) < 8:
        unmet.append("8 characters")
    if not re.search(r"[A-Z]", password):
        unmet.append("uppercase letter")
    if not re.search(r"[a-z]", password):
        unmet.append("lowercase letter")
    if not re.search(r"\d", password):
        unmet.append("number")
    if not re.search(symbol_pattern, password):
        unmet.append(f"symbol ({PASSWORD_REQUIRED_SYMBOLS})")
    return unmet


def _password_policy_message(unmet: list[str]) -> str:
    if not unmet:
        return ""
    length_missing = "8 characters" in unmet
    other_reqs = [item for item in unmet if item != "8 characters"]

    parts = []
    if length_missing:
        parts.append("at least 8 characters")

    if other_reqs:
        if len(other_reqs) == 1:
            parts.append(f"at least one {other_reqs[0]}")
        else:
            parts.append("at least one " + ", ".join(other_reqs[:-1]) + f", and {other_reqs[-1]}")

    if len(parts) == 1:
        return f"Password must include {parts[0]}."
    return f"Password must include {parts[0]} and {parts[1]}."


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower())
    return cleaned.strip("_") or "user"


def _agreement_name_for_filename(full_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", (full_name or "").strip())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.lower())
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    return normalized or "user"


def _build_terms_pdf_filename(full_name: str) -> str:
    return f"ai-listo-terms-agreement-{_agreement_name_for_filename(full_name)}.pdf"


def _build_terms_policy_pdf(
    full_name: str,
    agreed_at: datetime,
    email: str | None = None,
    include_signature_meta: bool = True,
) -> io.BytesIO:
    """Build a PDF copy of Terms and Privacy Policy with signer metadata."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Ai-Listo Terms of Service and Privacy Policy",
        author="Ai-Listo",
        subject="Terms Agreement",
        creator="Ai-Listo",
    )

    styles = getSampleStyleSheet()
    dark = colors.HexColor("#1e293b")
    muted = colors.HexColor("#64748b")
    brand = colors.HexColor("#3b82f6")

    title_style = ParagraphStyle(
        "TermsTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        textColor=dark,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "TermsSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=muted,
        spaceAfter=2,
    )
    heading_style = ParagraphStyle(
        "TermsHeading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=dark,
        spaceBefore=9,
        spaceAfter=3,
    )
    body_style = ParagraphStyle(
        "TermsBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=dark,
        leading=13,
        spaceAfter=3,
    )
    bullet_style = ParagraphStyle(
        "TermsBullet",
        parent=body_style,
        leftIndent=12,
        bulletIndent=2,
        spaceAfter=2,
    )

    story = []
    story.append(Paragraph("Ai-Listo", title_style))
    story.append(Paragraph("Terms of Service and Privacy Policy", subtitle_style))
    story.append(Paragraph(f"Version: {TERMS_VERSION}", subtitle_style))
    if include_signature_meta:
        story.append(Paragraph(f"Generated: {agreed_at.strftime('%B %d, %Y at %I:%M %p')}", subtitle_style))
        if full_name:
            agreed_by_line = f"Agreed by: {full_name}"
            if email:
                agreed_by_line += f" ({email})"
            story.append(Paragraph(agreed_by_line, subtitle_style))
    story.append(Spacer(1, 0.2 * cm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=brand))
    story.append(Spacer(1, 0.2 * cm))

    for section in TERMS_POLICY_SECTIONS:
        story.append(Paragraph(section["heading"], heading_style))
        for text in section.get("paragraphs", []):
            story.append(Paragraph(text, body_style))
        for item in section.get("bullets", []):
            story.append(Paragraph(item, bullet_style, bulletText="-"))
        for text in section.get("paragraphs_after", []):
            story.append(Paragraph(text, body_style))
        for item in section.get("bullets_after", []):
            story.append(Paragraph(item, bullet_style, bulletText="-"))

    doc.build(story)
    buf.seek(0)
    return buf


def login_required(f):
    """Redirect to /login if no user session."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        user = db.get_user_by_id(session["user_id"])
        if not user:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        if user.get("approval_status") != "approved":
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Account is not approved yet."}), 403
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    """Allow access only for authenticated users with admin role."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))

        user = db.get_user_by_id(session["user_id"])
        if not user:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))

        if user.get("approval_status") != "approved":
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Account is not approved yet."}), 403
            return redirect(url_for("login"))

        if user.get("role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Admin access required."}), 403
            return redirect(url_for("home"))

        return f(*args, **kwargs)
    return wrapped


def _normalize_admin_view_mode(mode: str | None) -> str:
    cleaned = str(mode or "").strip().lower()
    if cleaned in ADMIN_VIEW_MODE_ALLOWED:
        return cleaned
    return ADMIN_VIEW_MODE_ADMIN


def current_user() -> dict | None:
    uid = session.get("user_id")
    if uid is None:
        return None
    user = db.get_user_by_id(uid)
    if not user:
        return None

    role = user.get("role")
    effective_user = dict(user)
    effective_user["actual_role"] = role
    effective_user["admin_view_mode"] = ADMIN_VIEW_MODE_ADMIN
    effective_user["is_admin_teacher_mode"] = False
    effective_user["role_label"] = role

    if role == "admin":
        mode = _normalize_admin_view_mode(session.get(ADMIN_VIEW_MODE_SESSION_KEY))
        session[ADMIN_VIEW_MODE_SESSION_KEY] = mode
        effective_user["admin_view_mode"] = mode

        if mode == ADMIN_VIEW_MODE_TEACHER:
            effective_user["role"] = "teacher"
            effective_user["is_admin_teacher_mode"] = True
            effective_user["role_label"] = "teacher (admin view)"
        else:
            effective_user["role"] = "admin"
            effective_user["role_label"] = "admin"
    else:
        # Ensure mode flags from a prior admin login do not leak across users.
        session.pop(ADMIN_VIEW_MODE_SESSION_KEY, None)

    return effective_user


@app.context_processor
def inject_admin_pending_request_count():
    pending_request_count = 0
    admin_view_mode = ADMIN_VIEW_MODE_ADMIN
    is_admin_teacher_mode = False
    uid = session.get("user_id")
    if not uid:
        return {
            "admin_pending_request_count": pending_request_count,
            "admin_view_mode": admin_view_mode,
            "is_admin_teacher_mode": is_admin_teacher_mode,
        }

    user = db.get_user_by_id(uid)
    if not user:
        return {
            "admin_pending_request_count": pending_request_count,
            "admin_view_mode": admin_view_mode,
            "is_admin_teacher_mode": is_admin_teacher_mode,
        }

    if user.get("role") == "admin" and user.get("approval_status") == "approved":
        admin_view_mode = _normalize_admin_view_mode(session.get(ADMIN_VIEW_MODE_SESSION_KEY))
        is_admin_teacher_mode = admin_view_mode == ADMIN_VIEW_MODE_TEACHER
        if not is_admin_teacher_mode:
            pending_request_count = db.count_pending_users()
    else:
        session.pop(ADMIN_VIEW_MODE_SESSION_KEY, None)

    return {
        "admin_pending_request_count": pending_request_count,
        "admin_view_mode": admin_view_mode,
        "is_admin_teacher_mode": is_admin_teacher_mode,
    }


def _safe_user_profile_payload(user_obj: dict) -> dict:
    return {
        "id": user_obj.get("id"),
        "first_name": user_obj.get("first_name"),
        "last_name": user_obj.get("last_name"),
        "email": user_obj.get("email"),
        "avatar_url": user_obj.get("avatar_url"),
    }


def _supabase_public_headers(anon_key: str) -> dict:
    return {
        "apikey": anon_key,
        "Content-Type": "application/json",
    }


def _humanize_otp_send_error(raw_error: str) -> str:
    clean = (raw_error or "").strip()
    lowered = clean.lower()
    if "error sending magic link email" in lowered:
        return (
            "Supabase could not send the OTP email via SMTP. "
            "Check Supabase Auth Email settings (SMTP host, port, username, app password, and sender email)."
        )
    return clean or "Could not send OTP email."


def _send_login_otp_email(to_email: str) -> tuple[bool, str | None]:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not supabase_url or not supabase_anon_key:
        logging.error("OTP email not sent: SUPABASE_URL/SUPABASE_ANON_KEY is not configured")
        return False, "Supabase Auth is not configured."

    try:
        resp = requests.post(
            f"{supabase_url}/auth/v1/otp",
            json={"email": to_email, "create_user": False},
            headers=_supabase_public_headers(supabase_anon_key),
            timeout=10,
        )
        if not resp.ok:
            err_msg = "Could not send OTP email."
            try:
                payload = resp.json() if resp.content else {}
                err_msg = payload.get("msg") or payload.get("error_description") or payload.get("error") or err_msg
            except ValueError:
                pass
            err_msg = _humanize_otp_send_error(err_msg)
            logging.error("Supabase OTP send failed for %s: %s %s", to_email, resp.status_code, resp.text)
            return False, err_msg
        return True, None
    except Exception as exc:
        logging.error("Supabase OTP send request failed for %s: %s", to_email, exc)
        return False, "Could not send OTP email."


def _verify_login_otp_email(email: str, otp: str) -> tuple[bool, str | None]:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not supabase_url or not supabase_anon_key:
        return False, "Supabase Auth is not configured."

    try:
        resp = requests.post(
            f"{supabase_url}/auth/v1/verify",
            json={"type": "email", "email": email, "token": otp},
            headers=_supabase_public_headers(supabase_anon_key),
            timeout=10,
        )
        if not resp.ok:
            err_msg = "Invalid or expired OTP code."
            try:
                payload = resp.json() if resp.content else {}
                err_msg = payload.get("msg") or payload.get("error_description") or payload.get("error") or err_msg
            except ValueError:
                pass
            logging.warning("Supabase OTP verify failed for %s: %s %s", email, resp.status_code, resp.text)
            return False, err_msg
        return True, None
    except Exception as exc:
        logging.error("Supabase OTP verify request failed for %s: %s", email, exc)
        return False, "Could not verify OTP code."


def _format_wait_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    if minutes and sec:
        return f"{minutes} minute(s) and {sec} second(s)"
    if minutes:
        return f"{minutes} minute(s)"
    return f"{sec} second(s)"


def _extract_retry_after_seconds(message: str) -> int | None:
    text = str(message or "")
    match = re.search(r"after\s+(\d+)\s+second", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _login_lockout_context() -> dict:
    now_ts = int(time.time())
    lock_state = session.get("login_otp_lock") or {}
    lock_until = int(lock_state.get("until", 0) or 0)
    if lock_until <= now_ts:
        if lock_until:
            session.pop("login_otp_lock", None)
        return {"lockout_message": "", "lockout_seconds": 0}

    wait_for = lock_until - now_ts
    msg = (
        "Too many incorrect OTP attempts. "
        f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
    )
    return {"lockout_message": msg, "lockout_seconds": wait_for}


def _render_login_page(**extra_context):
    context = _login_lockout_context()
    context.update(extra_context)
    return render_template("login.html", **context)


# ─── Auth Pages ──────────────────────────────────────────────────────

def create_supabase_auth_user(email: str, password: str):
    """Mirror a new user into Supabase auth.users via the Admin API.
    Requires SUPABASE_SERVICE_ROLE_KEY in .env.
    Failures are logged but do NOT block registration.
    """
    supabase_url      = os.environ.get("SUPABASE_URL", "")
    service_role_key  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        logging.warning("SUPABASE_SERVICE_ROLE_KEY not set — skipping auth.users sync for %s", email)
        return
    try:
        resp = requests.post(
            f"{supabase_url}/auth/v1/admin/users",
            json={"email": email, "password": password, "email_confirm": True},
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code == 422:
            # User already exists in auth.users — not an error
            return
        if not resp.ok:
            logging.error("Supabase admin create user error: %s %s", resp.status_code, resp.text)
    except Exception as exc:
        logging.error("Supabase admin create user request failed: %s", exc)


def _supabase_admin_headers(service_role_key: str) -> dict:
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }


def _find_supabase_auth_user_id_by_email(email: str) -> str | None:
    """Return auth.users UUID for the given email, if found."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        return None

    target = email.strip().lower()
    headers = _supabase_admin_headers(service_role_key)

    # Supabase Admin API is paginated; walk a few pages and match by email.
    page = 1
    per_page = 200
    while page <= 20:
        resp = requests.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": per_page},
            timeout=10,
        )
        if not resp.ok:
            logging.error("Supabase admin list users error: %s %s", resp.status_code, resp.text)
            return None

        payload = resp.json() if resp.content else {}
        users = payload.get("users", []) if isinstance(payload, dict) else payload
        if not isinstance(users, list):
            users = []

        for user_obj in users:
            user_email = str((user_obj or {}).get("email", "")).strip().lower()
            if user_email == target:
                return (user_obj or {}).get("id")

        if len(users) < per_page:
            break
        page += 1

    return None


def update_supabase_auth_email(old_email: str, new_email: str) -> tuple[bool, str | None]:
    """Update Supabase auth.users email; returns (success, error_message)."""
    old_clean = old_email.strip().lower()
    new_clean = new_email.strip().lower()
    if old_clean == new_clean:
        return True, None

    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        return False, "SUPABASE_SERVICE_ROLE_KEY is not configured."

    try:
        auth_user_id = _find_supabase_auth_user_id_by_email(old_clean)
        if not auth_user_id:
            # If old email is not found but new email already exists in auth.users,
            # treat it as already synced.
            existing_new_id = _find_supabase_auth_user_id_by_email(new_clean)
            if existing_new_id:
                return True, None
            return False, "Could not locate auth.users record for current email."

        resp = requests.put(
            f"{supabase_url}/auth/v1/admin/users/{auth_user_id}",
            json={"email": new_clean, "email_confirm": True},
            headers=_supabase_admin_headers(service_role_key),
            timeout=10,
        )
        if not resp.ok:
            logging.error("Supabase admin update email error: %s %s", resp.status_code, resp.text)
            return False, f"Supabase auth email update failed ({resp.status_code})."
        return True, None
    except Exception as exc:
        logging.error("Supabase admin update email request failed: %s", exc)
        return False, "Supabase auth email update request failed."


def ensure_supabase_auth_user(email: str) -> tuple[bool, str | None]:
    """Ensure a Supabase auth.users identity exists for the given email."""
    target_email = str(email or "").strip().lower()
    if not target_email:
        return False, "Email is required."

    if _find_supabase_auth_user_id_by_email(target_email):
        return True, None

    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        return False, "SUPABASE_SERVICE_ROLE_KEY is not configured."

    # Temporary bootstrap password; user signs in with local DB credentials.
    random_core = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
    bootstrap_password = f"Aa1!{random_core}"

    try:
        resp = requests.post(
            f"{supabase_url}/auth/v1/admin/users",
            json={"email": target_email, "password": bootstrap_password, "email_confirm": True},
            headers=_supabase_admin_headers(service_role_key),
            timeout=10,
        )
        if resp.status_code == 422:
            return True, None
        if not resp.ok:
            logging.error("Supabase admin ensure user error for %s: %s %s", target_email, resp.status_code, resp.text)
            return False, f"Supabase auth user ensure failed ({resp.status_code})."
        return True, None
    except Exception as exc:
        logging.error("Supabase admin ensure user request failed for %s: %s", target_email, exc)
        return False, "Supabase auth user ensure request failed."

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email:
            if is_ajax:
                return jsonify({"error": "Email is required.", "field": "email"}), 400
            flash("Email is required.", "error")
            return _render_login_page()

        if not password:
            if is_ajax:
                return jsonify({"error": "Password is required.", "field": "password"}), 400
            flash("Password is required.", "error")
            return _render_login_page()

        user = db.get_user_by_email(email)
        if user and db.verify_password(password, user["password"]):
            approval_status = user.get("approval_status", "approved")
            if approval_status == "pending":
                msg = "Wait for Admin approval before signing in."
                if is_ajax:
                    return jsonify({"error": msg, "code": "pending_approval"}), 403
                flash(msg, "error")
                return _render_login_page()

            if approval_status == "rejected":
                msg = "Your account request was rejected by the admin."
                if is_ajax:
                    return jsonify({"error": msg, "code": "account_rejected"}), 403
                flash(msg, "error")
                return _render_login_page()

            now_ts = int(time.time())

            if LOGIN_OTP_ENABLED:
                # Lock is scoped to the email currently trying to sign in on this browser session.
                lock_state = session.get("login_otp_lock") or {}
                lock_email = str(lock_state.get("email", "")).strip().lower()
                lock_until = int(lock_state.get("until", 0) or 0)
                user_email = str(user.get("email", "")).strip().lower()
                if lock_email == user_email and lock_until > now_ts:
                    wait_for = lock_until - now_ts
                    msg = (
                        "Too many incorrect OTP attempts. "
                        f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
                    )
                    if is_ajax:
                        return jsonify({"error": msg, "retry_after": wait_for, "code": "otp_locked"}), 429
                    flash(msg, "error")
                    return _render_login_page()

                if lock_email == user_email and lock_until <= now_ts:
                    session.pop("login_otp_lock", None)

            if not LOGIN_OTP_ENABLED:
                session.pop("pending_login", None)
                session["user_id"] = user["id"]
                session["login_marker"] = f"{user['id']}-{int(time.time())}"
                if user.get("role") == "admin":
                    session[ADMIN_VIEW_MODE_SESSION_KEY] = ADMIN_VIEW_MODE_ADMIN
                else:
                    session.pop(ADMIN_VIEW_MODE_SESSION_KEY, None)
                if is_ajax:
                    return jsonify({"success": True, "redirect": url_for("home")})
                return redirect(url_for("home"))

            session["pending_login"] = {
                "user_id": user["id"],
                "email": user.get("email", ""),
                "otp_sent_at": now_ts,
                "attempts": 0,
                "resend_window_seconds": LOGIN_OTP_RESEND_COOLDOWN_SECONDS,
                "resend_not_before": now_ts + LOGIN_OTP_RESEND_COOLDOWN_SECONDS,
            }

            sent, send_error = _send_login_otp_email(to_email=user.get("email", ""))
            if not sent:
                session.pop("pending_login", None)
                if is_ajax:
                    return jsonify({"error": send_error or "Unable to send OTP email. Please try again."}), 503
                flash(send_error or "Unable to send OTP email. Please try again.", "error")
                return _render_login_page()

            # Use the post-send timestamp so cooldown starts when OTP dispatch completes.
            otp_sent_at = int(time.time())
            pending_login = session.get("pending_login") or {}
            pending_login["otp_sent_at"] = otp_sent_at
            resend_window_seconds = int(
                pending_login.get("resend_window_seconds", LOGIN_OTP_RESEND_COOLDOWN_SECONDS) or 0
            )
            resend_window_seconds = max(LOGIN_OTP_RESEND_COOLDOWN_SECONDS, resend_window_seconds)
            pending_login["resend_window_seconds"] = resend_window_seconds
            pending_login["resend_not_before"] = otp_sent_at + resend_window_seconds
            session["pending_login"] = pending_login

            if is_ajax:
                return jsonify(
                    {
                        "otp_required": True,
                        "message": "An OTP has been sent to your email. Please check your inbox or spam folder and enter the code.",
                        "otp_expires_in": LOGIN_OTP_TTL_SECONDS,
                        "resend_available_in": resend_window_seconds,
                    }
                )
            flash("An OTP has been sent to your email. Please check your inbox or spam folder and enter the code.", "success")
            return _render_login_page()

        session.pop("pending_login", None)
        if is_ajax:
            return jsonify({"error": "Invalid email or password."}), 401
        flash("Invalid email or password.", "error")

    return _render_login_page()


@app.route("/verify-login-otp", methods=["POST"])
def verify_login_otp():
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    otp = request.form.get("otp", "").strip()

    if not otp:
        if is_ajax:
            return jsonify({"error": "OTP is required.", "field": "otp"}), 400
        flash("OTP is required.", "error")
        return _render_login_page()

    if not otp.isdigit() or len(otp) < 6 or len(otp) > 12:
        if is_ajax:
            return jsonify({"error": "OTP must be a numeric code with 6 to 12 digits.", "field": "otp"}), 400
        flash("OTP must be a numeric code with 6 to 12 digits.", "error")
        return _render_login_page()

    pending_login = session.get("pending_login") or {}
    if not pending_login:
        msg = "Your sign-in session has expired. Please sign in again."
        if is_ajax:
            return jsonify({"error": msg}), 400
        flash(msg, "error")
        return _render_login_page()

    now_ts = int(time.time())
    otp_sent_at = int(pending_login.get("otp_sent_at", 0))
    pending_email = str(pending_login.get("email", "")).strip().lower()

    lock_state = session.get("login_otp_lock") or {}
    lock_email = str(lock_state.get("email", "")).strip().lower()
    lock_until = int(lock_state.get("until", 0) or 0)
    if lock_email == pending_email and lock_until > now_ts:
        wait_for = lock_until - now_ts
        msg = (
            "Too many incorrect OTP attempts. "
            f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
        )
        session.pop("pending_login", None)
        if is_ajax:
            return jsonify({"error": msg, "retry_after": wait_for, "code": "otp_locked"}), 429
        flash(msg, "error")
        return _render_login_page()

    if lock_email == pending_email and lock_until <= now_ts:
        session.pop("login_otp_lock", None)

    # OTP is valid only within the configured time window.
    if now_ts - otp_sent_at > LOGIN_OTP_TTL_SECONDS:
        session.pop("pending_login", None)
        msg = "OTP has expired. Please sign in again to get a new OTP."
        if is_ajax:
            return jsonify({"error": msg, "field": "otp"}), 400
        flash(msg, "error")
        return _render_login_page()

    attempts = int(pending_login.get("attempts", 0))
    if attempts >= LOGIN_OTP_MAX_ATTEMPTS:
        lock_until = now_ts + LOGIN_OTP_LOCKOUT_SECONDS
        session["login_otp_lock"] = {"email": pending_email, "until": lock_until}
        session.pop("pending_login", None)
        wait_for = lock_until - now_ts
        msg = (
            "Too many incorrect OTP attempts. "
            f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
        )
        if is_ajax:
            return jsonify({"error": msg, "retry_after": wait_for, "code": "otp_locked"}), 429
        flash(msg, "error")
        return _render_login_page()

    verify_ok, verify_error = _verify_login_otp_email(
        email=str(pending_login.get("email", "")),
        otp=otp,
    )
    if not verify_ok:
        pending_login["attempts"] = attempts + 1
        session["pending_login"] = pending_login

        if pending_login["attempts"] >= LOGIN_OTP_MAX_ATTEMPTS:
            lock_until = now_ts + LOGIN_OTP_LOCKOUT_SECONDS
            session["login_otp_lock"] = {"email": pending_email, "until": lock_until}
            session.pop("pending_login", None)
            wait_for = lock_until - now_ts
            msg = (
                "Too many incorrect OTP attempts. "
                f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
            )
            if is_ajax:
                return jsonify({"error": msg, "retry_after": wait_for, "code": "otp_locked"}), 429
            flash(msg, "error")
            return _render_login_page()

        remaining = max(0, LOGIN_OTP_MAX_ATTEMPTS - pending_login["attempts"])
        msg = verify_error or "Invalid OTP code."
        if remaining:
            msg = f"{msg} {remaining} attempt(s) left."
        if is_ajax:
            return jsonify({"error": msg, "field": "otp"}), 401
        flash(msg, "error")
        return _render_login_page()

    user_id = pending_login.get("user_id")
    user = db.get_user_by_id(user_id) if user_id else None
    if not user or user.get("approval_status") != "approved":
        session.pop("pending_login", None)
        msg = "Your account is not available for login."
        if is_ajax:
            return jsonify({"error": msg}), 403
        flash(msg, "error")
        return _render_login_page()

    session.pop("pending_login", None)
    session["user_id"] = user["id"]
    session["login_marker"] = f"{user['id']}-{int(time.time())}"
    if user.get("role") == "admin":
        session[ADMIN_VIEW_MODE_SESSION_KEY] = ADMIN_VIEW_MODE_ADMIN
    else:
        session.pop(ADMIN_VIEW_MODE_SESSION_KEY, None)
    if is_ajax:
        return jsonify({"success": True, "redirect": url_for("home")})
    return redirect(url_for("home"))


@app.route("/resend-login-otp", methods=["POST"])
def resend_login_otp():
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    pending_login = session.get("pending_login") or {}
    if not pending_login:
        msg = "Your sign-in session has expired. Please sign in again."
        if is_ajax:
            return jsonify({"error": msg}), 400
        flash(msg, "error")
        return _render_login_page()

    now_ts = int(time.time())
    pending_email = str(pending_login.get("email", "")).strip().lower()
    otp_sent_at = int(pending_login.get("otp_sent_at", 0) or 0)
    resend_window_seconds = int(
        pending_login.get("resend_window_seconds", LOGIN_OTP_RESEND_COOLDOWN_SECONDS) or 0
    )
    resend_window_seconds = max(LOGIN_OTP_RESEND_COOLDOWN_SECONDS, resend_window_seconds)
    resend_not_before = int(
        pending_login.get("resend_not_before", otp_sent_at + resend_window_seconds) or 0
    )

    lock_state = session.get("login_otp_lock") or {}
    lock_email = str(lock_state.get("email", "")).strip().lower()
    lock_until = int(lock_state.get("until", 0) or 0)
    if lock_email == pending_email and lock_until > now_ts:
        wait_for = lock_until - now_ts
        msg = (
            "Too many incorrect OTP attempts. "
            f"You are temporarily timed out. Please try to sign in again after {_format_wait_time(wait_for)}."
        )
        session.pop("pending_login", None)
        if is_ajax:
            return jsonify({"error": msg, "retry_after": wait_for, "code": "otp_locked"}), 429
        flash(msg, "error")
        return _render_login_page()

    if now_ts - otp_sent_at > LOGIN_OTP_TTL_SECONDS:
        session.pop("pending_login", None)
        msg = "OTP has expired. Please sign in again to get a new OTP."
        if is_ajax:
            return jsonify({"error": msg}), 400
        flash(msg, "error")
        return _render_login_page()

    if now_ts < resend_not_before:
        retry_after = resend_not_before - now_ts
        msg = f"Please wait {_format_wait_time(retry_after)} before requesting another OTP."
        if is_ajax:
            return jsonify({"error": msg, "retry_after": retry_after, "code": "resend_cooldown"}), 429
        flash(msg, "error")
        return _render_login_page()

    sent, send_error = _send_login_otp_email(to_email=str(pending_login.get("email", "")))
    if not sent:
        provider_retry_after = _extract_retry_after_seconds(send_error or "")
        if is_ajax and provider_retry_after is not None:
            elapsed_since_last_send = max(0, now_ts - otp_sent_at)
            learned_window = max(
                resend_window_seconds,
                elapsed_since_last_send + provider_retry_after,
            )
            pending_login["resend_window_seconds"] = learned_window
            pending_login["resend_not_before"] = now_ts + provider_retry_after
            session["pending_login"] = pending_login
            return jsonify(
                {
                    "error": send_error or "Please wait before requesting another OTP.",
                    "retry_after": provider_retry_after,
                    "code": "resend_cooldown",
                }
            ), 429
        if is_ajax:
            return jsonify({"error": send_error or "Unable to send OTP email. Please try again."}), 503
        flash(send_error or "Unable to send OTP email. Please try again.", "error")
        return _render_login_page()

    sent_at = int(time.time())
    pending_login["otp_sent_at"] = sent_at
    pending_login["resend_window_seconds"] = resend_window_seconds
    pending_login["resend_not_before"] = sent_at + resend_window_seconds
    session["pending_login"] = pending_login
    msg = "A new OTP has been sent to your email."
    if is_ajax:
        return jsonify(
            {
                "success": True,
                "message": msg,
                "resend_available_in": resend_window_seconds,
            }
        )
    flash(msg, "success")
    return _render_login_page()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email      = request.form.get("email", "").strip().lower()
        password   = request.form.get("password", "")
        confirm    = request.form.get("confirmPassword", "")
        first_name = request.form.get("firstName", "").strip()
        last_name  = request.form.get("lastName", "").strip()

        # Validation
        errors = {}
        if not first_name:
            errors["firstName"] = "First name is required."
        if not last_name:
            errors["lastName"] = "Last name is required."
        if not email:
            errors["email"] = "Email is required."
        elif "@" not in email:
            errors["email"] = "Please enter a valid email address."
        if not password:
            errors["password"] = "Password is required."
        else:
            unmet = _password_policy_unmet(password)
            if unmet:
                errors["password"] = _password_policy_message(unmet)
        if password and password != confirm:
            errors["confirmPassword"] = "Passwords do not match."

        if errors:
            if is_ajax:
                return jsonify({"errors": errors}), 400
            flash(list(errors.values())[0], "error")
            return render_template("register.html")

        if db.get_user_by_email(email):
            if is_ajax:
                return jsonify({"errors": {"email": "An account with this email already exists."}}), 409
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        created_user = None
        try:
            created_user = db.create_user(
                email,
                password,
                first_name,
                last_name,
                approval_status="pending",
            )

            agreed_at = datetime.now()
            full_name = f"{first_name} {last_name}".strip()
            terms_filename = _build_terms_pdf_filename(full_name)
            terms_pdf = _build_terms_policy_pdf(full_name, agreed_at, email=email)

            db.create_user_terms_agreement_proof(
                user_id=created_user["id"],
                full_name=full_name,
                agreed_at=agreed_at,
                file_name=terms_filename,
                pdf_data=terms_pdf.getvalue(),
                terms_version=TERMS_VERSION,
            )
        except Exception as exc:
            logging.exception("Failed to store terms agreement proof for %s", email)
            if created_user and created_user.get("id"):
                try:
                    db.delete_user_by_id(created_user["id"])
                except Exception:
                    logging.exception("Failed to rollback user %s after proof-save error", created_user["id"])

            if is_ajax:
                return jsonify({"errors": {"email": "Could not complete registration. Please try again."}}), 500
            flash("Could not complete registration. Please try again.", "error")
            return render_template("register.html")

        create_supabase_auth_user(email, password)
        pending_msg = "Account created. Wait for Admin approval before signing in."
        if is_ajax:
            return jsonify({"success": True, "redirect": url_for("login"), "message": pending_msg})
        flash(pending_msg, "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/terms/download-pdf", methods=["GET"])
def download_terms_pdf():
    full_name = request.args.get("name", "Prospective User").strip() or "Prospective User"
    generated_at = datetime.now()
    filename = _build_terms_pdf_filename(full_name)
    buf = _build_terms_policy_pdf(
        full_name,
        generated_at,
        include_signature_meta=False,
    )
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    prefill_email = ""
    from_profile = request.args.get("from", "").strip().lower() == "profile"
    if from_profile:
        user = current_user()
        if user:
            prefill_email = str(user.get("email", "")).strip()

    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email = request.form.get("email", "").strip().lower()

        if not email:
            if is_ajax:
                return jsonify({"error": "Email is required.", "field": "email"}), 400
            return render_template("forgot-password.html")

        if "@" not in email:
            if is_ajax:
                return jsonify({"error": "Please enter a valid email address.", "field": "email"}), 400
            return render_template("forgot-password.html")

        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        app_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
        redirect_to = f"{app_url}/reset-password"

        # Auto-heal auth identity drift: local user exists but auth.users entry is missing.
        local_user = db.get_user_by_email(email)
        if local_user:
            ensured, ensure_err = ensure_supabase_auth_user(email)
            if not ensured:
                logging.warning("Could not ensure Supabase auth user for %s: %s", email, ensure_err)

        if supabase_url and supabase_anon_key:
            try:
                resp = requests.post(
                    f"{supabase_url}/auth/v1/recover",
                    json={"email": email},
                    params={"redirect_to": redirect_to},
                    headers={"apikey": supabase_anon_key, "Content-Type": "application/json"},
                    timeout=10,
                )
                if not resp.ok:
                    logging.error("Supabase recover error: %s %s", resp.status_code, resp.text)
            except Exception as exc:
                logging.error("Supabase recover request failed: %s", exc)
        else:
            logging.warning("SUPABASE_URL or SUPABASE_ANON_KEY not set — reset email not sent for %s", email)

        # Always return success to avoid revealing which emails are registered
        if is_ajax:
            return jsonify({"success": True})
        return render_template("forgot-password.html", prefill_email=prefill_email)

    return render_template("forgot-password.html", prefill_email=prefill_email)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        access_token = request.form.get("access_token", "").strip()
        new_password = request.form.get("password", "")
        confirm = request.form.get("confirmPassword", "")

        if not access_token:
            if is_ajax:
                return jsonify({"error": "Invalid or missing reset token."}), 400
            return render_template("reset-password.html")

        # Validate the Supabase access token and retrieve the user's email
        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        try:
            user_resp = requests.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "apikey": supabase_anon_key,
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=10,
            )
        except Exception as exc:
            logging.error("Supabase user lookup failed: %s", exc)
            if is_ajax:
                return jsonify({"error": "Could not verify reset token. Please try again."}), 503
            return render_template("reset-password.html")

        if user_resp.status_code != 200:
            if is_ajax:
                return jsonify({"error": "This reset link is invalid or has expired."}), 400
            return render_template("reset-password.html")

        email = user_resp.json().get("email", "")

        if not new_password:
            if is_ajax:
                return jsonify({"error": "Password is required.", "field": "password"}), 400
            return render_template("reset-password.html")

        unmet = _password_policy_unmet(new_password)
        if unmet:
            if is_ajax:
                return jsonify({"error": _password_policy_message(unmet), "field": "password"}), 400
            return render_template("reset-password.html")

        if new_password != confirm:
            if is_ajax:
                return jsonify({"error": "Passwords do not match.", "field": "confirmPassword"}), 400
            return render_template("reset-password.html")

        user = db.get_user_by_email(email)
        if not user:
            if is_ajax:
                return jsonify({"error": "No account found for this email."}), 404
            return render_template("reset-password.html")

        if db.verify_password(new_password, user["password"]):
            if is_ajax:
                return jsonify({"error": "New password must be different from your current password.", "field": "password"}), 400
            return render_template("reset-password.html")

        db.update_user_password(user["id"], new_password)

        # Invalidate any existing authenticated browser session immediately.
        session.clear()

        if is_ajax:
            return jsonify({"success": True, "redirect": url_for("login")})
        return redirect(url_for("login"))

    return render_template("reset-password.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Main Pages ──────────────────────────────────────────────────────

@app.route("/")
@login_required
def home():
    user = current_user()
    if user.get("role") == "admin":
        stats = db.get_dashboard_stats_admin()
    else:
        stats = db.get_dashboard_stats(user["id"])
    subjects = db.get_subjects(user["id"])
    return render_template("index.html", user=user, stats=stats, subjects=subjects)


@app.route("/live-session")
@login_required
def live_session():
    user = current_user()
    subjects = db.get_subjects(user["id"])
    return render_template("live-session.html", user=user, subjects=subjects)


_YOLO_SERVER = os.environ.get("YOLO_SERVER_URL", "http://4.216.188.104:5000").rstrip("/")
_YOLO_HEALTH_PATHS = ["/health", "/"]
_YOLO_CONNECT_TIMEOUT = max(0.5, float(os.environ.get("YOLO_CONNECT_TIMEOUT", "2.0")))
_YOLO_READ_TIMEOUT = max(1.0, float(os.environ.get("YOLO_READ_TIMEOUT", "4.5")))
_YOLO_HTTP = requests.Session()
_yolo_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
_YOLO_HTTP.mount("http://", _yolo_adapter)
_YOLO_HTTP.mount("https://", _yolo_adapter)


def _find_yolo_health_path():
    """Return the first reachable health endpoint path, or None."""
    for path in _YOLO_HEALTH_PATHS:
        try:
            r = _YOLO_HTTP.get(
                f"{_YOLO_SERVER}{path}",
                timeout=(_YOLO_CONNECT_TIMEOUT, 2),
            )
            if r.status_code == 200:
                return path
            r.close()
        except requests.exceptions.RequestException:
            continue
    return None


@app.route("/api/yolo-health")
@login_required
def yolo_health():
    """Check YOLO server reachability and report diagnostics."""
    tried = {}
    for path in _YOLO_HEALTH_PATHS:
        try:
            r = _YOLO_HTTP.get(
                f"{_YOLO_SERVER}{path}",
                timeout=(_YOLO_CONNECT_TIMEOUT, 2),
            )
            ct = r.headers.get("Content-Type", "")
            payload = None
            if "application/json" in ct.lower():
                try:
                    payload = r.json()
                except ValueError:
                    payload = None
            tried[path] = {
                "status": r.status_code,
                "content_type": ct,
                "payload": payload,
            }
            r.close()
        except requests.exceptions.RequestException as exc:
            tried[path] = {"status": 0, "error": str(exc)[:120]}

    health_path = _find_yolo_health_path()
    if health_path:
        return jsonify({"reachable": True, "endpoint": health_path, "tried": tried})
    return jsonify({"reachable": False, "error": f"No reachable health endpoint on {_YOLO_SERVER}", "tried": tried}), 502


@app.route("/api/yolo-infer", methods=["POST"])
@login_required
def yolo_infer():
    """Forward browser camera frames to YOLO server and return detections."""
    payload = request.get_json(silent=True) or {}
    frame = payload.get("frame") or payload.get("image")
    session_id = payload.get("session_id") or payload.get("sessionId")
    if not frame:
        logging.warning("YOLO infer rejected: missing frame payload")
        return jsonify({"error": "Missing frame payload"}), 400

    try:
        request_payload = {"frame": frame}
        if session_id:
            request_payload["session_id"] = session_id
        r = _YOLO_HTTP.post(
            f"{_YOLO_SERVER}/infer",
            json=request_payload,
            timeout=(_YOLO_CONNECT_TIMEOUT, _YOLO_READ_TIMEOUT),
        )
    except requests.exceptions.RequestException as exc:
        logging.error("YOLO infer proxy error: %s", exc)
        return jsonify({"error": "YOLO server unavailable"}), 502

    try:
        data = r.json()
    except ValueError:
        logging.error("YOLO infer upstream returned non-JSON response with status %s", r.status_code)
        data = {"error": "Invalid response from YOLO server"}

    if app.logger.isEnabledFor(logging.DEBUG):
        logging.debug(
            "YOLO infer upstream response: status=%s keys=%s",
            r.status_code,
            sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )

    return jsonify(data), r.status_code


@app.route("/classes")
@login_required
def classes():
    import datetime as _dt
    user = current_user()
    subjects = db.get_subjects(user["id"])

    def _fmt_time(t):
        if t is None:
            return None
        if isinstance(t, _dt.time):
            return t.strftime('%H:%M')
        if isinstance(t, _dt.timedelta):
            total = int(t.total_seconds())
            h, rem = divmod(total, 3600)
            m = rem // 60
            return f'{h:02d}:{m:02d}'
        return str(t)

    groups_map = {}
    groups_order = []
    today_schedule_map = {}
    today_schedule_order = []
    for subj in subjects:
        key = (subj['name'], subj['course_code'])
        if key not in groups_map:
            groups_map[key] = {
                'name': subj['name'],
                'course_code': subj['course_code'],
                'sections': [],
            }
            groups_order.append(key)
        if subj.get('section'):
            section_schedules = [
                {**sch,
                 'start_time': _fmt_time(sch.get('start_time')),
                 'end_time': _fmt_time(sch.get('end_time'))}
                for sch in subj.get('schedules', [])
            ]
            groups_map[key]['sections'].append({
                'id': subj['id'],
                'section': subj['section'],
                'schedules': section_schedules,
            })

            today_key = (subj['course_code'], subj['section'])
            if today_key not in today_schedule_map:
                today_schedule_map[today_key] = {
                    'course_code': subj['course_code'],
                    'section': subj['section'],
                    'schedules': [],
                }
                today_schedule_order.append(today_key)
            today_schedule_map[today_key]['schedules'].extend(section_schedules)

    subject_groups = [groups_map[k] for k in groups_order]
    today_schedule_groups = [today_schedule_map[k] for k in today_schedule_order]
    return render_template(
        "classes.html",
        user=user,
        subjects=subjects,
        subject_groups=subject_groups,
        today_schedule_groups=today_schedule_groups,
    )


@app.route("/teachers")
@login_required
def teachers():
    import datetime as _dt
    user = current_user()

    def _can_view_teacher_panel(candidate):
        if not candidate:
            return False
        if candidate.get("role") == "admin":
            return True
        return candidate.get("role") == "teacher" and candidate.get("approval_status") == "approved"
    
    # Only admins can access this page
    if user.get("role") != "admin":
        flash("Access denied. Only admins can view teachers.", "error")
        return redirect(url_for("classes"))
    
    # Get all approved teachers and admins (admins can also have teaching schedules).
    all_teachers = db.get_approved_teachers_and_admins()
    
    # Get subject data for a specific teacher if requested
    selected_teacher = None
    subject_groups = []
    today_schedule_groups = []
    
    teacher_id_param = request.args.get("teacher_id", type=int)
    if teacher_id_param:
        # Verify teacher exists and is approved
        candidate = db.get_user_by_id(teacher_id_param)
        if _can_view_teacher_panel(candidate):
            selected_teacher = candidate
            subjects = db.get_subjects(teacher_id_param)
            
            # Process subjects into groups (same logic as /classes route)
            def _fmt_time(t):
                if t is None:
                    return None
                if isinstance(t, _dt.time):
                    parsed_time = t
                elif isinstance(t, _dt.timedelta):
                    total = int(t.total_seconds())
                    h, rem = divmod(total, 3600)
                    m = rem // 60
                    parsed_time = _dt.time(hour=h % 24, minute=m)
                elif isinstance(t, str):
                    raw = t.strip()
                    parsed_time = None
                    for fmt in ('%H:%M:%S', '%H:%M', '%I:%M %p', '%I:%M%p'):
                        try:
                            parsed_time = _dt.datetime.strptime(raw, fmt).time()
                            break
                        except ValueError:
                            continue
                    if parsed_time is None:
                        return raw
                else:
                    return str(t)

                return parsed_time.strftime('%I:%M %p').lstrip('0')

            groups_map = {}
            groups_order = []
            today_schedule_map = {}
            today_schedule_order = []
            
            for subj in subjects:
                key = (subj['name'], subj['course_code'])
                if key not in groups_map:
                    groups_map[key] = {
                        'name': subj['name'],
                        'course_code': subj['course_code'],
                        'sections': [],
                    }
                    groups_order.append(key)
                if subj.get('section'):
                    section_schedules = [
                        {**sch,
                         'start_time': _fmt_time(sch.get('start_time')),
                         'end_time': _fmt_time(sch.get('end_time'))}
                        for sch in subj.get('schedules', [])
                    ]
                    groups_map[key]['sections'].append({
                        'id': subj['id'],
                        'section': subj['section'],
                        'schedules': section_schedules,
                    })

                    today_key = (subj['course_code'], subj['section'])
                    if today_key not in today_schedule_map:
                        today_schedule_map[today_key] = {
                            'course_code': subj['course_code'],
                            'section': subj['section'],
                            'schedules': [],
                        }
                        today_schedule_order.append(today_key)
                    today_schedule_map[today_key]['schedules'].extend(section_schedules)

            subject_groups = [groups_map[k] for k in groups_order]
            today_schedule_groups = [today_schedule_map[k] for k in today_schedule_order]
    
    return render_template(
        "teachers.html",
        user=user,
        all_teachers=all_teachers,
        selected_teacher=selected_teacher,
        subject_groups=subject_groups,
        today_schedule_groups=today_schedule_groups,
    )


def _build_subject_filter_context(subjects: list[dict]) -> tuple[list[dict], list[str], dict[str, list[str]]]:
    """Build subject and section filter options from a subjects collection."""
    seen_course_codes = set()
    subject_filters = []
    subject_section_map = {}

    for subj in subjects:
        code = str(subj.get("course_code", "")).strip()
        name = str(subj.get("name", "")).strip()
        section = str(subj.get("section", "")).strip()
        if not code:
            continue

        if code not in seen_course_codes:
            seen_course_codes.add(code)
            subject_filters.append({"course_code": code, "name": name})

        subject_section_map.setdefault(code, [])
        if section and section not in subject_section_map[code]:
            subject_section_map[code].append(section)

    subject_filters.sort(key=lambda s: s["course_code"])
    for sections in subject_section_map.values():
        sections.sort()

    section_filters = sorted(
        {
            section
            for sections in subject_section_map.values()
            for section in sections
        }
    )

    return subject_filters, section_filters, subject_section_map


@app.route("/history")
@login_required
def history():
    user = current_user()

    # Admin can browse any teacher's history via ?teacher_id=X
    teachers = []
    selected_teacher = None
    effective_teacher_id = user["id"]

    if user.get("role") == "admin":
        effective_teacher_id = None
        teachers = db.get_approved_teachers()
        teacher_arg_present = "teacher_id" in request.args
        if teacher_arg_present:
            # Accept explicit teacher selection/clear from query, then redirect to a clean URL.
            raw_teacher_value = (request.args.get("teacher_id") or "").strip()
            if not raw_teacher_value:
                session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)
            else:
                teacher_id_param = request.args.get("teacher_id", type=int)
                if teacher_id_param:
                    candidate = db.get_user_by_id(teacher_id_param)
                    if candidate and candidate.get("role") == "teacher" and candidate.get("approval_status") == "approved":
                        session[ADMIN_HISTORY_TEACHER_SESSION_KEY] = teacher_id_param
                    else:
                        session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)
                else:
                    session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)

            clean_query = {}
            year_param = request.args.get("year")
            month_num_param = request.args.get("month_num")
            if year_param:
                clean_query["year"] = year_param
            if month_num_param:
                clean_query["month_num"] = month_num_param
            return redirect(url_for("history", **clean_query))

        selected_teacher_id = session.get(ADMIN_HISTORY_TEACHER_SESSION_KEY)
        if selected_teacher_id:
            candidate = db.get_user_by_id(selected_teacher_id)
            if candidate and candidate.get("role") == "teacher" and candidate.get("approval_status") == "approved":
                selected_teacher = candidate
                effective_teacher_id = selected_teacher_id
            else:
                session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)

    now = datetime.now()
    selected_year = request.args.get("year", type=int) or now.year
    selected_month_num = request.args.get("month_num", type=int) or now.month

    # Guard against invalid date filters from query params.
    if selected_month_num < 1 or selected_month_num > 12:
        selected_month_num = now.month
    if selected_year < 1970 or selected_year > 2100:
        selected_year = now.year

    selected_month = f"{selected_year:04d}-{selected_month_num:02d}"
    sessions_list = db.get_sessions_for_month(effective_teacher_id, selected_year, selected_month_num)
    stats = db.get_history_summary_stats(effective_teacher_id)
    subjects = db.get_history_subjects(effective_teacher_id)
    month_values = db.get_session_month_options(effective_teacher_id)

    years = set()
    for value in month_values:
        try:
            years.add(datetime.strptime(value, "%Y-%m").year)
        except ValueError:
            continue
    current_year = datetime.now().year
    years.add(current_year)
    years.add(selected_year)

    min_year = min(min(years), current_year - 5)
    max_year = max(max(years), current_year)
    year_options = list(range(max_year, min_year - 1, -1))
    month_name_options = [
        {"value": i, "label": datetime(2000, i, 1).strftime("%B")}
        for i in range(1, 13)
    ]

    seen_course_codes = set()
    subject_filters = []
    subject_section_map = {}  # { course_code: [section, ...] }
    section_filters = sorted({str(s.get("section", "")).strip() for s in subjects if s.get("section")})

    for subj in subjects:
        code = str(subj.get("course_code", "")).strip()
        name = str(subj.get("name", "")).strip()
        section = str(subj.get("section", "")).strip()
        if not code:
            continue
        if code not in seen_course_codes:
            seen_course_codes.add(code)
            subject_filters.append({"course_code": code, "name": name})
        if code not in subject_section_map:
            subject_section_map[code] = []
        if section and section not in subject_section_map[code]:
            subject_section_map[code].append(section)

    subject_filters.sort(key=lambda s: s["course_code"])

    return render_template(
        "history.html",
        user=user,
        sessions=sessions_list,
        stats=stats,
        subjects=subjects,
        subject_filters=subject_filters,
        section_filters=section_filters,
        teachers=teachers,
        selected_teacher=selected_teacher,
        subject_section_map=subject_section_map,
        year_options=year_options,
        month_name_options=month_name_options,
        selected_year=selected_year,
        selected_month_num=selected_month_num,
        selected_month=selected_month,
    )


@app.route("/reports")
@login_required
def reports():
    user = current_user()

    # For admins, allow selecting approved teachers and admins.
    teachers = []
    if user.get("role") == "admin":
        teachers = db.get_approved_teachers_and_admins()

    if user.get("role") == "admin":
        subjects = db.get_report_subjects(None)
    else:
        subjects = db.get_report_subjects(user["id"])

    login_marker = session.get("login_marker")
    if not login_marker:
        login_marker = f"{user['id']}-{int(time.time())}"
        session["login_marker"] = login_marker

    subject_filters, section_filters, subject_section_map = _build_subject_filter_context(subjects)

    report_subject_filters_by_teacher = {"": subject_filters}
    report_subject_section_map_by_teacher = {"": subject_section_map}

    if user.get("role") == "admin":
        for teacher in teachers:
            teacher_id = teacher.get("id")
            if not teacher_id:
                continue
            teacher_subjects = db.get_report_subjects(teacher_id)
            teacher_filters, _, teacher_section_map = _build_subject_filter_context(teacher_subjects)
            teacher_key = str(teacher_id)
            report_subject_filters_by_teacher[teacher_key] = teacher_filters
            report_subject_section_map_by_teacher[teacher_key] = teacher_section_map

    return render_template(
        "reports.html",
        user=user,
        subject_filters=subject_filters,
        section_filters=section_filters,
        subject_section_map=subject_section_map,
        report_subject_filters_by_teacher=report_subject_filters_by_teacher,
        report_subject_section_map_by_teacher=report_subject_section_map_by_teacher,
        report_login_marker=login_marker,
        teachers=teachers,
    )


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    return render_template("profile.html", user=user)


@app.route("/profile/view-mode", methods=["POST"])
@login_required
def profile_view_mode():
    uid = session.get("user_id")
    actual_user = db.get_user_by_id(uid) if uid else None
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.is_json
    )

    if not actual_user or actual_user.get("role") != "admin":
        if is_ajax:
            return jsonify({"error": "Only admins can change view mode."}), 403
        flash("Only admins can change view mode.", "error")
        return redirect(url_for("profile"))

    if request.is_json:
        data = request.get_json(silent=True) or {}
        requested_mode = data.get("mode")
        next_path = str(data.get("next") or "").strip()
    else:
        requested_mode = request.form.get("mode")
        next_path = str(request.form.get("next") or "").strip()

    requested_mode_clean = str(requested_mode or "").strip().lower()
    if requested_mode_clean not in ADMIN_VIEW_MODE_ALLOWED:
        if is_ajax:
            return jsonify({"error": "Invalid view mode."}), 400
        flash("Invalid view mode selected.", "error")
        return redirect(url_for("profile"))

    session[ADMIN_VIEW_MODE_SESSION_KEY] = requested_mode_clean

    if not next_path.startswith("/"):
        next_path = url_for("profile")

    if is_ajax:
        return jsonify(
            {
                "success": True,
                "mode": requested_mode_clean,
                "redirect": next_path,
            }
        )

    if requested_mode_clean == ADMIN_VIEW_MODE_TEACHER:
        flash("Switched to Teacher View. You can now use teacher pages.", "success")
    else:
        flash("Switched back to Admin View.", "success")
    return redirect(next_path)


@app.route("/settings")
@login_required
def settings():
    user = current_user()
    return render_template("settings.html", user=user)


@app.route("/about")
@login_required
def about():
    user = current_user()
    return render_template("about.html", user=user)


@app.route("/user-management")
@admin_required
def user_management():
    user = current_user()
    users = db.list_users()
    pending_users = db.get_pending_users()
    return render_template("user-management.html", user=user, users=users, pending_users=pending_users)


@app.route("/user-agreements")
@admin_required
def user_agreements():
    user = current_user()
    agreements = db.list_user_terms_agreements()
    return render_template("user-agreements.html", user=user, agreements=agreements)


@app.route("/admin/user-agreements/<int:proof_id>/download")
@admin_required
def admin_download_user_agreement(proof_id: int):
    proof = db.get_user_terms_agreement_proof(proof_id)
    if not proof:
        return jsonify({"error": "Agreement proof not found."}), 404

    pdf_data = proof.get("pdf_data")
    if not pdf_data:
        return jsonify({"error": "Agreement proof has no PDF data."}), 404

    download_filename = _build_terms_pdf_filename(proof.get("full_name") or "user")

    return send_file(
        io.BytesIO(bytes(pdf_data)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_filename,
    )


# ─── API Endpoints ───────────────────────────────────────────────────

@app.route("/api/profile", methods=["POST"])
@login_required
def api_update_profile():
    user = current_user()
    data = request.get_json(silent=True) or {}

    first_name = str(data.get("firstName", "")).strip()
    last_name = str(data.get("lastName", "")).strip()
    email = str(data.get("email", "")).strip().lower()

    if not first_name:
        return jsonify({"error": "First name is required.", "field": "firstName"}), 400
    if not last_name:
        return jsonify({"error": "Last name is required.", "field": "lastName"}), 400
    if not email:
        return jsonify({"error": "Email is required.", "field": "email"}), 400

    existing = db.get_user_by_email(email)
    if existing and existing["id"] != user["id"]:
        return jsonify({"error": "Email is already used by another account.", "field": "email"}), 409

    email_changed = email != str(user.get("email", "")).strip().lower()
    if email_changed:
        ok, sync_error = update_supabase_auth_email(user["email"], email)
        if not ok:
            return jsonify({
                "error": "Could not sync email to auth provider. " + (sync_error or "Please try again."),
                "field": "email",
            }), 503

    try:
        updated = db.update_user_profile(user["id"], first_name, last_name, email)
    except Exception as exc:
        logging.exception("Failed to update profile for user %s", user["id"])
        if email_changed:
            # Best-effort rollback of auth email when local DB update fails.
            rollback_ok, rollback_err = update_supabase_auth_email(email, user["email"])
            if not rollback_ok:
                logging.error("Failed to rollback Supabase auth email after DB failure: %s", rollback_err)
        return jsonify({"error": f"Could not save profile: {exc}"}), 500

    if not updated:
        return jsonify({"error": "User not found."}), 404

    # Regenerate user agreement PDF if name or email changed
    old_full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    new_full_name = f"{first_name} {last_name}".strip()
    old_email = str(user.get("email", "")).strip().lower()
    if old_full_name != new_full_name or old_email != email:
        try:
            new_filename = _build_terms_pdf_filename(new_full_name)
            new_pdf = _build_terms_policy_pdf(
                new_full_name,
                datetime.now(),
                email=email,
                include_signature_meta=True,
            )
            db.update_user_terms_agreement_proof(
                user_id=user["id"],
                full_name=new_full_name,
                file_name=new_filename,
                pdf_data=new_pdf.getvalue(),
            )
        except Exception as exc:
            logging.exception("Failed to regenerate user agreement PDF for user %s", user["id"])
            # Non-blocking error: continue even if PDF regeneration fails

    return jsonify({"success": True, "user": _safe_user_profile_payload(updated)})


@app.route("/api/users/<int:user_id>/avatar")
@login_required
def api_user_avatar(user_id):
    avatar_blob = db.get_user_avatar_blob(user_id)
    if not avatar_blob:
        return "", 404

    avatar_bytes, mime_type = avatar_blob
    return send_file(
        io.BytesIO(avatar_bytes),
        mimetype=mime_type,
        as_attachment=False,
        download_name=f"avatar-{user_id}",
        max_age=0,
    )


@app.route("/api/profile/avatar", methods=["POST"])
@login_required
def api_upload_profile_avatar():
    user = current_user()
    file = request.files.get("avatar")
    if not file:
        return jsonify({"error": "No file uploaded."}), 400

    original_name = file.filename or ""
    _, ext = os.path.splitext(original_name.lower())
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({"error": "Invalid image type. Use JPG, PNG, WEBP, or GIF."}), 400

    mime_type = (file.mimetype or "").lower()
    if not mime_type.startswith("image/"):
        return jsonify({"error": "Uploaded file must be an image."}), 400

    file.stream.seek(0, os.SEEK_END)
    file_size = file.stream.tell()
    file.stream.seek(0)
    if file_size > 2 * 1024 * 1024:
        return jsonify({"error": "Image is too large. Maximum size is 2 MB."}), 400

    avatar_bytes = file.read()
    if not avatar_bytes:
        return jsonify({"error": "Uploaded image is empty."}), 400

    try:
        updated = db.update_user_avatar(user["id"], avatar_bytes, mime_type)
        if not updated:
            return jsonify({"error": "User not found."}), 404
    except Exception as exc:
        logging.exception("Failed to upload avatar for user %s", user["id"])
        return jsonify({"error": f"Could not upload avatar: {exc}"}), 500

    return jsonify({"success": True, "user": _safe_user_profile_payload(updated)})


@app.route("/api/profile/avatar", methods=["DELETE"])
@login_required
def api_remove_profile_avatar():
    user = current_user()

    try:
        updated = db.update_user_avatar(user["id"], None, None)
    except Exception as exc:
        logging.exception("Failed to clear avatar for user %s", user["id"])
        return jsonify({"error": f"Could not remove avatar: {exc}"}), 500

    if not updated:
        return jsonify({"error": "User not found."}), 404

    return jsonify({"success": True, "user": _safe_user_profile_payload(updated)})

@app.route("/api/admin/users/<int:user_id>/approval", methods=["POST"])
@admin_required
def api_admin_update_user_approval(user_id):
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip().lower()
    if status not in {"approved", "rejected"}:
        return jsonify({"error": "Status must be 'approved' or 'rejected'."}), 400

    actor = current_user()
    if actor and actor.get("id") == user_id:
        return jsonify({"error": "You cannot change your own approval status."}), 400

    target = db.get_user_by_id(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404

    updated = db.update_user_approval_status(user_id, status, reviewed_by_user_id=actor["id"] if actor else None)
    return jsonify({"success": True, "user": updated})


@app.route("/api/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def api_admin_update_user_role(user_id):
    payload = request.get_json(silent=True) or {}
    role = str(payload.get("role", "")).strip().lower()
    if role not in {"teacher", "admin"}:
        return jsonify({"error": "Role must be 'teacher' or 'admin'."}), 400

    actor = current_user()
    if actor and actor.get("id") == user_id:
        return jsonify({"error": "You cannot change your own role."}), 400

    target = db.get_user_by_id(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404

    updated = db.update_user_role(user_id, role)
    return jsonify({"success": True, "user": updated})

@app.route("/api/subjects", methods=["POST"])
@login_required
def api_create_subject():
    user = current_user()
    data = request.get_json(silent=True) or {}
    try:
        _validate_schedule_conflicts(user["id"], data.get("schedule", []))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    subject = db.create_subject(
        teacher_id=user["id"],
        name=data["name"],
        course_code=data["courseCode"],
        section=data["section"],
        schedule_entries=data.get("schedule", []),
    )
    return jsonify(subject), 201


@app.route("/api/subjects/<int:subject_id>", methods=["DELETE"])
@login_required
def api_delete_subject(subject_id):
    user = current_user()
    subject = db.get_subject_for_teacher(subject_id, user["id"])
    if not subject:
        return jsonify({"error": "Subject not found for your account."}), 404
    db.delete_subject(subject_id)
    return "", 204


@app.route("/api/subject-groups/delete", methods=["POST"])
@login_required
def api_delete_subject_group():
    user = current_user()
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    course_code = str(data.get("courseCode", "")).strip()

    if not name or not course_code:
        return jsonify({"error": "Both name and courseCode are required."}), 400

    deleted_count = db.delete_subject_group(user["id"], name, course_code)
    if deleted_count == 0:
        return jsonify({"error": "Subject group not found for your account."}), 404

    return jsonify({"deleted": deleted_count}), 200


@app.route("/api/subjects/<int:subject_id>/schedules", methods=["PUT"])
@login_required
def api_update_schedules(subject_id):
    user = current_user()
    subject = db.get_subject_for_teacher(subject_id, user["id"])
    if not subject:
        return jsonify({"error": "Subject not found for your account."}), 404

    data = request.get_json(silent=True) or {}
    try:
        _validate_schedule_conflicts(
            user["id"],
            data.get("schedules", []),
            exclude_subject_id=subject_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    schedules = db.update_subject_schedules(subject_id, data.get("schedules", []))
    return jsonify(schedules)


@app.route("/api/sessions", methods=["POST"])
@login_required
def api_start_session():
    user = current_user()
    data = request.get_json(silent=True) or {}
    subject_id = data.get("subjectId")

    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        return jsonify({"error": "A valid subjectId is required."}), 400

    subject = db.get_subject_for_teacher(subject_id, user["id"])
    if not subject:
        return jsonify({"error": "Subject not found for your account."}), 404

    try:
        s = db.create_session(subject_id)
    except Exception as exc:
        logging.exception("Failed to create session for user %s subject %s", user["id"], subject_id)
        return jsonify({"error": f"Could not start session: {exc}"}), 500

    return jsonify(s), 201


@app.route("/api/sessions/<int:session_id>/end", methods=["POST"])
@login_required
def api_end_session(session_id):
    user = current_user()
    data = request.get_json(silent=True) or {}

    # Ensure this session belongs to the signed-in teacher.
    sessions_list = db.get_sessions(user["id"])
    if not any(s["id"] == session_id for s in sessions_list):
        return jsonify({"error": "Session not found for your account."}), 404

    try:
        s = db.end_session(session_id, data.get("summaryStats", {}))
    except Exception as exc:
        logging.exception("Failed to end session %s for user %s", session_id, user["id"])
        return jsonify({"error": f"Could not end session: {exc}"}), 500

    return jsonify(s)


@app.route("/api/sessions/<int:session_id>/cancel", methods=["POST"])
@login_required
def api_cancel_session(session_id):
    user = current_user()

    # Ensure this session belongs to the signed-in teacher.
    sessions_list = db.get_sessions(user["id"])
    target_session = next((s for s in sessions_list if s["id"] == session_id), None)
    if not target_session:
        return jsonify({"error": "Session not found for your account."}), 404

    if target_session.get("status") != "active":
        return jsonify({"error": "Only active sessions can be cancelled."}), 400

    try:
        cancelled = db.cancel_session(session_id)
        if not cancelled:
            return jsonify({"error": "Session could not be cancelled."}), 404
    except Exception as exc:
        logging.exception("Failed to cancel session %s for user %s", session_id, user["id"])
        return jsonify({"error": f"Could not cancel session: {exc}"}), 500

    return jsonify({"success": True, "id": session_id})


def _compute_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]

    q_clamped = max(0.0, min(1.0, float(q)))
    position = (len(ordered) - 1) * q_clamped
    left_index = int(position)
    right_index = min(left_index + 1, len(ordered) - 1)
    fraction = position - left_index

    return ordered[left_index] + (ordered[right_index] - ordered[left_index]) * fraction


def _attention_level_from_score(
    score: float | int | None,
    *,
    p_min: float | None = None,
    p_max: float | None = None,
) -> str | None:
    if score is None:
        return None

    value = float(score)

    if p_min is not None and p_max is not None:
        denom = float(p_max) - float(p_min)
        if denom == 0:
            normalized_score = 0.5
        else:
            normalized_score = (value - float(p_min)) / denom
            normalized_score = max(0.0, min(1.0, normalized_score))

        if normalized_score >= 0.66:
            return "high"
        if normalized_score >= 0.33:
            return "medium"
        return "low"

    # Fallback when report quantiles are unavailable.
    if value > 75:
        return "high"
    if value > 50:
        return "medium"
    return "low"


def _format_top_labels(items: list[tuple[str, float]], empty_text: str) -> str:
    if not items:
        return empty_text
    top_items = [label for label, _ in items[:3]]
    if len(top_items) == 1:
        return top_items[0]
    if len(top_items) == 2:
        return f"{top_items[0]} and {top_items[1]}"
    return f"{', '.join(top_items[:-1])}, and {top_items[-1]}"


def _hour_window_label(hour_24: int) -> str:
    start_display = datetime(2000, 1, 1, hour_24, 0).strftime("%I:%M %p").lstrip("0")
    end_display = datetime(2000, 1, 1, hour_24, 59).strftime("%I:%M %p").lstrip("0")
    return f"{start_display} - {end_display}"


def _normalize_section_for_display(section: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(section or "").strip())
    return re.sub(r"\s*-\s*", "-", cleaned)


def _format_subject_section_label(course_code: str, section: str) -> str:
    course = str(course_code or "").strip() or "Unspecified Subject"
    section_display = _normalize_section_for_display(section) or "Unspecified Section"
    return f"{course}: {section_display}"


def _build_report_interpretation_content(
    sessions_list: list,
    subject_filter: str = "",
    section_filter: str = "",
) -> dict:
    rows = []
    for session_item in sessions_list:
        summary_stats = session_item.get("summary_stats") or {}
        score_raw = summary_stats.get("avgAttention")
        if score_raw is None:
            continue
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            continue

        start_time = session_item.get("start_time")
        if not start_time:
            continue

        course_code = str(session_item.get("course_code") or "").strip()
        section = str(session_item.get("section") or "").strip()
        section_display = _normalize_section_for_display(section) or "Unspecified Section"
        class_label = _format_subject_section_label(course_code, section)

        rows.append(
            {
                "score": score,
                "course_code": course_code or "Unspecified Subject",
                "section": section_display,
                "class_label": class_label,
                "weekday": start_time.strftime("%A"),
                "hour": int(start_time.hour),
            }
        )

    if not rows:
        return {
            "sections": [],
            "no_data_message": "No interpretation could be generated because there are no sessions with valid attention data in the selected date range.",
        }

    session_scores = [item["score"] for item in rows]
    report_p_min = _compute_quantile(session_scores, 0.05)
    report_p_max = _compute_quantile(session_scores, 0.95)

    for item in rows:
        item["level"] = _attention_level_from_score(
            item["score"],
            p_min=report_p_min,
            p_max=report_p_max,
        )

    normalized_section_filter = _normalize_section_for_display(section_filter)

    weekday_order = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6,
    }

    def _most_common(values: list, *, limit: int = 2, order_map: dict | None = None) -> list:
        if not values:
            return []
        counts = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        ranked_items = sorted(
            counts.items(),
            key=lambda pair: (
                -pair[1],
                (order_map or {}).get(pair[0], 999),
                str(pair[0]),
            ),
        )
        return [value for value, _ in ranked_items[:limit]]

    if not subject_filter and not section_filter:
        group_key = "class_label"
        group_empty_text = "No classes matched the interpretation criteria."
        group_table_title_template = "{prefix} overall attention by class"
    elif subject_filter:
        group_key = "section"
        group_empty_text = "No sections matched the interpretation criteria."
        group_table_title_template = f"{{prefix}} overall attention by section for {subject_filter}"
    else:
        group_key = "course_code"
        group_empty_text = "No subjects matched the interpretation criteria."
        group_table_title_template = f"{{prefix}} overall attention by subject for {normalized_section_filter}"

    group_scores = {}
    for item in rows:
        label = item[group_key]
        group_scores.setdefault(label, []).append(item["score"])

    group_averages = {
        label: (sum(values) / len(values))
        for label, values in group_scores.items()
    }
    group_levels = {
        label: _attention_level_from_score(avg_score, p_min=report_p_min, p_max=report_p_max)
        for label, avg_score in group_averages.items()
    }

    has_low_group = any(level == "low" for level in group_levels.values())
    has_medium_group = any(level == "medium" for level in group_levels.values())

    if has_low_group and has_medium_group:
        target_levels = ["low", "medium"]
    elif has_low_group:
        target_levels = ["low"]
    elif has_medium_group:
        target_levels = ["medium"]
    else:
        target_levels = ["medium"]

    sections = []

    for focus_level in target_levels:
        focus_label = focus_level.capitalize()
        attention_label = f"{focus_label} Attention"
        metric_prefix = "Lowest" if focus_level == "low" else "Medium"
        group_table_title = group_table_title_template.format(prefix=metric_prefix)

        group_ranked = sorted(
            [
                (label, avg_score)
                for label, avg_score in group_averages.items()
                if group_levels.get(label) == focus_level
            ],
            key=lambda pair: (pair[1], pair[0]),
        )
        group_summary_text = _format_top_labels(group_ranked, group_empty_text)

        day_scores = {}
        for item in rows:
            day_scores.setdefault(item["weekday"], []).append(item["score"])
        day_ranked = []
        for day_name, values in day_scores.items():
            avg_score = sum(values) / len(values)
            if _attention_level_from_score(avg_score, p_min=report_p_min, p_max=report_p_max) == focus_level:
                day_ranked.append((day_name, avg_score))
        day_ranked.sort(key=lambda pair: (pair[1], weekday_order.get(pair[0], 99), pair[0]))

        hour_scores = {}
        for item in rows:
            hour_scores.setdefault(item["hour"], []).append(item["score"])
        hour_ranked = []
        for hour, values in hour_scores.items():
            avg_score = sum(values) / len(values)
            if _attention_level_from_score(avg_score, p_min=report_p_min, p_max=report_p_max) == focus_level:
                hour_ranked.append((hour, avg_score))
        hour_ranked.sort(key=lambda pair: (pair[1], pair[0]))
        top_focus_hours = {hour for hour, _ in hour_ranked[:3]}

        group_table_rows = [
            [label, f"{_attention_level_from_score(score, p_min=report_p_min, p_max=report_p_max).capitalize()} Attention"]
            for label, score in group_ranked[:3]
        ]
        day_table_title = f"Days that most often showed {focus_level} attention"
        day_table_rows = [
            [day_name, f"{_attention_level_from_score(score, p_min=report_p_min, p_max=report_p_max).capitalize()} Attention"]
            for day_name, score in day_ranked[:3]
        ]
        time_table_title = f"Time windows that usually showed {focus_level} attention"
        time_table_rows = [
            [_hour_window_label(hour), f"{_attention_level_from_score(score, p_min=report_p_min, p_max=report_p_max).capitalize()} Attention"]
            for hour, score in hour_ranked[:3]
        ]

        focus_line = f"Interpretation focus: {focus_label} attention level patterns across the selected sessions."
        fallback_line = None
        if focus_level == "medium" and not has_low_group:
            fallback_line = (
                "No low-attention group averages were detected in this range, so medium-attention trends were used for interpretation."
            )
        focus_block_line = focus_line if not fallback_line else f"{focus_line} {fallback_line}"

        top_days = {day_name for day_name, _ in day_ranked[:2]}
        top_hours = {hour for hour, _ in hour_ranked[:2]}
        correlation_rows = []

        if top_days or top_hours:
            for group_label, _ in group_ranked[:3]:
                focused_rows = [
                    item for item in rows if item[group_key] == group_label and item["level"] == focus_level
                ]
                if not focused_rows:
                    continue

                day_matches = [item for item in focused_rows if item["weekday"] in top_days] if top_days else []
                hour_matches = [item for item in focused_rows if item["hour"] in top_hours] if top_hours else []
                overlap_rows = [
                    item
                    for item in focused_rows
                    if (not top_days or item["weekday"] in top_days)
                    and (not top_hours or item["hour"] in top_hours)
                ] if (top_days and top_hours) else []

                if overlap_rows:
                    candidate_rows = overlap_rows
                    has_day_pattern = True
                    has_time_pattern = True
                elif day_matches and hour_matches:
                    candidate_rows = day_matches if len(day_matches) >= len(hour_matches) else hour_matches
                    has_day_pattern = True
                    has_time_pattern = True
                elif day_matches:
                    candidate_rows = day_matches
                    has_day_pattern = True
                    has_time_pattern = False
                elif hour_matches:
                    candidate_rows = hour_matches
                    has_day_pattern = False
                    has_time_pattern = True
                else:
                    continue

                top_day = _most_common(
                    [item["weekday"] for item in candidate_rows],
                    limit=1,
                    order_map=weekday_order,
                ) if has_day_pattern else []
                top_hour = _most_common([item["hour"] for item in candidate_rows], limit=1) if has_time_pattern else []

                representative = candidate_rows[0]
                if group_key == "class_label":
                    subject_value = representative["course_code"]
                    section_value = representative["section"]
                elif group_key == "section":
                    subject_value = str(subject_filter or representative["course_code"]).strip() or representative["course_code"]
                    section_value = group_label
                else:
                    subject_value = group_label
                    section_value = normalized_section_filter or representative["section"]

                correlation_rows.append(
                    {
                        "subject": subject_value,
                        "section": section_value,
                        "attention_level": attention_label,
                        "day": top_day[0] if top_day else "Not specific",
                        "time_window": _hour_window_label(top_hour[0]) if top_hour else "Not specific",
                    }
                )

        if correlation_rows:
            has_specific_day = any(row.get("day") and row["day"] != "Not specific" for row in correlation_rows)
            has_specific_time = any(row.get("time_window") and row["time_window"] != "Not specific" for row in correlation_rows)
            if has_specific_day and has_specific_time:
                correlation_detected_line = f"Correlation detected: {focus_label} attention patterns were observed in day and time windows (not always simultaneously for every section)."
            elif has_specific_day:
                correlation_detected_line = f"Correlation detected: {focus_label} attention patterns were observed by day, with no single dominant time window."
            else:
                correlation_detected_line = f"Correlation detected: {focus_label} attention patterns were observed by time window, with no single dominant day."
        else:
            correlation_detected_line = f"Correlation: none. No strong day-time overlap was detected for {focus_level} attention."

        correlation_sentence_lines = []
        for row in correlation_rows:
            day_value = str(row.get("day") or "Not specific")
            time_value = str(row.get("time_window") or "Not specific")
            if day_value != "Not specific" and time_value != "Not specific":
                sentence = f"{row['subject']}: {row['section']} is mostly {row['attention_level'].lower()} during {day_value}, around {time_value}."
            elif day_value != "Not specific":
                sentence = f"{row['subject']}: {row['section']} is mostly {row['attention_level'].lower()} during {day_value}, with no single dominant time window."
            elif time_value != "Not specific":
                sentence = f"{row['subject']}: {row['section']} is mostly {row['attention_level'].lower()} around {time_value}, with no single dominant day."
            else:
                sentence = f"{row['subject']}: {row['section']} is mostly {row['attention_level'].lower()} with no single dominant day or time window."
            correlation_sentence_lines.append(sentence)

        sections.append(
            {
                "focus_level": focus_level,
                "focus_label": focus_label,
                "attention_label": attention_label,
                "focus_line": focus_line,
                "focus_block_line": focus_block_line,
                "fallback_line": fallback_line,
                "group_table_title": group_table_title,
                "group_no_match_text": group_empty_text,
                "group_table_rows": group_table_rows,
                "day_table_title": day_table_title,
                "day_table_rows": day_table_rows,
                "time_table_title": time_table_title,
                "time_table_rows": time_table_rows,
                "correlation_rows": correlation_rows,
                "correlation_detected_line": correlation_detected_line,
                "correlation_sentence_lines": correlation_sentence_lines,
            }
        )

    return {
        "sections": sections,
        "no_data_message": None,
    }


def _build_report_pdf(
    user: dict,
    start_date: str,
    end_date: str,
    sessions_list: list,
    subject_filter: str = "",
    section_filter: str = "",
    teacher_label: str | None = None,
) -> io.BytesIO:
    """Build the report PDF and return a seeked BytesIO buffer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
    )

    try:
        start_display = datetime.strptime(start_date, "%Y-%m-%d").strftime("%m-%d-%Y")
        end_display = datetime.strptime(end_date, "%Y-%m-%d").strftime("%m-%d-%Y")
    except ValueError:
        start_display = start_date
        end_display = end_date

    report_title = f"Ai-Listo Report ({start_display} to {end_display})"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=report_title,
        author="Ai-Listo",
        subject="Student Attention Report",
        creator="Ai-Listo",
    )

    styles = getSampleStyleSheet()
    brand_blue = colors.HexColor("#3b82f6")
    dark = colors.HexColor("#1e293b")
    muted = colors.HexColor("#64748b")

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=dark,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=muted,
        spaceAfter=2,
        fontName="Helvetica",
    )
    section_style = ParagraphStyle(
        "ReportSection",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=dark,
        spaceBefore=14,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    normal_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=9,
        textColor=dark,
        fontName="Helvetica",
    )
    table_cell_style = ParagraphStyle(
        "ReportTableCellWrap",
        parent=normal_style,
        fontSize=8.5,
        leading=10,
    )

    def _strip_label_prefix(text: str, prefix: str) -> str:
        value = str(text or "").strip()
        if value.lower().startswith(prefix.lower()):
            return value[len(prefix):].lstrip()
        return value

    story = []

    story.append(Paragraph("Ai-Listo", title_style))
    story.append(Paragraph("Student Attention Monitoring System", subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=brand_blue))
    story.append(Spacer(1, 0.3 * cm))

    teacher_name = teacher_label or f"{user['first_name']} {user['last_name']}"
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    story.append(Paragraph(f"<b>Report Period:</b> {start_display} to {end_display}", normal_style))
    story.append(Paragraph(f"<b>Teacher:</b> {teacher_name}", normal_style))
    story.append(Paragraph(f"<b>Subject Filter:</b> {subject_filter or 'All Subjects'}", normal_style))
    story.append(Paragraph(f"<b>Section Filter:</b> {section_filter or 'All Sections'}", normal_style))
    story.append(Paragraph(f"<b>Generated:</b> {generated_at}", normal_style))
    story.append(Spacer(1, 0.5 * cm))

    total = len(sessions_list)
    attentions = [
        s["summary_stats"].get("avgAttention")
        for s in sessions_list
        if s.get("summary_stats") and s["summary_stats"].get("avgAttention") is not None
    ]
    avg_att = round(sum(attentions) / len(attentions)) if attentions else 0

    # Keep report table widths consistent across sections.
    report_table_total_width = 16.5 * cm

    story.append(Paragraph("Summary", section_style))
    summary_data = [
        ["Total Sessions", "Avg. Attention"],
        [str(total), f"{avg_att}%"],
    ]
    summary_table = Table(summary_data, colWidths=[report_table_total_width / 2, report_table_total_width / 2])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)

    interpretation_content = _build_report_interpretation_content(
        sessions_list,
        subject_filter=subject_filter,
        section_filter=section_filter,
    )

    sections = interpretation_content.get("sections", [])
    no_data_message = interpretation_content.get("no_data_message")

    def _join_first_col(rows: list[list[str]], fallback_text: str) -> str:
        if not rows:
            return fallback_text
        return ", ".join(str(row[0]) for row in rows[:3])

    if not sections:
        story.append(Paragraph("Interpretation", section_style))
        story.append(Paragraph(html.escape(no_data_message or "No interpretation data available."), normal_style))
    else:
        for idx, section_data in enumerate(sections):
            attention_header = section_data.get("attention_label", "Attention")

            story.append(Paragraph(f"Interpretation ({attention_header})", section_style))
            focus_line = section_data.get("focus_block_line") or section_data.get("focus_line")
            if focus_line:
                focus_detail = _strip_label_prefix(focus_line, "Interpretation focus:")
                story.append(Paragraph(f"<b>Interpretation Focus:</b> {html.escape(focus_detail)}", normal_style))
                story.append(Spacer(1, 0.15 * cm))

            interpretation_table_data = [["Interpretation Metric", "Details"]]
            group_title = section_data.get("group_table_title") or "Lowest overall attention"
            group_no_match_text = section_data.get("group_no_match_text") or "No groups matched the interpretation criteria."
            group_rows = section_data.get("group_table_rows", [])
            day_title = section_data.get("day_table_title") or "Days"
            day_rows = section_data.get("day_table_rows", [])
            time_title = section_data.get("time_table_title") or "Time windows"
            time_rows = section_data.get("time_table_rows", [])

            interpretation_table_data.append([
                Paragraph(html.escape(group_title), table_cell_style),
                Paragraph(html.escape(_join_first_col(group_rows, group_no_match_text)), table_cell_style),
            ])
            interpretation_table_data.append([
                Paragraph(html.escape(day_title), table_cell_style),
                Paragraph(html.escape(_join_first_col(day_rows, "No day-level pattern was identified.")), table_cell_style),
            ])
            interpretation_table_data.append([
                Paragraph(html.escape(time_title), table_cell_style),
                Paragraph(html.escape(_join_first_col(time_rows, "No time-of-day pattern was identified.")), table_cell_style),
            ])

            interpretation_table = Table(
                interpretation_table_data,
                colWidths=[6.0 * cm, 10.5 * cm],
                repeatRows=1,
            )
            interpretation_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.append(interpretation_table)

            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(f"Correlation Table ({attention_header})", section_style))

            detected_line = section_data.get("correlation_detected_line")
            if detected_line:
                detected_detail = _strip_label_prefix(detected_line, "Correlation detected:")
                detected_detail = _strip_label_prefix(detected_detail, "Correlation:")
                story.append(Paragraph(f"<b>Correlation Detected:</b> {html.escape(detected_detail)}", normal_style))

            correlation_rows = section_data.get("correlation_rows", [])
            correlation_sentence_lines = section_data.get("correlation_sentence_lines", [])
            if correlation_rows:
                for line in correlation_sentence_lines:
                    story.append(Paragraph(html.escape(line), normal_style, bulletText="•"))
                story.append(Spacer(1, 0.15 * cm))

                correlation_data = [[
                    "Subject",
                    "Section",
                    "Attention Level",
                    "Day",
                    "Time Window",
                ]]
                for row in correlation_rows:
                    correlation_data.append([
                        Paragraph(html.escape(str(row.get("subject") or "—")), table_cell_style),
                        Paragraph(html.escape(str(row.get("section") or "—")), table_cell_style),
                        Paragraph(html.escape(str(row.get("attention_level") or "—")), table_cell_style),
                        Paragraph(html.escape(str(row.get("day") or "—")), table_cell_style),
                        Paragraph(html.escape(str(row.get("time_window") or "—")), table_cell_style),
                    ])

                correlation_table = Table(
                    correlation_data,
                    colWidths=[3.2 * cm, 3.4 * cm, 3.2 * cm, 2.7 * cm, 4.0 * cm],
                    repeatRows=1,
                )
                correlation_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                story.append(correlation_table)

            if idx < len(sections) - 1:
                story.append(Spacer(1, 0.35 * cm))

    # Build daily average-attention trend points from the selected date range sessions.
    daily_attention_totals = {}
    daily_attention_counts = {}
    for s in sessions_list:
        if not s.get("start_time"):
            continue
        if not s.get("summary_stats") or s["summary_stats"].get("avgAttention") is None:
            continue
        day_key = s["start_time"].date()
        daily_attention_totals[day_key] = daily_attention_totals.get(day_key, 0.0) + float(s["summary_stats"]["avgAttention"])
        daily_attention_counts[day_key] = daily_attention_counts.get(day_key, 0) + 1

    if daily_attention_totals:
        trend_days = sorted(daily_attention_totals.keys())
        trend_labels = [d.strftime("%b %d") for d in trend_days]
        trend_values = [round(daily_attention_totals[d] / daily_attention_counts[d], 2) for d in trend_days]

        trend_block = [Paragraph("Avg. Attention Trend", section_style)]
        try:
            chart_drawing = Drawing(report_table_total_width, 6.2 * cm)
            chart = HorizontalLineChart()
            chart.x = 1.0 * cm
            chart.y = 0.9 * cm
            chart.width = report_table_total_width - (1.5 * cm)
            chart.height = 4.8 * cm
            chart.data = [trend_values]
            chart.joinedLines = 1
            chart.lines[0].strokeColor = brand_blue
            chart.lines[0].strokeWidth = 2
            chart.lines[0].symbol = makeMarker("FilledCircle")

            chart.categoryAxis.categoryNames = trend_labels
            chart.categoryAxis.labels.boxAnchor = "n"
            chart.categoryAxis.labels.fontName = "Helvetica"
            chart.categoryAxis.labels.fontSize = 7
            chart.categoryAxis.labels.angle = 30
            chart.categoryAxis.labels.dy = -8

            chart.valueAxis.valueMin = 0
            chart.valueAxis.valueMax = 100
            chart.valueAxis.valueStep = 10
            chart.valueAxis.labels.fontName = "Helvetica"
            chart.valueAxis.labels.fontSize = 7

            chart_drawing.add(chart)
            trend_block.append(chart_drawing)
        except Exception:
            logging.exception("Failed to render avg attention trend chart")
            trend_block.append(Paragraph("Trend chart could not be rendered for this report.", normal_style))
        story.append(KeepTogether(trend_block))
    else:
        story.append(KeepTogether([
            Paragraph("Avg. Attention Trend", section_style),
            Paragraph("No attention data available for trend chart in the selected date range.", normal_style),
        ]))

    story.append(Paragraph("Session Details", section_style))
    if sessions_list:
        show_teacher_column = (teacher_name or "").strip().lower() == "all teachers"
        header_text_style = ParagraphStyle(
            "ReportTableHeaderText",
            parent=normal_style,
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=9.5,
            alignment=1,
            textColor=colors.white,
        )
        teacher_cell_style = ParagraphStyle(
            "ReportTeacherCellText",
            parent=normal_style,
            fontName="Helvetica",
            fontSize=8.5,
            leading=9.5,
            alignment=1,
            textColor=dark,
        )

        avg_attention_header = Paragraph("Avg.<br/>Attention", header_text_style)
        if show_teacher_column:
            table_data = [["Teacher", "Class", "Date", "Start Time", "End Time", "Duration", avg_attention_header]]
        else:
            table_data = [["Class", "Date", "Start Time", "End Time", "Duration", avg_attention_header]]

        for s in sessions_list:
            course = f"{s.get('course_code', '')} - {s.get('section', '')}"
            date_display = s["start_time"].strftime("%b %d, %Y") if s.get("start_time") else "—"
            start_time_display = s["start_time"].strftime("%I:%M %p") if s.get("start_time") else "—"
            end_time_display = s["end_time"].strftime("%I:%M %p") if s.get("end_time") else "—"
            if s.get("start_time") and s.get("end_time"):
                mins = _duration_minutes_ignore_seconds(s.get("start_time"), s.get("end_time")) or 0
                hours, rem_mins = divmod(mins, 60)
                duration = f"{hours} hr {rem_mins} min"
            else:
                duration = "—"
            att = (
                f"{s['summary_stats']['avgAttention']}%"
                if s.get("summary_stats") and s["summary_stats"].get("avgAttention") is not None
                else "—"
            )
            if show_teacher_column:
                teacher_first_name = str(s.get("teacher_first_name", "") or "").strip()
                teacher_last_name = str(s.get("teacher_last_name", "") or "").strip()
                if teacher_last_name and teacher_first_name:
                    teacher_full_name = Paragraph(
                        f"{teacher_last_name},<br/>{teacher_first_name}",
                        teacher_cell_style,
                    )
                elif teacher_last_name:
                    teacher_full_name = Paragraph(f"{teacher_last_name},", teacher_cell_style)
                elif teacher_first_name:
                    teacher_full_name = Paragraph(teacher_first_name, teacher_cell_style)
                else:
                    teacher_full_name = "—"
                table_data.append([
                    teacher_full_name,
                    course,
                    date_display,
                    start_time_display,
                    end_time_display,
                    duration,
                    att,
                ])
            else:
                table_data.append([course, date_display, start_time_display, end_time_display, duration, att])

        if show_teacher_column:
            # Prioritize class readability by giving it more width and shrinking teacher.
            col_widths = [2.3 * cm, 3.5 * cm, 2.2 * cm, 1.9 * cm, 1.9 * cm, 2.0 * cm, 2.7 * cm]
        else:
            col_widths = [3.5 * cm, 2.8 * cm, 2.4 * cm, 2.4 * cm, 2.7 * cm, 2.7 * cm]
        detail_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        detail_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(detail_table)
    else:
        story.append(Paragraph("No sessions found for the selected date range.", normal_style))

    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "This report was automatically generated by Ai-Listo — SSS Village Elementary School.",
        subtitle_style,
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def _build_report_filename(start_date: str, end_date: str, subject_code: str = "", section: str = "") -> str:
    filename = f"ailisto-report-{start_date}-to-{end_date}"
    if subject_code:
        filename += f"-{subject_code}"
    if section:
        filename += f"-{section}"
    return f"{filename}.pdf"


def _resolve_report_target_scope(user: dict, teacher_id_raw) -> tuple[int | None, dict, str]:
    """Resolve report scope and label from an optional teacherId filter."""
    is_admin = user.get("role") == "admin"
    teacher_token = str(teacher_id_raw).strip() if teacher_id_raw is not None else ""

    if teacher_token:
        if not is_admin:
            raise PermissionError("Only admins can request a different teacher report scope")

        try:
            teacher_id = int(teacher_token)
        except (TypeError, ValueError):
            raise ValueError("Invalid teacherId") from None

        target_user = db.get_user_by_id(teacher_id)
        is_report_target = bool(target_user) and (
            target_user.get("role") == "admin"
            or (target_user.get("role") == "teacher" and target_user.get("approval_status") == "approved")
        )
        if not is_report_target:
            raise LookupError("Teacher not found")

        teacher_label = f"{target_user['first_name']} {target_user['last_name']}"
        return teacher_id, target_user, teacher_label

    if is_admin:
        return None, user, "All Teachers"

    teacher_label = f"{user['first_name']} {user['last_name']}"
    return user["id"], user, teacher_label


@app.route("/api/generate-report", methods=["POST"])
@login_required
def api_generate_report():
    """Return the PDF report as a downloadable attachment."""
    data = request.get_json(silent=True) or {}
    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    subject_code = str(data.get("subjectCode", "")).strip()
    section = str(data.get("section", "")).strip()
    teacher_id_raw = data.get("teacherId")
    
    if not start_date or not end_date:
        return jsonify({"error": "startDate and endDate are required"}), 400
    
    user = current_user()
    
    try:
        target_user_id, target_user, teacher_label = _resolve_report_target_scope(user, teacher_id_raw)
    except PermissionError:
        return jsonify({"error": "Unauthorized"}), 403
    except ValueError:
        return jsonify({"error": "Invalid teacherId"}), 400
    except LookupError:
        return jsonify({"error": "Teacher not found"}), 404
    
    try:
        sessions_list = db.get_sessions_by_date_range(
            target_user_id,
            start_date,
            end_date,
            subject_code=subject_code,
            section=section,
        )
        buf = _build_report_pdf(
            target_user,
            start_date,
            end_date,
            sessions_list,
            subject_filter=subject_code,
            section_filter=section,
            teacher_label=teacher_label,
        )
    except Exception as exc:
        logging.exception(
            "Report generation failed for user=%s start=%s end=%s subject=%s section=%s",
            target_user_id,
            start_date,
            end_date,
            subject_code,
            section,
        )
        return jsonify({"error": "Failed to generate report"}), 500
    filename = _build_report_filename(start_date, end_date, subject_code, section)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/api/preview-report")
@login_required
def api_preview_report():
    """Return the PDF report inline for browser preview."""
    start_date = request.args.get("startDate", "")
    end_date = request.args.get("endDate", "")
    subject_code = request.args.get("subjectCode", "").strip()
    section = request.args.get("section", "").strip()
    teacher_id_raw = request.args.get("teacherId")
    
    if not start_date or not end_date:
        return jsonify({"error": "startDate and endDate are required"}), 400
    
    user = current_user()
    
    try:
        target_user_id, target_user, teacher_label = _resolve_report_target_scope(user, teacher_id_raw)
    except PermissionError:
        return jsonify({"error": "Unauthorized"}), 403
    except ValueError:
        return jsonify({"error": "Invalid teacherId"}), 400
    except LookupError:
        return jsonify({"error": "Teacher not found"}), 404
    
    try:
        sessions_list = db.get_sessions_by_date_range(
            target_user_id,
            start_date,
            end_date,
            subject_code=subject_code,
            section=section,
        )
        buf = _build_report_pdf(
            target_user,
            start_date,
            end_date,
            sessions_list,
            subject_filter=subject_code,
            section_filter=section,
            teacher_label=teacher_label,
        )
    except Exception as exc:
        logging.exception(
            "Report preview failed for user=%s start=%s end=%s subject=%s section=%s",
            target_user_id,
            start_date,
            end_date,
            subject_code,
            section,
        )
        return jsonify({"error": "Failed to generate report"}), 500
    filename = _build_report_filename(start_date, end_date, subject_code, section)
    return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=filename)


@app.route("/api/weekly-attention")
@login_required
def api_weekly_attention():
    """Get weekly attention data for a specific week."""
    user = current_user()
    week_date_str = request.args.get("date")
    if not week_date_str:
        return jsonify({"error": "date parameter is required"}), 400
    
    try:
        week_date = datetime.fromisoformat(week_date_str)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    try:
        if user.get("role") == "admin":
            data = db.get_weekly_attention_admin(week_date)
        else:
            data = db.get_weekly_attention(user["id"], week_date)
        return jsonify(data), 200
    except Exception as exc:
        logging.exception("Failed to get weekly attention for user=%s date=%s", user["id"], week_date_str)
        return jsonify({"error": "Failed to fetch weekly data"}), 500


@app.route("/api/sessions")
@login_required
def api_get_sessions():
    """Get sessions for the selected month."""
    user = current_user()
    selected_year, selected_month_num, selected_month = _resolve_month_selection(
        month_value=request.args.get("month"),
        year_value=request.args.get("year"),
        month_number_value=request.args.get("month_num"),
    )
    
    try:
        # Admin can filter by teacher
        teacher_id = user["id"]
        if user.get("role") == "admin":
            teacher_id = None
            teacher_arg_present = "teacher_id" in request.args
            if teacher_arg_present:
                raw_teacher_value = (request.args.get("teacher_id") or "").strip()
                if not raw_teacher_value:
                    session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)
                else:
                    teacher_id_param = request.args.get("teacher_id", type=int)
                    if teacher_id_param:
                        candidate = db.get_user_by_id(teacher_id_param)
                        if candidate and candidate.get("role") == "teacher" and candidate.get("approval_status") == "approved":
                            session[ADMIN_HISTORY_TEACHER_SESSION_KEY] = teacher_id_param
                        else:
                            session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)
                    else:
                        session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)

            selected_teacher_id = session.get(ADMIN_HISTORY_TEACHER_SESSION_KEY)
            if selected_teacher_id:
                candidate = db.get_user_by_id(selected_teacher_id)
                if candidate and candidate.get("role") == "teacher" and candidate.get("approval_status") == "approved":
                    teacher_id = selected_teacher_id
                else:
                    session.pop(ADMIN_HISTORY_TEACHER_SESSION_KEY, None)
        
        sessions_list = db.get_sessions_for_month(teacher_id, selected_year, selected_month_num)
        
        # Format sessions for JSON
        formatted_sessions = []
        for s in sessions_list:
            formatted_sessions.append({
                "id": s["id"],
                "course_code": s.get("course_code"),
                "section": s.get("section"),
                "subject_name": s.get("subject_name"),
                "start_time": s.get("start_time").isoformat() if s.get("start_time") else None,
                "end_time": s.get("end_time").isoformat() if s.get("end_time") else None,
                "duration_minutes": _duration_minutes_ignore_seconds(s.get("start_time"), s.get("end_time")),
                "avg_attention": s.get("summary_stats", {}).get("avgAttention") if s.get("summary_stats") else None,
            })
        
        return jsonify({
            "sessions": formatted_sessions,
            "month": selected_month,
        }), 200
    except Exception as exc:
        logging.exception("Failed to get paginated sessions for user=%s", user["id"])
        return jsonify({"error": "Failed to fetch sessions"}), 500


# ─── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
