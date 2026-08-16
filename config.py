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
    if _db_url:
        if _db_url.startswith("postgres://"):
            _db_url = _db_url.replace("postgres://", "postgresql+pg8000://", 1)
        elif _db_url.startswith("postgresql://") and not _db_url.startswith("postgresql+"):
            _db_url = _db_url.replace("postgresql://", "postgresql+pg8000://", 1)
        
        # If pg8000 is used with query params like ?sslmode=require, clean params for pg8000
        if "postgresql+pg8000://" in _db_url and "?" in _db_url:
            _db_url = _db_url.split("?")[0]

        SQLALCHEMY_DATABASE_URI = _db_url
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl_context": True}}
    elif os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/portfolio.db"
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'portfolio.db')}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session cookie hardening. Vercel terminates TLS, so the Secure flag is
    # only enabled there; locally (plain http) it would break the session.
    _on_serverless = bool(
        os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    )
    SESSION_COOKIE_SECURE = _on_serverless
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _on_serverless
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

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
