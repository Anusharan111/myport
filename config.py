import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Set a long random string in Vercel env vars (SECRET_KEY) before deploying!
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-to-a-random-secret-key")

    # Database URI:
    # 1) If DATABASE_URL is set (Postgres from Neon/Supabase/Vercel Postgres), use it.
    # 2) On Vercel serverless without DATABASE_URL, fallback to /tmp/portfolio.db (writable).
    # 3) Locally, fallback to BASE_DIR/portfolio.db.
    _db_url = os.environ.get("DATABASE_URL")
    if _db_url and _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)

    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    elif os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/portfolio.db"
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'portfolio.db')}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Vercel: set BLOB_READ_WRITE_TOKEN (from a Vercel Blob Store) so uploaded
    # images persist. Without it, uploads are stored on disk.
    BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")

    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        UPLOAD_FOLDER_PROJECTS = "/tmp/uploads/projects"
        UPLOAD_FOLDER_PROFILE = "/tmp/uploads/profile"
    else:
        UPLOAD_FOLDER_PROJECTS = os.path.join(BASE_DIR, "static", "uploads", "projects")
        UPLOAD_FOLDER_PROFILE = os.path.join(BASE_DIR, "static", "uploads", "profile")

    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6 MB upload limit
