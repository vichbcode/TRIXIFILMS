import os
from datetime import timedelta


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _default_db_url():
    default_path = os.path.join(APP_DIR, "trixifilms.db").replace(os.sep, "/")
    try:
        with open(default_path, "a"):
            pass
    except (OSError, PermissionError):
        tmp_path = f"/tmp/trixifilms.db"
        return f"sqlite:///{tmp_path}"
    return f"sqlite:///{default_path}"


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        _default_db_url()
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    CLOUDINARY_FOLDER = os.environ.get("CLOUDINARY_FOLDER", "trixifilms").strip()
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    MAX_PIXEL_COUNT = 6000 * 6000
    LOCKOUT_THRESHOLD = 8
    LOCKOUT_WINDOW = 15 * 60
    LOCKOUT_DURATION = 30 * 60
    ADD_THRESHOLD = 5
    ADD_WINDOW = 10 * 60
    ADD_BLOCK_DURATION = 30 * 60


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True


class DevelopmentConfig(Config):
    pass
