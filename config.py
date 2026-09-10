import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

CLAIM_KEYWORD = os.environ.get("CLAIM_KEYWORD", "هور").strip()
CLAIM_COOLDOWN_SECONDS = int(os.environ.get("CLAIM_COOLDOWN_SECONDS", "300"))

# حداقل و حداکثر پوینتی که هر بار claim به کاربر میده
CLAIM_POINTS_MIN = 5
CLAIM_POINTS_MAX = 15
