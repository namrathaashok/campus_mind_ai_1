import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dsu_campuspulse_secret_key_default_change_me")
    
    # Detect Vercel serverless environment (only /tmp is writable)
    IS_VERCEL = os.getenv("VERCEL", "") == "1"
    
    # Database
    if IS_VERCEL:
        INSTANCE_PATH = Path("/tmp/instance")
        DATABASE_PATH = INSTANCE_PATH / "campuspulse.db"
    else:
        INSTANCE_PATH = BASE_DIR / "instance"
        DATABASE_PATH = INSTANCE_PATH / "campuspulse.db"
    
    # Campus Details
    CAMPUS_NAME = os.getenv("CAMPUS_NAME", "Dayananda Sagar University")
    CAMPUS_LOCATION = os.getenv("CAMPUS_LOCATION", "Bengaluru, Karnataka, India")
    DEFAULT_CAMPUS_LAT = float(os.getenv("DEFAULT_CAMPUS_LAT", "12.6582"))
    DEFAULT_CAMPUS_LNG = float(os.getenv("DEFAULT_CAMPUS_LNG", "77.4475"))
    DEFAULT_MAP_ZOOM = int(os.getenv("DEFAULT_MAP_ZOOM", "17"))
    
    # Secondary Campus (City Campus - Kudlu Gate, Bengaluru)
    CITY_CAMPUS_LAT = float(os.getenv("CITY_CAMPUS_LAT", "12.8906"))
    CITY_CAMPUS_LNG = float(os.getenv("CITY_CAMPUS_LNG", "77.6416"))
    
    # AI Service Settings
    AI_PROVIDER = os.getenv("AI_PROVIDER", "rule_based")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()

    # Optional passwords for seeded sample accounts; unset values are randomized.
    SEEDED_ADMIN_PASSWORD = os.getenv("SEEDED_ADMIN_PASSWORD", "admin@123").strip()
    SEEDED_STAFF_PASSWORD = os.getenv("SEEDED_STAFF_PASSWORD", "").strip()
    SEEDED_STUDENT_PASSWORD = os.getenv("SEEDED_STUDENT_PASSWORD", "").strip()

    # Gmail SMTP credentials for password recovery email.
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
    
    # Uploads
    if IS_VERCEL:
        UPLOAD_FOLDER = Path("/tmp/uploads")
    else:
        UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    
    # Session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

class TestingConfig(Config):
    TESTING = True
    DATABASE_PATH = BASE_DIR / "instance" / "test_campuspulse.db"
    WTF_CSRF_ENABLED = False
    SEEDED_ADMIN_PASSWORD = "admin@123"
    SEEDED_STAFF_PASSWORD = "test-staff-password"
    SEEDED_STUDENT_PASSWORD = "test-student-password"
