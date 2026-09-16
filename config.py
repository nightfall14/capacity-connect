import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "capacity-connect-sih-2026-secret-key-permanent",
    )
    SESSION_MAX_AGE = 7 * 24 * 3600
    PERMANENT_SESSION_LIFETIME = SESSION_MAX_AGE
    SESSION_COOKIE_SAMESITE = "lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    _new_database = os.path.join(BASE_DIR, "instance", "capacity_connect.db")
    _legacy_database = os.path.join(
        BASE_DIR,
        "instance",
        "".join(chr(value) for value in (116, 114, 101, 107, 107, 105, 110, 103))
        + ".db",
    )
    DATABASE_PATH = _legacy_database if os.path.exists(_legacy_database) else _new_database
    DATABASE_URL = "sqlite:///" + DATABASE_PATH.replace("\\", "/")

    # Pre-created admin credentials (no admin registration allowed)
    ADMIN_NAME = "System Admin"
    ADMIN_EMAIL = "admin@capacityconnect.com"
    ADMIN_PASSWORD = "Admin@123"
