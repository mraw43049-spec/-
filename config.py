import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

REQUIRED_CHANNEL = os.environ.get("REQUIRED_CHANNEL", "@fox_frenzy").strip()
REQUIRED_CHANNEL_URL = os.environ.get("REQUIRED_CHANNEL_URL", "https://t.me/fox_frenzy").strip()

CLAIM_KEYWORD = os.environ.get("CLAIM_KEYWORD", "هور").strip()
CLAIM_COOLDOWN_SECONDS = int(os.environ.get("CLAIM_COOLDOWN_SECONDS", "300"))
CLAIM_POINTS_MIN = int(os.environ.get("CLAIM_POINTS_MIN", "5"))
CLAIM_POINTS_MAX = int(os.environ.get("CLAIM_POINTS_MAX", "15"))

ADMIN_IDS = {
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
