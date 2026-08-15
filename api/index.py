import sys
import os

# Ensure project root is on Python path so `from app import app` works
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app as application

# Vercel's @vercel/python runtime looks for `app` by convention
app = application
