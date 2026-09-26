import os
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv()

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_USER_ID", "0").strip()
try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

# Database Configuration (Turso or Local SQLite fallback)
TURSO_DB_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

# Residential Rotating Proxy (Turnoxy)
PROXY_PRIMARY = os.getenv(
    "PROXY_PRIMARY", 
    "http://sub_Hzu7N0Hx:Rujm61dQa861evho@gate.turnoxy.com:1318"
).strip()

PROXY_BACKUP = os.getenv("PROXY_BACKUP", "").strip()

# Port for Render Free Web Service keep-alive
PORT = int(os.getenv("PORT", "8080"))
