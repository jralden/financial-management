#!/usr/bin/env python3
"""
Sync local Fidelity data to Railway PostgreSQL.

Run this after the local scraper fetches new data.
"""

import json
import os
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import delete
from .models import (
    get_session, init_database, AccountBalance, BondHolding,
    MonthlyProjection, SyncLog
)


def get_issuer_from_cusip(cusip: str, original_issuer: str) -> str:
    """Get issuer name from CUSIP if original is Unknown."""
    if original_issuer and original_issuer != "Unknown":
        return original_issuer

    # US Treasury securities start with 912
    if cusip.startswith("912"):
        return "US TREASURY"

    # Could add more CUSIP prefix lookups here
    return original_issuer

CACHE_DIR = Path.home() / ".cache" / "financial-management"


def sync_balances() -> int:
    """Sync account balances from local cache to database."""
    cache_file = CACHE_DIR / "fidelity_balances.json"

    if not cache_file.exists():
        print("No balances cache found")
        return 0

    with open(cache_file) as f:
        data = json.load(f)

    session = get_session()

    try:
        # Parse timestamp
        timestamp = datetime.fromisoformat(data['timestamp'])

        # Clear old balances and insert new
        session.execute(delete(AccountBalance))

        count = 0
        for acc in data.get('accounts', []):
            balance = AccountBalance(
                account_number=acc.get('account_number', 'unknown'),
                account_name=acc.get('name', 'Unknown'),
                account_type=acc.get('account_type', 'Unknown'),
                balance=acc.get('balance', 0),
                daily_change=acc.get('daily_change', 0),
                daily_change_percent=acc.get('daily_change_percent', 0),
                as_of=timestamp
            )
            session.add(balance)
            count += 1

        session.commit()
        print(f"Synced {count} account balances")
        return count

    except Exception as e:
        session.rollback()
        print(f"Error syncing balances: {e}")
        raise
    finally:
        session.close()


def sync_bond_holdings() -> int:
    """Sync bond holdings from local cache to database."""
    cache_file = CACHE_DIR / "bond_holdings.json"

    if not cache_file.exists():
        print("No bond holdings cache found")
        return 0

    with open(cache_file) as f:
        data = json.load(f)

    session = get_session()

    try:
        # Clear old holdings and insert new
        session.execute(delete(BondHolding))

        count = 0
        for h in data.get('holdings', []):
            # Parse maturity date
            maturity = date.fromisoformat(h['maturity_date'])

            # Infer payment months from maturity if not set
            month1 = maturity.month
            month2 = month1 - 6 if month1 > 6 else month1 + 6
            pay_month_1, pay_month_2 = min(month1, month2), max(month1, month2)

            holding = BondHolding(
                cusip=h['cusip'],
                issuer=get_issuer_from_cusip(h['cusip'], h.get('issuer', 'Unknown')),
                coupon_rate=h['coupon_rate'],
                maturity_date=maturity,
                face_value=h['face_value'],
                current_value=h.get('current_value', 0),
                account=h.get('account', 'Unknown'),
                payment_month_1=pay_month_1,
                payment_month_2=pay_month_2,
                payment_verified=False,
                last_updated=datetime.now(timezone.utc)
            )
            session.add(holding)
            count += 1

        session.commit()
        print(f"Synced {count} bond holdings")
        return count

    except Exception as e:
        session.rollback()
        print(f"Error syncing holdings: {e}")
        raise
    finally:
        session.close()


def sync_monthly_projections() -> int:
    """Sync monthly projections from local cache to database."""
    cache_file = CACHE_DIR / "monthly_income.json"

    if not cache_file.exists():
        print("No monthly projections cache found")
        return 0

    with open(cache_file) as f:
        data = json.load(f)

    session = get_session()

    try:
        # Clear old projections and insert new
        session.execute(delete(MonthlyProjection))

        count = 0
        for m in data.get('monthly_totals', []):
            projection = MonthlyProjection(
                year=m['year'],
                month=m['month'],
                coupon_income=m.get('coupon_income', 0),
                maturities=m.get('maturities', 0),
                total_cash=m.get('total_cash', 0),
                calculated_at=datetime.now(timezone.utc)
            )
            session.add(projection)
            count += 1

        session.commit()
        print(f"Synced {count} monthly projections")
        return count

    except Exception as e:
        session.rollback()
        print(f"Error syncing projections: {e}")
        raise
    finally:
        session.close()


def sync_all() -> dict:
    """Sync all data to Railway database."""
    print(f"\n{'='*50}")
    print("SYNCING TO RAILWAY DATABASE")
    print(f"{'='*50}")

    # Initialize database tables if needed
    init_database()

    session = get_session()
    log = SyncLog(
        sync_type='full',
        status='running',
        started_at=datetime.now(timezone.utc)
    )
    session.add(log)
    session.commit()
    log_id = log.id
    session.close()

    results = {}
    total = 0

    try:
        results['balances'] = sync_balances()
        total += results['balances']

        results['holdings'] = sync_bond_holdings()
        total += results['holdings']

        results['projections'] = sync_monthly_projections()
        total += results['projections']

        # Update sync log
        session = get_session()
        log = session.get(SyncLog, log_id)
        log.status = 'success'
        log.records_synced = total
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()

        print(f"\n{'='*50}")
        print(f"SYNC COMPLETE: {total} records")
        print(f"{'='*50}")

    except Exception as e:
        # Update sync log with error
        session = get_session()
        log = session.get(SyncLog, log_id)
        log.status = 'error'
        log.error_message = str(e)
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()
        raise

    return results


def main():
    import sys

    # Check for DATABASE_URL
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("WARNING: DATABASE_URL not set - using local SQLite")
        print("Set DATABASE_URL to sync to Railway PostgreSQL")

    if "--init" in sys.argv:
        init_database()
        print("Database initialized")
        return

    sync_all()


if __name__ == "__main__":
    main()
