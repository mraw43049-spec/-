from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DATABASE_URL

# Normalize Railway PostgreSQL URLs and explicitly select psycopg v3.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    points = Column(Integer, nullable=False, default=0)
    total_earned = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=1)
    last_claim_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Challenge(Base):
    __tablename__ = "challenges"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    game_type = Column(String, nullable=False)
    player1_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    player2_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    player1_score = Column(Integer, nullable=True)
    player2_score = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

def init_db():
    Base.metadata.create_all(engine)
    # create_all ستون‌های جدید را به جدول قدیمی اضافه نمی‌کند؛ این migration سبک برای Railway است.
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "total_earned" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN total_earned INTEGER NOT NULL DEFAULT 0"))
            conn.execute(text("UPDATE users SET total_earned = points WHERE total_earned = 0"))

def get_session():
    return SessionLocal()
