# -*- coding: utf-8 -*-
"""دیتابیس مستقل پروژه‌ی سلف (فقط جدول‌های self_access و self_profile)."""
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or "sqlite:///self.db"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
if DATABASE_URL.startswith("postgresql://"):
    try:
        import psycopg  # noqa: F401
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    except ImportError:
        logger.error("psycopg نصب نیست؛ برگشت به SQLite محلی (با هر دیپلوی پاک می‌شه)")
        DATABASE_URL = "sqlite:///self.db"

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5 if not _is_sqlite else 5,
    max_overflow=10 if not _is_sqlite else 0,
    pool_recycle=1800,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    import selfbot  # noqa: F401  (جدول‌ها موقع import روی Base ثبت می‌شن)
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
