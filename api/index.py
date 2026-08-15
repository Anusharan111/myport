import sys
import os

# Ensure root directory is on the python search path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app


class VercelPathFix:
    """Fix PATH_INFO when Vercel serverless rewrites /(.*) to /api/index."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")
        if path_info.startswith("/api/index"):
            environ["PATH_INFO"] = path_info[len("/api/index") :] or "/"
        elif path_info == "/api" or path_info == "/api/":
            environ["PATH_INFO"] = "/"
        return self.wsgi_app(environ, start_response)


app.wsgi_app = VercelPathFix(app.wsgi_app)

