import logging
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Float, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DATABASE_URL

logger = logging.getLogger(__name__)

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]

if DATABASE_URL.startswith('postgresql://'):
    try:
        import psycopg  # noqa: F401
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
    except ImportError:
        # هشدار جدی: یعنی DATABASE_URL روی Postgres تنظیم شده ولی درایور psycopg
        # نصب نیست، پس ربات مجبوره برگرده روی SQLite محلی که با هر دیپلوی پاک می‌شه.
        # این دیگه بی‌صدا انجام نمی‌شه تا تو لاگ‌های Railway حتماً دیده بشه.
        logger.error(
            "psycopg نصب نیست ولی DATABASE_URL روی Postgres تنظیم شده! "
            "در حال بازگشت اضطراری به SQLite محلی (bot.db) هستیم — "
            "این یعنی داده‌ها با دیپلوی بعدی پاک می‌شن. "
            "psycopg[binary] رو به requirements.txt اضافه کن و دوباره دیپلوی کن."
        )
        DATABASE_URL = 'sqlite:///bot.db'

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# نوع ستون تاریخ/زمان برای ALTER TABLE خام: روی Postgres باید TIMESTAMP WITH TIME ZONE باشه،
# چون "DATETIME" روی Postgres اصلاً نوع معتبری نیست و باعث کرش init_db می‌شه.
DT_SQL_TYPE = 'TIMESTAMP WITH TIME ZONE' if engine.dialect.name == 'postgresql' else 'DATETIME'

class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    name_flag = Column(String, nullable=False, default='')
    name_emoji = Column(String, nullable=False, default='')
    emoji_storage_capacity = Column(Integer, nullable=False, default=3)
    first_name = Column(String, nullable=True)
    points = Column(Integer, nullable=False, default=0)
    total_earned = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=1)
    last_claim_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # داده‌های روباه؛ همه nullable/default هستند تا دیتابیس قبلی بدون حذف کاربران مهاجرت کند.
    fox_name = Column(String, nullable=False, default='مکار')
    fox_level = Column(Integer, nullable=False, default=1)
    fox_belly = Column(Integer, nullable=False, default=3)
    fox_belly_capacity = Column(Integer, nullable=False, default=3)
    fox_points = Column(Integer, nullable=False, default=0)
    fox_storage = Column(Integer, nullable=False, default=0)
    fox_total_earned = Column(Integer, nullable=False, default=0)
    fox_production_remainder = Column(Float, nullable=False, default=0.0)
    fox_last_production_at = Column(DateTime(timezone=True), nullable=True)
    last_hunt_at = Column(DateTime(timezone=True), nullable=True)
    last_transfer_at = Column(DateTime(timezone=True), nullable=True)
    last_fox_claim_at = Column(DateTime(timezone=True), nullable=True)
    fox_claim_count = Column(Integer, nullable=False, default=0)
    hunt_count = Column(Integer, nullable=False, default=0)
    fox_rescued_count = Column(Integer, nullable=False, default=0)
    fox_prestige_count = Column(Integer, nullable=False, default=0)
    fox_last_hunger_at = Column(DateTime(timezone=True), nullable=True)
    wheel_last_spin_at = Column(DateTime(timezone=True), nullable=True)
    wheel_last_reward = Column(Integer, nullable=True)
    last_ruby_game_at = Column(DateTime(timezone=True), nullable=True)
    last_casino_game_at = Column(DateTime(timezone=True), nullable=True)

    # مریضی روباه (از لول 6 به بعد، هر 48 ساعت یک‌بار)
    fox_sick_since = Column(DateTime(timezone=True), nullable=True)
    fox_sick_reason = Column(String, nullable=True)
    fox_sick_treatment = Column(String, nullable=True)  # pill | syrup | rest
    fox_sick_doses_given = Column(Integer, nullable=False, default=0)
    fox_sick_next_dose_at = Column(DateTime(timezone=True), nullable=True)
    fox_sick_rest_until = Column(DateTime(timezone=True), nullable=True)
    fox_last_sick_at = Column(DateTime(timezone=True), nullable=True)

    # یخچال روبی (از سطح 7 کاربر باز می‌شود)
    fridge_level = Column(Integer, nullable=False, default=1)

    # کارخونه روبی (از سطح 10 کاربر باز می‌شود)
    factory_built = Column(Integer, nullable=False, default=0)
    factory_build_started_at = Column(DateTime(timezone=True), nullable=True)
    factory_storage_level = Column(Integer, nullable=False, default=1)
    factory_workers_level = Column(Integer, nullable=False, default=1)
    factory_machine_level = Column(Integer, nullable=False, default=1)
    factory_produced_total = Column(Integer, nullable=False, default=0)

    # بن دائم (فروشگاه گیفت: تخلف در ارسال رسید) یا محرومیت موقت توسط پشتیبانی
    is_banned = Column(Integer, nullable=False, default=0)
    banned_until = Column(DateTime(timezone=True), nullable=True)
    # زندان روبی و ضداسپم
    jail_until = Column(DateTime(timezone=True), nullable=True)
    jail_reason = Column(String, nullable=True)
    jail_fine = Column(Integer, nullable=False, default=0)
    jail_arrested_at = Column(DateTime(timezone=True), nullable=True)
    injured_fox_stock = Column(Integer, nullable=False, default=0)
    spam_window_at = Column(DateTime(timezone=True), nullable=True)
    spam_count = Column(Integer, nullable=False, default=0)

class RubyEmojiItem(Base):
    __tablename__ = 'ruby_emoji_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False, index=True)
    item_key = Column(String, nullable=False)
    emoji = Column(String, nullable=False)
    category = Column(String, nullable=False)
    purchased_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Challenge(Base):
    __tablename__ = 'challenges'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    game_type = Column(String, nullable=False)
    player1_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    player2_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=True)
    player1_score = Column(Integer, nullable=True)
    player2_score = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class GroupChat(Base):
    __tablename__ = 'group_chats'
    chat_id = Column(BigInteger, primary_key=True)
    title = Column(String, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # ---------- شهر روبی ----------
    city_owner_id = Column(BigInteger, nullable=True)
    city_owner_name = Column(String, nullable=True)
    city_level = Column(Integer, nullable=False, default=1)
    city_claim_total = Column(Integer, nullable=False, default=0)    # مجموع روب روب‌های این گپ
    city_rescued_total = Column(Integer, nullable=False, default=0)  # مجموع روباه‌های زخمی نجات‌یافته این گپ
    city_hunt_total = Column(Integer, nullable=False, default=0)     # مجموع شکارهای این گپ
    city_treasury = Column(Integer, nullable=False, default=0)       # خزانه شهر
    city_donors = Column(String, nullable=True, default='')          # آیدی دونیت‌کننده‌های این چرخه (تا ارتقا بعدی)
    # ---------- انتخابات شهرداری (از سطح شهر 5 به بعد) ----------
    city_mayor_id = Column(BigInteger, nullable=True)                 # آیدی شهردار منتخب فعلی
    city_mayor_name = Column(String, nullable=True)                   # نام نمایشی شهردار فعلی
    city_mayor_source = Column(String, nullable=False, default='owner') # owner | transferred
    city_mayor_term_ends_at = Column(DateTime(timezone=True), nullable=True)  # پایان دوره 3 روزه شهردار فعلی
    city_election_status = Column(String, nullable=False, default='none')     # none | candidacy | voting
    city_election_candidates = Column(String, nullable=True, default='')      # آیدی کاندیدها با کاما جدا شده (به ترتیب ثبت‌نام)
    city_election_votes = Column(String, nullable=True, default='')           # "رای‌دهنده:کاندید" با کاما جدا شده
    city_election_candidacy_ends_at = Column(DateTime(timezone=True), nullable=True)  # مهلت ثبت‌نام کاندیدها
    city_election_voting_ends_at = Column(DateTime(timezone=True), nullable=True)     # مهلت رای‌گیری (حداکثر 5 ساعت)
    # ---------- ناظر هوشمند گروه (پیش‌فرض خاموش؛ ادمین گروه روشنش می‌کند) ----------
    ai_mod = Column(Integer, nullable=False, default=0)
    # غلط‌گیر املایی: -1 = طبق پیش‌فرض ربات (FOX_SPELL_DEFAULT)، 0 = خاموش، 1 = روشن
    spell_mod = Column(Integer, nullable=False, default=-1)




class RubyTable(Base):
    __tablename__ = 'ruby_tables'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    game_type = Column(String, nullable=False)
    creator_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    max_players = Column(Integer, nullable=False, default=2)
    players = Column(String, nullable=False, default='')
    status = Column(String, nullable=False, default='open')
    entry_amount = Column(Integer, nullable=False, default=0)
    pot = Column(Integer, nullable=False, default=0)
    scores = Column(String, nullable=True, default='')
    message_id = Column(BigInteger, nullable=True)
    state = Column(String, nullable=True, default='')
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class FriendRequest(Base):
    __tablename__ = 'friend_requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    receiver_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    status = Column(String, nullable=False, default='pending')  # pending | accepted | rejected
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime(timezone=True), nullable=True)

class Friendship(Base):
    __tablename__ = 'friendships'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user1_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    user2_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    last_action_user1_at = Column(DateTime(timezone=True), nullable=True)
    last_action_user2_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class GiftCode(Base):
    __tablename__ = 'gift_codes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, nullable=False, unique=True, index=True)
    reward = Column(Integer, nullable=False, default=0)
    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    active = Column(Integer, nullable=False, default=1)
    expires_at = Column(DateTime(timezone=True), nullable=True)   # None = بدون محدودیت زمانی

class FoxKnowledge(Base):
    """پاسخ‌های دستی که ادمین به روباه یاد می‌دهد («یاد بگیر: کلید | جواب»)."""
    __tablename__ = 'fox_knowledge'
    id = Column(Integer, primary_key=True, autoincrement=True)
    keywords = Column(String, nullable=False)     # کلیدها؛ هر خط یک کلید
    answer = Column(String, nullable=False)       # برای مدیا: کپشن (می‌تواند خالی باشد)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # مدیا (آهنگ/ویدیو/گیف/استیکر/...): اگه file_id پر باشه، روباه به‌جای متن این فایل را می‌فرستد
    media_type = Column(String, nullable=True)     # audio | video | animation | sticker | voice | photo | document
    file_id = Column(String, nullable=True)
    file_unique_id = Column(String, nullable=True)

class FoxMoodSong(Base):
    """آهنگ‌هایی که پشتیبانی برای «روباهیو حال» اضافه می‌کنه؛ هر آهنگ یک یا چند حال (happy,calm,sad,energy,love,rage) داره."""
    __tablename__ = 'fox_mood_songs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    moods = Column(String, nullable=False)          # مثلاً "happy,energy"
    media_type = Column(String, nullable=False)     # audio | document
    file_id = Column(String, nullable=False)
    file_unique_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class FoxMoodChannel(Base):
    """کانال‌هایی که ادمین ربات، ربات رو توش ادمین کرده؛ آهنگ‌های این کانال‌ها با هشتگ حال (#شاد ...) خودکار به «روباهیو حال» اضافه می‌شن."""
    __tablename__ = 'fox_mood_channels'
    chat_id = Column(BigInteger, primary_key=True, autoincrement=False)
    title = Column(String, nullable=True)
    added_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class GiftCodeRedemption(Base):
    __tablename__ = 'gift_code_redemptions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code_id = Column(Integer, ForeignKey('gift_codes.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    redeemed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CityMarketItem(Base):
    """موجودی و قیمت محصولات مارکت روبی برای هر شهر."""
    __tablename__ = 'city_market_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey('group_chats.chat_id'), nullable=False)
    item_key = Column(String, nullable=False)  # egg | injured_fox
    quantity = Column(Integer, nullable=False, default=0)
    price = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class RubyEgg(Base):
    """تخم‌مرغ‌های خریداری‌شده از مارکت؛ خام/پخته و غیرقابل فروش."""
    __tablename__ = 'ruby_eggs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    cooked = Column(Integer, nullable=False, default=0)
    cooking_started_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class CityMemberPresence(Base):
    """اولین زمانی که ربات حضور یک کاربر را در یک شهر دیده است."""
    __tablename__ = 'city_member_presence'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey('group_chats.chat_id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class CityDonation(Base):
    __tablename__ = 'city_donations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey('group_chats.chat_id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    amount = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class RubySmuggling(Base):
    __tablename__ = 'ruby_smuggling'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    count = Column(Integer, nullable=False)
    risk_percent = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completes_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default='pending')  # pending | success | caught
    reward = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JailWallMemory(Base):
    __tablename__ = 'jail_wall_memories'
    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    text = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class InjuredFox(Base):
    __tablename__ = 'injured_foxes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    required_attempts = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default='pending')
    rescuer_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=True)
    attempt_log = Column(String, nullable=True, default='')
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FoxHunt(Base):
    __tablename__ = 'fox_hunts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    emoji = Column(String, nullable=False)
    item_name = Column(String, nullable=False)
    nutrition = Column(Integer, nullable=False)
    sell_value = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default='pending')
    weight = Column(Float, nullable=True)                 # وزن (کیلوگرم)؛ موقع شکار رول می‌شود.
    cooked = Column(Integer, nullable=False, default=0)    # 0 = خام، 1 = پخته (داخل یخچال)
    cooking_started_at = Column(DateTime(timezone=True), nullable=True)  # زمان شروع پخت؛ None یعنی در حال پخت نیست.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BankAccount(Base):
    __tablename__ = 'bank_accounts'
    account_number = Column(String(12), primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False, unique=True)
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_interest_at = Column(DateTime(timezone=True), nullable=True)
    last_card_transfer_at = Column(DateTime(timezone=True), nullable=True)

class BankTransaction(Base):
    __tablename__ = 'bank_transactions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_number = Column(String(12), ForeignKey('bank_accounts.account_number'), nullable=False)
    counterparty_account = Column(String(12), nullable=True)
    counterparty_user_id = Column(BigInteger, nullable=True)
    direction = Column(String(10), nullable=False)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    description = Column(String, nullable=True)


class FootballMatch(Base):
    __tablename__ = 'football_matches'
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_home = Column(String, nullable=False)
    team_away = Column(String, nullable=False)
    match_time = Column(String, nullable=False)  # متن آزاد؛ همونی که پشتیبانی وارد کرده (تاریخ/ساعت)
    status = Column(String, nullable=False, default='open')  # open | closed
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FootballPrediction(Base):
    __tablename__ = 'football_predictions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey('football_matches.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    choice = Column(String, nullable=False)  # home | draw | away
    status = Column(String, nullable=False, default='pending')  # pending | approved | rejected
    reward = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime(timezone=True), nullable=True)


class GiftOrder(Base):
    __tablename__ = 'gift_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    recipient_id = Column(BigInteger, nullable=False)
    gift_type = Column(String, nullable=False)          # '15' | '25' | '50'
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Integer, nullable=False)
    total_price = Column(Integer, nullable=False)
    gift_text = Column(String, nullable=True)
    gift_design = Column(String, nullable=True)          # کلید طرح انتخاب‌شده داخل تعرفه (مثلاً teddy/heart)
    receipt_file_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default='pending')  # pending | delivered | rejected
    started_at = Column(DateTime(timezone=True), nullable=True)   # زمان شروع سفارش (انتخاب گیفت)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PointsPurchase(Base):
    __tablename__ = 'points_purchases'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)   # آیدی سفارش‌دهنده
    recipient_id = Column(BigInteger, nullable=False)                              # آیدی گیرنده روب‌پوینت
    package_key = Column(String, nullable=False)         # '1' | '2' | '3' | '4'
    points_amount = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)
    receipt_file_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default='pending')  # pending | approved | rejected
    channel_message_id = Column(BigInteger, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FactoryOrder(Base):
    __tablename__ = 'factory_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    tier_key = Column(String, nullable=False)
    item_key = Column(String, nullable=False)
    percent = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    cost_paid = Column(Integer, nullable=False)
    sell_total = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ready_at = Column(DateTime(timezone=True), nullable=False)
    collected = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FactoryInventory(Base):
    """انبار محصولات ساخته‌شده‌ی هر کاربر؛ محصول برداشت‌شده اینجا می‌مونه تا خودِ کاربر بفروشدش."""
    __tablename__ = 'factory_inventory'
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), primary_key=True)
    item_key = Column(String, primary_key=True)
    quantity = Column(Integer, nullable=False, default=0)


class MarketPrice(Base):
    """قیمت لحظه‌ای هر محصول کارخونه؛ هر ۲۵ دقیقه با جاب پس‌زمینه به‌روزرسانی می‌شود."""
    __tablename__ = 'market_prices'
    item_key = Column(String, primary_key=True)
    price = Column(Integer, nullable=False)
    high_price = Column(Integer, nullable=False)
    low_price = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Referral(Base):
    """زیرمجموعه‌گیری: هر کاربر با لینک اختصاصی خودش، بعد از تایید پشتیبانی، به معرف روب‌پوینت می‌ده."""
    __tablename__ = 'referrals'
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    referred_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False, unique=True)
    status = Column(String, nullable=False, default='pending')  # pending / approved / rejected
    reward = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(BigInteger, nullable=True)


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_gift_code_user ON gift_code_redemptions(code_id, user_id)"))
    inspector = inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    injured_cols = {c['name'] for c in inspector.get_columns('injured_foxes')}
    bank_cols = {c['name'] for c in inspector.get_columns('bank_accounts')}
    if 'education_progress' in inspector.get_table_names():
        education_cols = {c['name'] for c in inspector.get_columns('education_progress')}
        education_additions = {
            'correct_answers': 'INTEGER NOT NULL DEFAULT 0',
            'pending_certificate': 'INTEGER NOT NULL DEFAULT 0',
        }
        with engine.begin() as conn:
            for name, definition in education_additions.items():
                if name not in education_cols:
                    conn.execute(text(f'ALTER TABLE education_progress ADD COLUMN {name} {definition}'))
    additions = {
        'total_earned': 'INTEGER NOT NULL DEFAULT 0',
        'name_flag': "VARCHAR NOT NULL DEFAULT ''",
        'name_emoji': "VARCHAR NOT NULL DEFAULT ''",
        'emoji_storage_capacity': 'INTEGER NOT NULL DEFAULT 3',
        'fox_name': "VARCHAR DEFAULT 'مکار'",
        'fox_level': 'INTEGER NOT NULL DEFAULT 1',
        'fox_belly': 'INTEGER NOT NULL DEFAULT 3',
        'fox_belly_capacity': 'INTEGER NOT NULL DEFAULT 3',
        'fox_points': 'INTEGER NOT NULL DEFAULT 0',
        'fox_storage': 'INTEGER NOT NULL DEFAULT 0',
        'fox_total_earned': 'INTEGER NOT NULL DEFAULT 0',
        'fox_production_remainder': 'FLOAT NOT NULL DEFAULT 0',
        'fox_last_production_at': DT_SQL_TYPE,
        'last_hunt_at': DT_SQL_TYPE,
        'last_transfer_at': DT_SQL_TYPE,
        'last_fox_claim_at': DT_SQL_TYPE,
        'fox_claim_count': 'INTEGER NOT NULL DEFAULT 0',
        'hunt_count': 'INTEGER NOT NULL DEFAULT 0',
        'fox_rescued_count': 'INTEGER NOT NULL DEFAULT 0',
        'fox_prestige_count': 'INTEGER NOT NULL DEFAULT 0',
        'fox_last_hunger_at': DT_SQL_TYPE,
        'wheel_last_spin_at': DT_SQL_TYPE,
        'wheel_last_reward': 'INTEGER',
        'last_casino_game_at': DT_SQL_TYPE,
        'last_ruby_game_at': DT_SQL_TYPE,
        'fox_sick_since': DT_SQL_TYPE,
        'fox_sick_reason': 'VARCHAR',
        'fox_sick_treatment': 'VARCHAR',
        'fox_sick_doses_given': 'INTEGER NOT NULL DEFAULT 0',
        'fox_sick_next_dose_at': DT_SQL_TYPE,
        'fox_sick_rest_until': DT_SQL_TYPE,
        'fox_last_sick_at': DT_SQL_TYPE,
        'fridge_level': 'INTEGER NOT NULL DEFAULT 1',
        'factory_built': 'INTEGER NOT NULL DEFAULT 0',
        'factory_build_started_at': DT_SQL_TYPE,
        'factory_storage_level': 'INTEGER NOT NULL DEFAULT 1',
        'factory_workers_level': 'INTEGER NOT NULL DEFAULT 1',
        'factory_machine_level': 'INTEGER NOT NULL DEFAULT 1',
        'factory_produced_total': 'INTEGER NOT NULL DEFAULT 0',
        'is_banned': 'INTEGER NOT NULL DEFAULT 0',
        'banned_until': DT_SQL_TYPE,
        'jail_until': DT_SQL_TYPE,
        'jail_reason': 'VARCHAR',
        'jail_fine': 'INTEGER NOT NULL DEFAULT 0',
        'jail_arrested_at': DT_SQL_TYPE,
        'injured_fox_stock': 'INTEGER NOT NULL DEFAULT 0',
        'spam_window_at': DT_SQL_TYPE,
        'spam_count': 'INTEGER NOT NULL DEFAULT 0',
    }
    with engine.begin() as conn:
        added_user_cols = set()
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {definition}'))
                added_user_cols.add(name)
        if 'attempt_log' not in injured_cols:
            conn.execute(text("ALTER TABLE injured_foxes ADD COLUMN attempt_log VARCHAR"))
        if 'last_card_transfer_at' not in bank_cols:
            conn.execute(text(f'ALTER TABLE bank_accounts ADD COLUMN last_card_transfer_at {DT_SQL_TYPE}'))
        if 'fox_hunts' in inspector.get_table_names():
            hunt_cols = {c['name'] for c in inspector.get_columns('fox_hunts')}
            hunt_additions = {
                'weight': 'FLOAT',
                'cooked': 'INTEGER NOT NULL DEFAULT 0',
                'cooking_started_at': DT_SQL_TYPE,
            }
            for name, definition in hunt_additions.items():
                if name not in hunt_cols:
                    conn.execute(text(f'ALTER TABLE fox_hunts ADD COLUMN {name} {definition}'))
        if 'gift_codes' in inspector.get_table_names():
            gcode_cols = {c['name'] for c in inspector.get_columns('gift_codes')}
            if 'expires_at' not in gcode_cols:
                conn.execute(text(f'ALTER TABLE gift_codes ADD COLUMN expires_at {DT_SQL_TYPE}'))
        if 'gift_orders' in inspector.get_table_names():
            gift_cols = {c['name'] for c in inspector.get_columns('gift_orders')}
            gift_additions = {
                'gift_design': 'VARCHAR',
            }
            for name, definition in gift_additions.items():
                if name not in gift_cols:
                    conn.execute(text(f'ALTER TABLE gift_orders ADD COLUMN {name} {definition}'))
        if 'ruby_tables' in inspector.get_table_names():
            ruby_cols = {c['name'] for c in inspector.get_columns('ruby_tables')}
            ruby_additions = {
                'entry_amount': 'INTEGER NOT NULL DEFAULT 0',
                'pot': 'INTEGER NOT NULL DEFAULT 0',
                'scores': "VARCHAR DEFAULT ''",
                'message_id': 'BIGINT',
                'state': "VARCHAR DEFAULT ''",
            }
            for name, definition in ruby_additions.items():
                if name not in ruby_cols:
                    conn.execute(text(f'ALTER TABLE ruby_tables ADD COLUMN {name} {definition}'))
        # دیتای قدیمی را حفظ می‌کنیم و فقط مقدارهای روباه را برای کاربران قدیمی آماده می‌کنیم.
        conn.execute(text("UPDATE users SET fox_name = 'مکار' WHERE fox_name IS NULL OR fox_name = ''"))
        conn.execute(text("UPDATE users SET fox_level = 1 WHERE fox_level IS NULL OR fox_level < 1"))
        conn.execute(text("UPDATE users SET fox_belly = 3 WHERE fox_belly IS NULL OR fox_belly < 0"))
        conn.execute(text(
            "UPDATE users SET fox_belly_capacity = 3 + COALESCE(fox_level, 1) - 1 "
            "WHERE fox_belly_capacity IS NULL OR fox_belly_capacity < 3"
        ))
        conn.execute(text("UPDATE users SET fox_points = 0 WHERE fox_points IS NULL OR fox_points < 0"))
        conn.execute(text("UPDATE users SET fox_storage = 0 WHERE fox_storage IS NULL OR fox_storage < 0"))
        conn.execute(text("UPDATE users SET fox_total_earned = 0 WHERE fox_total_earned IS NULL OR fox_total_earned < 0"))
        conn.execute(text("UPDATE users SET fox_production_remainder = 0 WHERE fox_production_remainder IS NULL OR fox_production_remainder < 0"))
        conn.execute(text("UPDATE users SET fox_claim_count = 0 WHERE fox_claim_count IS NULL OR fox_claim_count < 0"))
        conn.execute(text("UPDATE users SET hunt_count = 0 WHERE hunt_count IS NULL OR hunt_count < 0"))
        conn.execute(text("UPDATE users SET fox_rescued_count = 0 WHERE fox_rescued_count IS NULL OR fox_rescued_count < 0"))
        conn.execute(text("UPDATE users SET fox_prestige_count = 0 WHERE fox_prestige_count IS NULL OR fox_prestige_count < 0"))
        conn.execute(text("UPDATE users SET fridge_level = 1 WHERE fridge_level IS NULL OR fridge_level < 1"))
        conn.execute(text("UPDATE users SET factory_built = 0 WHERE factory_built IS NULL"))
        conn.execute(text("UPDATE users SET factory_storage_level = 1 WHERE factory_storage_level IS NULL OR factory_storage_level < 1"))
        conn.execute(text("UPDATE users SET factory_workers_level = 1 WHERE factory_workers_level IS NULL OR factory_workers_level < 1"))
        conn.execute(text("UPDATE users SET factory_machine_level = 1 WHERE factory_machine_level IS NULL OR factory_machine_level < 1"))
        conn.execute(text("UPDATE users SET factory_produced_total = 0 WHERE factory_produced_total IS NULL OR factory_produced_total < 0"))
        conn.execute(text("UPDATE users SET is_banned = 0 WHERE is_banned IS NULL"))
        conn.execute(text("UPDATE users SET jail_fine = 0 WHERE jail_fine IS NULL OR jail_fine < 0"))
        if 'injured_fox_stock' in added_user_cols:
            # برای کاربران قدیمی، آمار نجات‌یافته‌ها را به موجودی اولیه قاچاق تبدیل می‌کنیم؛
            # خود fox_rescued_count هرگز کم یا تغییر داده نمی‌شود.
            conn.execute(text("UPDATE users SET injured_fox_stock = COALESCE(fox_rescued_count, 0)"))
        else:
            conn.execute(text("UPDATE users SET injured_fox_stock = 0 WHERE injured_fox_stock IS NULL OR injured_fox_stock < 0"))
        conn.execute(text("UPDATE users SET spam_count = 0 WHERE spam_count IS NULL OR spam_count < 0"))
        if 'total_earned' not in cols:
            conn.execute(text('UPDATE users SET total_earned = points WHERE total_earned = 0'))
        if 'group_chats' in inspector.get_table_names():
            gc_cols = {c['name'] for c in inspector.get_columns('group_chats')}
            gc_additions = {
                'city_owner_id': 'BIGINT',
                'city_owner_name': 'VARCHAR',
                'city_level': 'INTEGER NOT NULL DEFAULT 1',
                'city_claim_total': 'INTEGER NOT NULL DEFAULT 0',
                'city_rescued_total': 'INTEGER NOT NULL DEFAULT 0',
                'city_hunt_total': 'INTEGER NOT NULL DEFAULT 0',
                'city_treasury': 'INTEGER NOT NULL DEFAULT 0',
                'city_donors': "VARCHAR DEFAULT ''",
                'ai_mod': 'INTEGER NOT NULL DEFAULT 0',
                'spell_mod': 'INTEGER NOT NULL DEFAULT -1',
            }
            for name, definition in gc_additions.items():
                if name not in gc_cols:
                    conn.execute(text(f'ALTER TABLE group_chats ADD COLUMN {name} {definition}'))
            mayor_additions = {
                'city_mayor_id': 'BIGINT',
                'city_mayor_name': 'VARCHAR',
                'city_mayor_source': "VARCHAR DEFAULT 'owner'",
                'city_mayor_term_ends_at': DT_SQL_TYPE,
                'city_election_status': "VARCHAR DEFAULT 'none'",
                'city_election_candidates': "VARCHAR DEFAULT ''",
                'city_election_votes': "VARCHAR DEFAULT ''",
                'city_election_candidacy_ends_at': DT_SQL_TYPE,
                'city_election_voting_ends_at': DT_SQL_TYPE,
            }
            for name, definition in mayor_additions.items():
                if name not in gc_cols:
                    conn.execute(text(f'ALTER TABLE group_chats ADD COLUMN {name} {definition}'))
            conn.execute(text(
                "UPDATE group_chats SET city_election_status = 'none' "
                "WHERE city_election_status IS NULL OR city_election_status = ''"
            ))
            # نسخه‌ی جدید رأی‌گیری ندارد: برای شهرهای قدیمی شهردار به مالک گپ منتقل می‌شود.
            # فقط ردیف‌هایی که ستون source تازه ساخته شده‌اند (یعنی هنوز انتقال دستی نداشته‌اند).
            if 'city_mayor_source' not in gc_cols:
                conn.execute(text(
                    "UPDATE group_chats SET city_mayor_id = city_owner_id, "
                    "city_mayor_name = city_owner_name, city_mayor_source = 'owner' "
                    "WHERE city_owner_id IS NOT NULL"
                ))
        # جداول جدید مارکت روبی و شرط ۳ روز حضور
        if 'city_market_items' in inspector.get_table_names():
            cm_cols = {c['name'] for c in inspector.get_columns('city_market_items')}
            if 'updated_at' not in cm_cols:
                conn.execute(text(f'ALTER TABLE city_market_items ADD COLUMN updated_at {DT_SQL_TYPE}'))
        if 'fox_knowledge' in inspector.get_table_names():
            fk_cols = {c['name'] for c in inspector.get_columns('fox_knowledge')}
            for name, definition in {'media_type': 'VARCHAR', 'file_id': 'VARCHAR', 'file_unique_id': 'VARCHAR'}.items():
                if name not in fk_cols:
                    conn.execute(text(f'ALTER TABLE fox_knowledge ADD COLUMN {name} {definition}'))


def get_session():
    return SessionLocal()
