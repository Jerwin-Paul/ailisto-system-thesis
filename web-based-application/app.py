import os
import json
import logging
import requests
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify,
)
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import db  # noqa: E402 — import after dotenv so DATABASE_URL is available

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(32).hex())

# Bootstrap tables on startup
db.init_db()


# ─── Auth Helpers ─────────────────────────────────────────────────────

def login_required(f):
    """Redirect to /login if no user session."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def current_user() -> dict | None:
    uid = session.get("user_id")
    if uid is None:
        return None
    return db.get_user_by_id(uid)


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

        db.create_user(email, password, first_name, last_name)
        create_supabase_auth_user(email, password)
        if is_ajax:
            return jsonify({"success": True, "redirect": url_for("login")})
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


_YOLO_SERVER = "http://4.216.188.104:5000"
# Common MJPEG feed paths — tried in order until one responds
_YOLO_FEED_PATHS = ["/video_feed", "/stream", "/video", "/feed"]


def _find_yolo_feed_path():
    """Return (path, content_type) for the first MJPEG-like feed, or (None, None)."""
    for path in _YOLO_FEED_PATHS:
        try:
            r = requests.get(
                f"{_YOLO_SERVER}{path}",
                stream=True,
                timeout=(3, 2),
            )
            ct = (r.headers.get("Content-Type") or "").lower()
            if r.status_code == 200 and ("multipart" in ct or "image" in ct or "octet-stream" in ct):
                r.close()
                return path, ct
            r.close()
        except requests.exceptions.RequestException:
            continue
    return None, None


@app.route("/api/yolo-health")
@login_required
def yolo_health():
    """Check YOLO server reachability and report diagnostics."""
    # First check basic connectivity
    tried = {}
    for path in _YOLO_FEED_PATHS:
        try:
            r = requests.get(
                f"{_YOLO_SERVER}{path}",
                stream=True,
                timeout=(3, 2),
            )
            ct = r.headers.get("Content-Type", "")
            tried[path] = {"status": r.status_code, "content_type": ct}
            r.close()
        except requests.exceptions.RequestException as exc:
            tried[path] = {"status": 0, "error": str(exc)[:120]}

    feed_path, feed_ct = _find_yolo_feed_path()
    if feed_path:
        return jsonify({"reachable": True, "endpoint": feed_path, "content_type": feed_ct, "tried": tried})
    return jsonify({"reachable": False, "error": f"No MJPEG feed found on {_YOLO_SERVER}", "tried": tried}), 502


@app.route("/proxy/yolo-stream")
@login_required
def proxy_yolo_stream():
    """Proxy the MJPEG video feed from the YOLO inference server."""
    from flask import Response as FlaskResponse
    feed_path, _ = _find_yolo_feed_path()
    if feed_path is None:
        logging.error("YOLO proxy: no MJPEG feed path on %s", _YOLO_SERVER)
        return jsonify({"error": "YOLO server unavailable"}), 502
    try:
        upstream = requests.get(
            f"{_YOLO_SERVER}{feed_path}",
            stream=True,
            timeout=(5, None),
        )
        return FlaskResponse(
            upstream.iter_content(chunk_size=4096),
            content_type=upstream.headers.get(
                "Content-Type", "multipart/x-mixed-replace; boundary=frame"
            ),
        )
    except requests.exceptions.RequestException as exc:
        logging.error("YOLO proxy error: %s", exc)
        return jsonify({"error": "YOLO server unavailable"}), 502


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
    return render_template("history.html", user=user, sessions=sessions_list)


@app.route("/reports")
@login_required
def reports():
    user = current_user()
    stats = db.get_dashboard_stats(user["id"])
    subjects = db.get_subjects(user["id"])
    sessions_list = db.get_sessions(user["id"])
    return render_template("reports.html", user=user, stats=stats, subjects=subjects, sessions=sessions_list)


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


# ─── API Endpoints ───────────────────────────────────────────────────

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
    data = request.get_json()
    s = db.create_session(data["subjectId"])
    return jsonify(s, default=str), 201


@app.route("/api/sessions/<int:session_id>/end", methods=["POST"])
@login_required
def api_end_session(session_id):
    data = request.get_json()
    s = db.end_session(session_id, data.get("summaryStats", {}))
    return jsonify(s, default=str)


# ─── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
