import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
MEDIA_DIR = DATA_DIR / "media"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = os.getenv("APP_NAME", "مساعد جاوا")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Amman")

# Public https address of this app. Instagram downloads your photos/videos from here.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

def _env(name, default=""):
    """Pasted keys often carry stray spaces or line breaks; those break HTTP headers."""
    return "".join((os.getenv(name) or default).split())


ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
MODEL = _env("MODEL", "claude-sonnet-5-5")

COMPOSIO_API_KEY = _env("COMPOSIO_API_KEY")
COMPOSIO_USER_ID = _env("COMPOSIO_USER_ID") or None
COMPOSIO_CONNECTED_ACCOUNT_ID = _env("COMPOSIO_CONNECTED_ACCOUNT_ID") or None
# For Composio Connect keys (ck_...): which Instagram connection to use (the old one is dead).
COMPOSIO_ACCOUNT = _env("COMPOSIO_ACCOUNT", "instagram_fluted-tipman")
IG_USER_ID = os.getenv("IG_USER_ID", "17841434449825074")
IG_USERNAME = os.getenv("IG_USERNAME", "jawapress")

# Set to 1 to run without real Instagram/Claude calls (for trying the app).
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"

BUSINESS_FACTS = """- الاسم: معاصر جاوا – مزارع نبيل سكجها، خبرة من سنة 1984
- فاتحين 24 ساعة كل يوم
- التلفون: 0789302000
- الموقع: https://maps.app.goo.gl/iqBKj3DHkPxq4thX6
- الأسعار (بالخاص بس، أبداً مش بالتعليقات): تنكة زيت الزيتون 120 دينار؛ العصر 75 قرش لكل كيلو زيت صافي"""
