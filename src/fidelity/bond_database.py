#!/usr/bin/env python3
"""
Bond Database - stores payment schedules and other bond metadata.

Since Fidelity doesn't provide coupon payment dates, we need to track them ourselves.
Initial values are inferred from maturity date (payments in maturity month and 6 months prior),
but can be overridden with actual data.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

# Database location
DB_DIR = Path.home() / ".cache" / "financial-management"
DB_FILE = DB_DIR / "bonds.db"


def get_db_connection() -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # Create tables if they don't exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bond_metadata (
            cusip TEXT PRIMARY KEY,
            issuer TEXT,
            coupon_rate REAL,
            maturity_date TEXT,
            payment_month_1 INTEGER,  -- First payment month (1-12)
            payment_month_2 INTEGER,  -- Second payment month (1-12)
            payment_day INTEGER DEFAULT 15,  -- Day of month for payments
            is_monthly_payer INTEGER DEFAULT 0,  -- Some bonds pay monthly
            is_quarterly_payer INTEGER DEFAULT 0,  -- Some bonds pay quarterly
            payment_verified INTEGER DEFAULT 0,  -- Has payment schedule been verified?
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cusip TEXT,
            account TEXT,
            face_value REAL,
            purchase_date TEXT,
            purchase_price REAL,
            current_value REAL,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cusip) REFERENCES bond_metadata(cusip)
        );

        CREATE INDEX IF NOT EXISTS idx_holdings_cusip ON holdings(cusip);
        CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings(account);
    """)

    conn.commit()
    return conn


def infer_payment_months(maturity_date: date) -> tuple[int, int]:
    """
    Infer coupon payment months from maturity date.
    Most bonds pay semiannually on the maturity month and 6 months prior.
    """
    month1 = maturity_date.month
    month2 = month1 - 6 if month1 > 6 else month1 + 6
    # Return in chronological order (earlier month first)
    return (min(month1, month2), max(month1, month2))


def upsert_bond_metadata(
    cusip: str,
    issuer: str,
    coupon_rate: float,
    maturity_date: date,
    payment_months: Optional[tuple[int, int]] = None,
    payment_day: int = 15,
    verified: bool = False,
    notes: str = ""
) -> None:
    """Insert or update bond metadata."""
    conn = get_db_connection()

    # Use provided payment months or infer from maturity
    if payment_months:
        month1, month2 = payment_months
    else:
        month1, month2 = infer_payment_months(maturity_date)

    conn.execute("""
        INSERT INTO bond_metadata
            (cusip, issuer, coupon_rate, maturity_date, payment_month_1, payment_month_2,
             payment_day, payment_verified, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(cusip) DO UPDATE SET
            issuer = excluded.issuer,
            coupon_rate = excluded.coupon_rate,
            maturity_date = excluded.maturity_date,
            payment_month_1 = CASE WHEN payment_verified = 0 THEN excluded.payment_month_1 ELSE payment_month_1 END,
            payment_month_2 = CASE WHEN payment_verified = 0 THEN excluded.payment_month_2 ELSE payment_month_2 END,
            updated_at = CURRENT_TIMESTAMP
    """, (cusip, issuer, coupon_rate, maturity_date.isoformat(), month1, month2,
          payment_day, 1 if verified else 0, notes))

    conn.commit()
    conn.close()


def get_bond_metadata(cusip: str) -> Optional[dict]:
    """Get metadata for a specific bond."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM bond_metadata WHERE cusip = ?", (cusip,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_bonds() -> list[dict]:
    """Get all bonds in the database."""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM bond_metadata ORDER BY maturity_date").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_payment_schedule(
    cusip: str,
    payment_month_1: int,
    payment_month_2: int,
    payment_day: int = 15,
    verified: bool = True
) -> None:
    """Update the payment schedule for a bond (manual override)."""
    conn = get_db_connection()
    conn.execute("""
        UPDATE bond_metadata
        SET payment_month_1 = ?, payment_month_2 = ?, payment_day = ?,
            payment_verified = ?, updated_at = CURRENT_TIMESTAMP
        WHERE cusip = ?
    """, (payment_month_1, payment_month_2, payment_day, 1 if verified else 0, cusip))
    conn.commit()
    conn.close()


def upsert_holding(
    cusip: str,
    account: str,
    face_value: float,
    current_value: float = 0.0
) -> None:
    """Insert or update a holding."""
    conn = get_db_connection()

    # Check if holding exists
    existing = conn.execute(
        "SELECT id FROM holdings WHERE cusip = ? AND account = ?",
        (cusip, account)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE holdings
            SET face_value = ?, current_value = ?, last_updated = CURRENT_TIMESTAMP
            WHERE cusip = ? AND account = ?
        """, (face_value, current_value, cusip, account))
    else:
        conn.execute("""
            INSERT INTO holdings (cusip, account, face_value, current_value)
            VALUES (?, ?, ?, ?)
        """, (cusip, account, face_value, current_value))

    conn.commit()
    conn.close()


def get_holdings_with_metadata() -> list[dict]:
    """Get all holdings with their bond metadata."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT h.*, m.issuer, m.coupon_rate, m.maturity_date,
               m.payment_month_1, m.payment_month_2, m.payment_day,
               m.payment_verified
        FROM holdings h
        JOIN bond_metadata m ON h.cusip = m.cusip
        ORDER BY m.maturity_date
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def sync_from_portfolio(holdings: list) -> None:
    """
    Sync the database from fetched portfolio holdings.
    holdings: list of BondHolding objects from bond_income.py
    """
    for h in holdings:
        # Upsert bond metadata (infers payment months if not already set)
        upsert_bond_metadata(
            cusip=h.cusip,
            issuer=h.issuer,
            coupon_rate=h.coupon_rate,
            maturity_date=h.maturity_date
        )
        # Upsert holding
        upsert_holding(
            cusip=h.cusip,
            account=h.account,
            face_value=h.face_value,
            current_value=h.current_value
        )


def print_database_summary():
    """Print a summary of the database contents."""
    bonds = get_all_bonds()
    holdings = get_holdings_with_metadata()

    print(f"\n{'='*70}")
    print("BOND DATABASE SUMMARY")
    print(f"{'='*70}")
    print(f"\nTotal bonds in database: {len(bonds)}")
    print(f"Total holdings: {len(holdings)}")

    verified = sum(1 for b in bonds if b['payment_verified'])
    print(f"Payment schedules verified: {verified}/{len(bonds)}")

    print(f"\n{'Bond':<12} {'Issuer':<25} {'Coupon':>7} {'Maturity':<12} {'Pays':>10} {'Verified'}")
    print("-"*70)
    for b in bonds:
        pay_months = f"{b['payment_month_1']:02d}/{b['payment_month_2']:02d}"
        verified_mark = "✓" if b['payment_verified'] else "?"
        print(f"{b['cusip']:<12} {b['issuer'][:24]:<25} {b['coupon_rate']*100:>6.2f}% "
              f"{b['maturity_date']:<12} {pay_months:>10} {verified_mark:>8}")


if __name__ == "__main__":
    print_database_summary()
