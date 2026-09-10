import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot.db').strip()
REQUIRED_CHANNEL = os.getenv('REQUIRED_CHANNEL', '@fox_frenzy').strip()
REQUIRED_CHANNEL_URL = os.getenv('REQUIRED_CHANNEL_URL', 'https://t.me/fox_frenzy').strip()
CLAIM_KEYWORD = os.getenv('CLAIM_KEYWORD', 'پوینت').strip()
CLAIM_COOLDOWN_SECONDS = int(os.getenv('CLAIM_COOLDOWN_SECONDS', '300'))
CLAIM_POINTS_MIN = int(os.getenv('CLAIM_POINTS_MIN', '10'))
CLAIM_POINTS_MAX = int(os.getenv('CLAIM_POINTS_MAX', '25'))
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
