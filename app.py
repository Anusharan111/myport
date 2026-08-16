import os
import re
import unicodedata
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request, flash, abort,
    send_from_directory, Response
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename

from config import Config
from models import db, Admin, Profile, Skill, Project, Message, LoginAttempt

try:
    from vercel_blob import put as blob_put, delete as blob_delete
except ImportError:
    blob_put = blob_delete = None

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "admin_login"
login_manager.login_message = "Please log in to access the admin panel."
login_manager.login_message_category = "error"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))


# ---------------------------------------------------------------------------
# Database bootstrap
# ---------------------------------------------------------------------------
# Vercel runs the app as a serverless function, so there is no shell to run
# `flask init-db`. Instead, tables + default admin/profile are created on boot.
# On Vercel, set ADMIN_USERNAME / ADMIN_PASSWORD env vars to choose your login.

from io import BytesIO
import base64
from sqlalchemy import text

try:
    from PIL import Image
except ImportError:
    Image = None


def init_db_data():
    try:
        with app.app_context():
            db.create_all()

            # Migrate column types to TEXT if created originally as VARCHAR(255)
            try:
                db.session.execute(text("ALTER TABLE profile ALTER COLUMN profile_image TYPE TEXT;"))
                db.session.execute(text("ALTER TABLE project ALTER COLUMN image TYPE TEXT;"))
                db.session.commit()
            except Exception:
                db.session.rollback()

            if not Admin.query.first():
                admin = Admin(username=os.environ.get("ADMIN_USERNAME", "admin"))
                admin.set_password(os.environ.get("ADMIN_PASSWORD", "admin123"))
                db.session.add(admin)
            if not Profile.query.first():
                db.session.add(Profile())
            db.session.commit()
    except Exception as e:
        app.logger.error(f"Database bootstrap warning: {e}")


init_db_data()


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "object-src 'none'",
    )
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def save_upload(file_storage, folder):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        flash("Unsupported image type. Use png, jpg, jpeg, gif, webp or svg.", "error")
        return None

    ext = file_storage.filename.rsplit(".", 1)[1].lower()

    # 1. Use Vercel Blob if token is available
    if app.config.get("BLOB_READ_WRITE_TOKEN") and blob_put is not None:
        try:
            filename = secure_filename(file_storage.filename)
            base, ext_name = os.path.splitext(filename)
            unique_name = f"{base}-{os.urandom(4).hex()}{ext_name}"
            blob = blob_put(
                unique_name,
                file_storage.stream,
                {"access": "public", "addRandomSuffix": True},
            )
            return blob["url"]
        except Exception:
            pass

    # 2. Store image directly as base64 data URL in PostgreSQL (persists across serverless cold starts)
    try:
        file_bytes = file_storage.read()
        if not file_bytes:
            return None

        # Compress and resize if Pillow is available
        if Image is not None and ext in ("jpg", "jpeg", "png", "webp"):
            try:
                img = Image.open(BytesIO(file_bytes))
                if img.mode in ("RGBA", "P") and ext in ("jpg", "jpeg"):
                    img = img.convert("RGB")
                img.thumbnail((1200, 1200))
                buf = BytesIO()
                save_fmt = "PNG" if ext == "png" else ("WEBP" if ext == "webp" else "JPEG")
                img.save(buf, format=save_fmt, quality=82, optimize=True)
                file_bytes = buf.getvalue()
            except Exception:
                pass

        mime = "image/jpeg" if ext in ("jpg", "jpeg") else ("image/svg+xml" if ext == "svg" else f"image/{ext}")
        encoded = base64.b64encode(file_bytes).decode("utf-8")
        return f"data:{mime};base64,{encoded}"
    except Exception as err:
        app.logger.error(f"Image upload error: {err}")
        flash("Image processing failed. Please try again or use an image URL.", "error")
        return None


def delete_media(stored_value):
    """Remove an image from Vercel Blob (no-op for database data URLs or local files)."""
    if not stored_value or not app.config.get("BLOB_READ_WRITE_TOKEN") or blob_delete is None:
        return
    if stored_value.startswith(("http://", "https://")) and "vercel-storage.com" in stored_value:
        try:
            blob_delete(stored_value)
        except Exception:
            pass


@app.template_filter("media_url")
def media_url(value, folder):
    """Render a stored image: Base64 data URL, full HTTP URL, or local static file."""
    if not value:
        return ""
    if value.startswith(("http://", "https://", "data:")):
        return value
    return url_for("static", filename=f"uploads/{folder}/{value}")


@app.context_processor
def inject_now_year():
    return {"now_year": datetime.utcnow().year}


def get_profile():
    profile = Profile.query.first()
    if not profile:
        profile = Profile()
        db.session.add(profile)
        db.session.commit()
    return profile


# ---------------------------------------------------------------------------
# Security.txt
# ---------------------------------------------------------------------------

@app.route("/.well-known/security.txt")
def security_txt():
    email = get_profile().email or "security@example.com"
    canonical = request.host_url.rstrip("/") + "/.well-known/security.txt"
    content = (
        "Contact: mailto:" + email + "\n"
        "Preferred-Languages: en\n"
        "Canonical: " + canonical + "\n"
        "Policy: " + canonical + "\n"
        "Expires: 2027-08-16T00:00:00.000Z\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/security.txt")
def security_txt_redirect():
    return redirect(url_for("security_txt"))


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    profile = get_profile()
    featured_projects = (
        Project.query.filter_by(featured=True).order_by(Project.sort_order, Project.id.desc()).all()
    )
    skills = Skill.query.order_by(Skill.sort_order, Skill.category).all()
    return render_template(
        "index.html", profile=profile, projects=featured_projects, skills=skills
    )


@app.route("/projects")
def projects():
    profile = get_profile()
    all_projects = Project.query.order_by(Project.sort_order, Project.id.desc()).all()
    return render_template("projects.html", profile=profile, projects=all_projects)


@app.route("/projects/<slug>")
def project_detail(slug):
    profile = get_profile()
    project = Project.query.filter_by(slug=slug).first_or_404()
    return render_template("project_detail.html", profile=profile, project=project)


@app.route("/about")
def about():
    profile = get_profile()
    skills = Skill.query.order_by(Skill.sort_order, Skill.category).all()
    return render_template("about.html", profile=profile, skills=skills)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    profile = get_profile()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("message", "").strip()

        if not name or not email or not body:
            flash("Please fill in your name, email and message.", "error")
            return render_template("contact.html", profile=profile), 400

        msg = Message(name=name, email=email, subject=subject, body=body)
        db.session.add(msg)
        db.session.commit()
        flash("Thanks for reaching out! I'll get back to you soon.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", profile=profile)


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

LOGIN_ATTEMPT_LIMIT = 10
LOGIN_ATTEMPT_WINDOW_MINUTES = 15


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def safe_next(target):
    """Allow only same-site relative redirects (blocks open redirects)."""
    if not target or target.startswith("//"):
        return None
    return target if target.startswith("/") else None


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        ip = client_ip()
        since = datetime.utcnow() - timedelta(minutes=LOGIN_ATTEMPT_WINDOW_MINUTES)
        recent_failures = LoginAttempt.query.filter(
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at > since,
        ).count()

        if recent_failures >= LOGIN_ATTEMPT_LIMIT:
            flash(
                "Too many failed login attempts. Please wait a few minutes and try again.",
                "error",
            )
            return render_template("admin/login.html"), 429

        # Keep the attempts table small
        LoginAttempt.query.filter(
            LoginAttempt.created_at < datetime.utcnow() - timedelta(hours=24)
        ).delete()

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(username=username).first()

        if admin and admin.check_password(password):
            LoginAttempt.query.filter(LoginAttempt.ip == ip).delete()
            db.session.add(LoginAttempt(ip=ip, username=username, success=True))
            db.session.commit()
            login_user(admin)
            return redirect(safe_next(request.args.get("next")) or url_for("admin_dashboard"))

        db.session.add(LoginAttempt(ip=ip, username=username, success=False))
        db.session.commit()
        flash("Invalid username or password.", "error")

    return render_template("admin/login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@app.route("/admin")
@login_required
def admin_dashboard():
    stats = {
        "projects": Project.query.count(),
        "skills": Skill.query.count(),
        "messages": Message.query.count(),
        "unread": Message.query.filter_by(is_read=False).count(),
    }
    recent_messages = Message.query.order_by(Message.created_at.desc()).limit(5).all()
    return render_template("admin/dashboard.html", stats=stats, recent_messages=recent_messages)


# --- Profile ---------------------------------------------------------------

@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    profile = get_profile()
    if request.method == "POST":
        profile.name = request.form.get("name", "").strip()
        profile.title = request.form.get("title", "").strip()
        profile.tagline = request.form.get("tagline", "").strip()
        profile.bio = request.form.get("bio", "").strip()
        profile.email = request.form.get("email", "").strip()
        profile.phone = request.form.get("phone", "").strip()
        profile.location = request.form.get("location", "").strip()
        profile.github_url = request.form.get("github_url", "").strip()
        profile.linkedin_url = request.form.get("linkedin_url", "").strip()
        profile.twitter_url = request.form.get("twitter_url", "").strip()
        profile.resume_url = request.form.get("resume_url", "").strip()

        image_url = request.form.get("profile_image_url", "").strip()
        if image_url:
            delete_media(profile.profile_image)
            profile.profile_image = image_url
        else:
            image_file = request.files.get("profile_image")
            saved_name = save_upload(image_file, app.config["UPLOAD_FOLDER_PROFILE"])
            if saved_name:
                delete_media(profile.profile_image)
                profile.profile_image = saved_name

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("admin_profile"))

    return render_template("admin/profile.html", profile=profile)


# --- Projects ----------------------------------------------------------

@app.route("/admin/projects")
@login_required
def admin_projects():
    all_projects = Project.query.order_by(Project.sort_order, Project.id.desc()).all()
    return render_template("admin/projects.html", projects=all_projects)


@app.route("/admin/projects/new", methods=["GET", "POST"])
@login_required
def admin_project_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template("admin/project_form.html", project=None)

        slug = slugify(title)
        base_slug = slug
        counter = 1
        while Project.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        project = Project(
            title=title,
            slug=slug,
            summary=request.form.get("summary", "").strip(),
            description=request.form.get("description", "").strip(),
            tech_stack=request.form.get("tech_stack", "").strip(),
            github_link=request.form.get("github_link", "").strip(),
            live_link=request.form.get("live_link", "").strip(),
            featured=bool(request.form.get("featured")),
            sort_order=int(request.form.get("sort_order") or 0),
        )

        image_url = request.form.get("image_url", "").strip()
        if image_url:
            project.image = image_url
        else:
            image_file = request.files.get("image")
            saved_name = save_upload(image_file, app.config["UPLOAD_FOLDER_PROJECTS"])
            if saved_name:
                project.image = saved_name

        db.session.add(project)
        db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("admin_projects"))

    return render_template("admin/project_form.html", project=None)


@app.route("/admin/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def admin_project_edit(project_id):
    project = db.session.get(Project, project_id) or abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template("admin/project_form.html", project=project)

        project.title = title
        project.summary = request.form.get("summary", "").strip()
        project.description = request.form.get("description", "").strip()
        project.tech_stack = request.form.get("tech_stack", "").strip()
        project.github_link = request.form.get("github_link", "").strip()
        project.live_link = request.form.get("live_link", "").strip()
        project.featured = bool(request.form.get("featured"))
        project.sort_order = int(request.form.get("sort_order") or 0)

        image_url = request.form.get("image_url", "").strip()
        if image_url:
            delete_media(project.image)
            project.image = image_url
        else:
            image_file = request.files.get("image")
            saved_name = save_upload(image_file, app.config["UPLOAD_FOLDER_PROJECTS"])
            if saved_name:
                delete_media(project.image)
                project.image = saved_name

        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("admin_projects"))

    return render_template("admin/project_form.html", project=project)


@app.route("/admin/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def admin_project_delete(project_id):
    project = db.session.get(Project, project_id) or abort(404)
    delete_media(project.image)
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted.", "success")
    return redirect(url_for("admin_projects"))


@app.route("/admin/projects/reorder", methods=["POST"])
@login_required
def admin_projects_reorder():
    """Set the display order of projects (used on the home page)."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        return {"ok": False, "error": "Invalid payload."}, 400
    try:
        ids = [int(pid) for pid in ids]
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid payload."}, 400
    for position, project_id in enumerate(ids):
        project = db.session.get(Project, project_id)
        if project:
            project.sort_order = position
    db.session.commit()
    return {"ok": True}


# --- Skills --------------------------------------------------------------

@app.route("/admin/skills", methods=["GET", "POST"])
@login_required
def admin_skills():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            skill = Skill(
                name=name,
                category=request.form.get("category", "General").strip() or "General",
                proficiency=int(request.form.get("proficiency") or 80),
                sort_order=int(request.form.get("sort_order") or 0),
            )
            db.session.add(skill)
            db.session.commit()
            flash("Skill added.", "success")
        return redirect(url_for("admin_skills"))

    all_skills = Skill.query.order_by(Skill.sort_order, Skill.category).all()
    return render_template("admin/skills.html", skills=all_skills)


@app.route("/admin/skills/<int:skill_id>/delete", methods=["POST"])
@login_required
def admin_skill_delete(skill_id):
    skill = db.session.get(Skill, skill_id) or abort(404)
    db.session.delete(skill)
    db.session.commit()
    flash("Skill removed.", "success")
    return redirect(url_for("admin_skills"))


# --- Messages --------------------------------------------------------------

@app.route("/admin/messages")
@login_required
def admin_messages():
    all_messages = Message.query.order_by(Message.created_at.desc()).all()
    return render_template("admin/messages.html", messages=all_messages)


@app.route("/admin/messages/<int:message_id>/read", methods=["POST"])
@login_required
def admin_message_read(message_id):
    msg = db.session.get(Message, message_id) or abort(404)
    msg.is_read = True
    db.session.commit()
    return redirect(url_for("admin_messages"))


@app.route("/admin/messages/<int:message_id>/delete", methods=["POST"])
@login_required
def admin_message_delete(message_id):
    msg = db.session.get(Message, message_id) or abort(404)
    db.session.delete(msg)
    db.session.commit()
    flash("Message deleted.", "success")
    return redirect(url_for("admin_messages"))


# --- Change password ---------------------------------------------------

@app.route("/admin/account", methods=["GET", "POST"])
@login_required
def admin_account():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "error")
        elif len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new_password != confirm_password:
            flash("New passwords do not match.", "error")
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash("Password updated.", "success")
        return redirect(url_for("admin_account"))

    return render_template("admin/account.html")


# ---------------------------------------------------------------------------
# CLI: create the database & a default admin user
# ---------------------------------------------------------------------------

@app.cli.command("init-db")
def init_db():
    """Create tables and a default admin user (username: admin / password: admin123)."""
    init_db_data()
    print(
        f"Database initialized. Login with username "
        f"'{os.environ.get('ADMIN_USERNAME', 'admin')}' and password "
        f"'{os.environ.get('ADMIN_PASSWORD', 'admin123')}'."
    )
    print("IMPORTANT: change this password immediately after logging in.")


if __name__ == "__main__":
    app.run(debug=True)
