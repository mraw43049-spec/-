from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Float, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DATABASE_URL

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]

if DATABASE_URL.startswith('postgresql://'):
    try:
        import psycopg  # noqa: F401
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
    except ImportError:
        DATABASE_URL = 'sqlite:///bot.db'

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
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
    fox_points = Column(Integer, nullable=False, default=0)
    fox_total_earned = Column(Integer, nullable=False, default=0)
    fox_production_remainder = Column(Float, nullable=False, default=0.0)
    fox_last_production_at = Column(DateTime(timezone=True), nullable=True)
    last_hunt_at = Column(DateTime(timezone=True), nullable=True)
    last_transfer_at = Column(DateTime(timezone=True), nullable=True)
    last_fox_claim_at = Column(DateTime(timezone=True), nullable=True)
    fox_claim_count = Column(Integer, nullable=False, default=0)
    hunt_count = Column(Integer, nullable=False, default=0)
    fox_rescued_count = Column(Integer, nullable=False, default=0)
    fox_last_hunger_at = Column(DateTime(timezone=True), nullable=True)
    wheel_last_spin_at = Column(DateTime(timezone=True), nullable=True)
    wheel_last_reward = Column(Integer, nullable=True)
    last_ruby_game_at = Column(DateTime(timezone=True), nullable=True)

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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BankAccount(Base):
    __tablename__ = 'bank_accounts'
    account_number = Column(String(12), primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False, unique=True)
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_interest_at = Column(DateTime(timezone=True), nullable=True)

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


def init_db():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    cols = {c['name'] for c in inspector.get_columns('users')}
    injured_cols = {c['name'] for c in inspector.get_columns('injured_foxes')}
    additions = {
        'total_earned': 'INTEGER NOT NULL DEFAULT 0',
        'fox_name': "VARCHAR DEFAULT 'مکار'",
        'fox_level': 'INTEGER NOT NULL DEFAULT 1',
        'fox_belly': 'INTEGER NOT NULL DEFAULT 3',
        'fox_points': 'INTEGER NOT NULL DEFAULT 0',
        'fox_total_earned': 'INTEGER NOT NULL DEFAULT 0',
        'fox_production_remainder': 'FLOAT NOT NULL DEFAULT 0',
        'fox_last_production_at': 'DATETIME',
        'last_hunt_at': 'DATETIME',
        'last_transfer_at': 'DATETIME',
        'last_fox_claim_at': 'DATETIME',
        'fox_claim_count': 'INTEGER NOT NULL DEFAULT 0',
        'hunt_count': 'INTEGER NOT NULL DEFAULT 0',
        'fox_rescued_count': 'INTEGER NOT NULL DEFAULT 0',
        'fox_last_hunger_at': 'DATETIME',
        'wheel_last_spin_at': 'DATETIME',
        'wheel_last_reward': 'INTEGER',
        'last_ruby_game_at': 'DATETIME',
    }
    with engine.begin() as conn:
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {definition}'))
        if 'attempt_log' not in injured_cols:
            conn.execute(text("ALTER TABLE injured_foxes ADD COLUMN attempt_log VARCHAR"))
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
        conn.execute(text("UPDATE users SET fox_points = 0 WHERE fox_points IS NULL OR fox_points < 0"))
        conn.execute(text("UPDATE users SET fox_total_earned = 0 WHERE fox_total_earned IS NULL OR fox_total_earned < 0"))
        conn.execute(text("UPDATE users SET fox_production_remainder = 0 WHERE fox_production_remainder IS NULL OR fox_production_remainder < 0"))
        conn.execute(text("UPDATE users SET fox_claim_count = 0 WHERE fox_claim_count IS NULL OR fox_claim_count < 0"))
        conn.execute(text("UPDATE users SET hunt_count = 0 WHERE hunt_count IS NULL OR hunt_count < 0"))
        conn.execute(text("UPDATE users SET fox_rescued_count = 0 WHERE fox_rescued_count IS NULL OR fox_rescued_count < 0"))
        if 'total_earned' not in cols:
            conn.execute(text('UPDATE users SET total_earned = points WHERE total_earned = 0'))


def get_session():
    return SessionLocal()
