"""
Database models for the Financial Management system.
Supports both local SQLite and Railway PostgreSQL.
"""

from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    Date, DateTime, ForeignKey, Text, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

Base = declarative_base()


class AccountBalance(Base):
    """Fidelity account balances - updated by local scraper."""
    __tablename__ = "account_balances"

    id = Column(Integer, primary_key=True)
    account_number = Column(String(20), nullable=False, index=True)
    account_name = Column(String(100), nullable=False)
    account_type = Column(String(50))  # Investment, Retirement, Authorized
    balance = Column(Float, nullable=False)
    cash_balance = Column(Float, default=0)  # Uninvested cash (money market, etc.)
    daily_change = Column(Float, default=0)
    daily_change_percent = Column(Float, default=0)
    as_of = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BondHolding(Base):
    """Bond holdings across all accounts."""
    __tablename__ = "bond_holdings"

    id = Column(Integer, primary_key=True)
    cusip = Column(String(9), nullable=False, index=True)
    issuer = Column(String(100))
    coupon_rate = Column(Float, nullable=False)
    maturity_date = Column(Date, nullable=False)
    face_value = Column(Float, nullable=False)
    current_value = Column(Float)
    account = Column(String(100), nullable=False)

    # Payment schedule (inferred or verified)
    payment_month_1 = Column(Integer)  # 1-12
    payment_month_2 = Column(Integer)  # 1-12
    payment_day = Column(Integer, default=15)
    payment_verified = Column(Boolean, default=False)

    last_updated = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_bond_maturity', 'maturity_date'),
        Index('idx_bond_account', 'account'),
    )


class MonthlyProjection(Base):
    """Pre-calculated monthly income projections."""
    __tablename__ = "monthly_projections"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    coupon_income = Column(Float, default=0)
    maturities = Column(Float, default=0)
    total_cash = Column(Float, default=0)
    calculated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_projection_date', 'year', 'month'),
    )


class BondEvaluation(Base):
    """Evaluated bonds for potential purchase."""
    __tablename__ = "bond_evaluations"

    id = Column(Integer, primary_key=True)
    cusip = Column(String(9), nullable=False, index=True)
    issuer = Column(String(100))
    coupon_rate = Column(Float)
    maturity_date = Column(Date)
    price = Column(Float)
    yield_to_maturity = Column(Float)
    rating_sp = Column(String(10))
    rating_moody = Column(String(10))

    # Calculated scores
    income_score = Column(Float)
    profit_score = Column(Float)
    composite_score = Column(Float)

    # Evaluation metadata
    evaluated_at = Column(DateTime, default=datetime.utcnow)
    evaluation_batch = Column(String(50))  # Group evaluations by batch

    notes = Column(Text)


class SyncLog(Base):
    """Track data syncs from local machine."""
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    sync_type = Column(String(50), nullable=False)  # balances, holdings, projections
    records_synced = Column(Integer, default=0)
    status = Column(String(20))  # success, error
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


def get_database_url() -> str:
    """Get database URL from environment or use local SQLite."""
    # Railway sets DATABASE_URL automatically when you add PostgreSQL
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        # Railway uses postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # Fallback to local SQLite for development
    return "sqlite:///./financial_management.db"


# Singleton engine and session factory
_engine = None
_SessionFactory = None


def get_engine():
    """Get SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        db_url = get_database_url()
        # Add connection pool settings for PostgreSQL
        if db_url.startswith("postgresql"):
            _engine = create_engine(
                db_url,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_pre_ping=True  # Verify connections before using
            )
        else:
            _engine = create_engine(db_url)
    return _engine


def get_session():
    """Get a new database session."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory()


def init_database():
    """Create all tables."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print(f"Database initialized: {get_database_url()[:50]}...")
