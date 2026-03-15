import os
import io
import json
import logging
import requests
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

# Bootstrap tables on startup
db.init_db()


# ─── Auth Helpers ─────────────────────────────────────────────────────

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


def current_user() -> dict | None:
    uid = session.get("user_id")
    if uid is None:
        return None
    return db.get_user_by_id(uid)


def _safe_user_profile_payload(user_obj: dict) -> dict:
    return {
        "id": user_obj.get("id"),
        "first_name": user_obj.get("first_name"),
        "last_name": user_obj.get("last_name"),
        "email": user_obj.get("email"),
        "avatar_url": user_obj.get("avatar_url"),
    }


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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email:
            if is_ajax:
                return jsonify({"error": "Email is required.", "field": "email"}), 400
            flash("Email is required.", "error")
            return render_template("login.html")

        if not password:
            if is_ajax:
                return jsonify({"error": "Password is required.", "field": "password"}), 400
            flash("Password is required.", "error")
            return render_template("login.html")

        user = db.get_user_by_email(email)
        if user and db.verify_password(password, user["password"]):
            approval_status = user.get("approval_status", "approved")
            if approval_status == "pending":
                msg = "Wait for Admin approval before signing in."
                if is_ajax:
                    return jsonify({"error": msg, "code": "pending_approval"}), 403
                flash(msg, "error")
                return render_template("login.html")

            if approval_status == "rejected":
                msg = "Your account request was rejected by the admin."
                if is_ajax:
                    return jsonify({"error": msg, "code": "account_rejected"}), 403
                flash(msg, "error")
                return render_template("login.html")

            session["user_id"] = user["id"]
            if is_ajax:
                return jsonify({"success": True, "redirect": url_for("home")})
            return redirect(url_for("home"))

        if is_ajax:
            return jsonify({"error": "Invalid email or password."}), 401
        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email      = request.form.get("email", "").strip()
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
        elif len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
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

        db.create_user(
            email,
            password,
            first_name,
            last_name,
            approval_status="pending",
        )
        create_supabase_auth_user(email, password)
        pending_msg = "Account created. Wait for Admin approval before signing in."
        if is_ajax:
            return jsonify({"success": True, "redirect": url_for("login"), "message": pending_msg})
        flash(pending_msg, "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email = request.form.get("email", "").strip()

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
        return render_template("forgot-password.html")

    return render_template("forgot-password.html")


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

        if len(new_password) < 6:
            if is_ajax:
                return jsonify({"error": "Password must be at least 6 characters.", "field": "password"}), 400
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

        db.update_user_password(user["id"], new_password)

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


def _find_yolo_health_path():
    """Return the first reachable health endpoint path, or None."""
    for path in _YOLO_HEALTH_PATHS:
        try:
            r = requests.get(
                f"{_YOLO_SERVER}{path}",
                timeout=(3, 2),
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
            r = requests.get(
                f"{_YOLO_SERVER}{path}",
                timeout=(3, 2),
            )
            ct = r.headers.get("Content-Type", "")
            tried[path] = {"status": r.status_code, "content_type": ct}
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
    frame = payload.get("frame")
    logging.info(
        "YOLO infer request received: user_id=%s has_frame=%s frame_len=%s",
        session.get("user_id"),
        bool(frame),
        len(frame) if isinstance(frame, str) else 0,
    )
    if not frame:
        logging.warning("YOLO infer rejected: missing frame payload")
        return jsonify({"error": "Missing frame payload"}), 400

    try:
        r = requests.post(
            f"{_YOLO_SERVER}/infer",
            json={"frame": frame},
            timeout=(3, 8),
        )
    except requests.exceptions.RequestException as exc:
        logging.error("YOLO infer proxy error: %s", exc)
        return jsonify({"error": "YOLO server unavailable"}), 502

    try:
        data = r.json()
    except ValueError:
        logging.error("YOLO infer upstream returned non-JSON response with status %s", r.status_code)
        data = {"error": "Invalid response from YOLO server"}

    logging.info(
        "YOLO infer upstream response: status=%s keys=%s",
        r.status_code,
        sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
    )

    return jsonify(data), r.status_code


@app.route("/classes")
@login_required
def classes():
    user = current_user()
    subjects = db.get_subjects(user["id"])
    return render_template("classes.html", user=user, subjects=subjects)


@app.route("/history")
@login_required
def history():
    user = current_user()
    sessions_list = db.get_sessions(user["id"])
    stats = db.get_dashboard_stats(user["id"])
    subjects = db.get_subjects(user["id"])
    chart_data = [
        {
            "label": s["start_time"].strftime("%b %d") if s.get("start_time") else "",
            "value": s["summary_stats"].get("avgAttention"),
        }
        for s in sessions_list
        if s.get("summary_stats") and s["summary_stats"].get("avgAttention") is not None
    ]
    return render_template(
        "history.html",
        user=user,
        sessions=sessions_list,
        stats=stats,
        subjects=subjects,
        chart_data=chart_data,
    )


@app.route("/reports")
@login_required
def reports():
    user = current_user()
    return render_template("reports.html", user=user)


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    return render_template("profile.html", user=user)


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
    data = request.get_json()
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
    db.delete_subject(subject_id)
    return "", 204


@app.route("/api/subjects/<int:subject_id>/schedules", methods=["PUT"])
@login_required
def api_update_schedules(subject_id):
    data = request.get_json()
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


def _build_report_pdf(user: dict, start_date: str, end_date: str, sessions_list: list) -> io.BytesIO:
    """Build the report PDF and return a seeked BytesIO buffer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
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

    story = []

    story.append(Paragraph("Ai-Listo", title_style))
    story.append(Paragraph("Student Attention Monitoring System", subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=brand_blue))
    story.append(Spacer(1, 0.3 * cm))

    teacher_name = f"{user['first_name']} {user['last_name']}"
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    story.append(Paragraph(f"<b>Report Period:</b> {start_display} to {end_display}", normal_style))
    story.append(Paragraph(f"<b>Teacher:</b> {teacher_name}", normal_style))
    story.append(Paragraph(f"<b>Generated:</b> {generated_at}", normal_style))
    story.append(Spacer(1, 0.5 * cm))

    total = len(sessions_list)
    completed = sum(1 for s in sessions_list if s.get("status") == "completed")
    attentions = [
        s["summary_stats"].get("avgAttention")
        for s in sessions_list
        if s.get("summary_stats") and s["summary_stats"].get("avgAttention") is not None
    ]
    avg_att = round(sum(attentions) / len(attentions)) if attentions else 0

    story.append(Paragraph("Summary", section_style))
    summary_data = [
        ["Total Sessions", "Completed Sessions", "Avg. Attention"],
        [str(total), str(completed), f"{avg_att}%"],
    ]
    summary_table = Table(summary_data, colWidths=[5.5 * cm, 5.5 * cm, 5.5 * cm])
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

    story.append(Paragraph("Session Details", section_style))
    if sessions_list:
        table_data = [["Class", "Date", "Duration", "Status", "Avg. Attention"]]
        for s in sessions_list:
            course = f"{s.get('course_code', '')} - {s.get('section', '')}"
            start = s["start_time"].strftime("%b %d, %Y %I:%M %p") if s.get("start_time") else "—"
            if s.get("start_time") and s.get("end_time"):
                delta = s["end_time"] - s["start_time"]
                mins = int(delta.total_seconds() // 60)
                duration = f"{mins} min"
            else:
                duration = "—"
            status = s.get("status", "active").capitalize()
            att = (
                f"{s['summary_stats']['avgAttention']}%"
                if s.get("summary_stats") and s["summary_stats"].get("avgAttention") is not None
                else "—"
            )
            table_data.append([course, start, duration, status, att])

        col_widths = [4.5 * cm, 4.5 * cm, 2.5 * cm, 2.5 * cm, 3 * cm]
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


@app.route("/api/generate-report", methods=["POST"])
@login_required
def api_generate_report():
    """Return the PDF report as a downloadable attachment."""
    data = request.get_json(silent=True) or {}
    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    if not start_date or not end_date:
        return jsonify({"error": "startDate and endDate are required"}), 400
    user = current_user()
    try:
        sessions_list = db.get_sessions_by_date_range(user["id"], start_date, end_date)
        buf = _build_report_pdf(user, start_date, end_date, sessions_list)
    except Exception as exc:
        logging.error("Report error: %s", exc)
        return jsonify({"error": "Failed to generate report"}), 500
    filename = f"ailisto-report-{start_date}-to-{end_date}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/api/preview-report")
@login_required
def api_preview_report():
    """Return the PDF report inline for browser preview."""
    start_date = request.args.get("startDate", "")
    end_date = request.args.get("endDate", "")
    if not start_date or not end_date:
        return jsonify({"error": "startDate and endDate are required"}), 400
    user = current_user()
    try:
        sessions_list = db.get_sessions_by_date_range(user["id"], start_date, end_date)
        buf = _build_report_pdf(user, start_date, end_date, sessions_list)
    except Exception as exc:
        logging.error("Report preview error: %s", exc)
        return jsonify({"error": "Failed to generate report"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=False)


# ─── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
