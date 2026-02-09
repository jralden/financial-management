"""
Cache reader for scraper data.

Reads from Backblaze B2 if B2_BUCKET_NAME is set, otherwise
falls back to local cache files at ~/.cache/financial-management/.
"""

import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
from dataclasses import dataclass

CACHE_DIR = Path.home() / ".cache" / "financial-management"
BALANCES_FILE = CACHE_DIR / "fidelity_balances.json"
BONDS_FILE = CACHE_DIR / "bond_holdings.json"

ET_TZ = ZoneInfo("America/New_York")


def _read_json(local_path: Path, filename: str) -> Optional[dict]:
    """Read JSON from B2 if configured, otherwise from local filesystem."""
    bucket = os.environ.get("B2_BUCKET_NAME")
    if bucket:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["B2_ENDPOINT_URL"],
            aws_access_key_id=os.environ["B2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["B2_SECRET_ACCESS_KEY"],
        )
        obj = s3.get_object(Bucket=bucket, Key=filename)
        return json.loads(obj["Body"].read())

    if not local_path.exists():
        return None
    with open(local_path) as f:
        return json.load(f)


# Account ordering
ACCOUNT_ORDER = {
    "Joint WROS - TOD": 0,
    "Mary's IRA": 1,
    "John's IRA": 2,
}


@dataclass
class AccountBalance:
    account_name: str
    account_type: str
    balance: float
    cash_balance: float
    daily_change: float
    daily_change_percent: float


@dataclass
class BondHolding:
    cusip: str
    issuer: str
    coupon_rate: float
    face_value: float
    current_value: float
    account: str
    maturity_date: date
    annual_income: float
    payment_month_1: int
    payment_month_2: int


@dataclass
class CacheStatus:
    balances_timestamp: Optional[datetime]
    bonds_timestamp: Optional[datetime]
    is_stale: bool  # True if balances older than 15 minutes during market hours


def is_market_hours() -> bool:
    """Check if current time is within market hours."""
    now_et = datetime.now(ET_TZ)
    if now_et.weekday() > 4:  # Weekend
        return False
    if now_et.hour < 9 or now_et.hour >= 17:
        return False
    return True


def load_balances() -> tuple[list[AccountBalance], float, float, Optional[datetime]]:
    """Load account balances from cache.

    Returns:
        (accounts, total_balance, total_change, timestamp)
    """
    try:
        data = _read_json(BALANCES_FILE, "fidelity_balances.json")
        if data is None:
            return [], 0.0, 0.0, None

        # Load cash data from bonds file if available
        cash_by_account = {}
        bonds_data = _read_json(BONDS_FILE, "bond_holdings.json")
        if bonds_data:
            cash_by_account = bonds_data.get('cash_by_account', {})

        accounts = []
        for acc in data.get('accounts', []):
            account_name = acc.get('name', 'Unknown')
            accounts.append(AccountBalance(
                account_name=account_name,
                account_type=acc.get('account_type', 'Unknown'),
                balance=acc.get('balance', 0),
                cash_balance=cash_by_account.get(account_name, 0),
                daily_change=acc.get('daily_change', 0),
                daily_change_percent=acc.get('daily_change_percent', 0),
            ))

        # Sort by account order
        accounts.sort(key=lambda a: ACCOUNT_ORDER.get(a.account_name, 99))

        timestamp = None
        if data.get('cached_at'):
            timestamp = datetime.fromisoformat(data['cached_at'])

        return (
            accounts,
            data.get('total_balance', 0),
            data.get('total_daily_change', 0),
            timestamp
        )
    except Exception as e:
        print(f"Error loading balances: {e}")
        return [], 0.0, 0.0, None


def load_bond_holdings() -> tuple[list[BondHolding], Optional[datetime]]:
    """Load bond holdings from cache.

    Returns:
        (holdings, timestamp)
    """
    try:
        data = _read_json(BONDS_FILE, "bond_holdings.json")
        if data is None:
            return [], None

        holdings = []
        for h in data.get('holdings', []):
            maturity = date.fromisoformat(h['maturity_date'])

            # Infer payment months from maturity
            month1 = maturity.month
            month2 = month1 - 6 if month1 > 6 else month1 + 6
            pay_month_1, pay_month_2 = min(month1, month2), max(month1, month2)

            holdings.append(BondHolding(
                cusip=h['cusip'],
                issuer=h.get('issuer', 'Unknown'),
                coupon_rate=h['coupon_rate'],
                face_value=h['face_value'],
                current_value=h.get('current_value', 0),
                account=h.get('account', 'Unknown'),
                maturity_date=maturity,
                annual_income=h.get('annual_income', h['face_value'] * h['coupon_rate']),
                payment_month_1=pay_month_1,
                payment_month_2=pay_month_2,
            ))

        # Sort by maturity date
        holdings.sort(key=lambda h: h.maturity_date)

        timestamp = None
        if data.get('timestamp'):
            timestamp = datetime.fromisoformat(data['timestamp'])

        return holdings, timestamp
    except Exception as e:
        print(f"Error loading holdings: {e}")
        return [], None


def get_cache_status() -> CacheStatus:
    """Get status of cached data."""
    _, _, _, balances_ts = load_balances()
    _, bonds_ts = load_bond_holdings()

    is_stale = False
    if balances_ts and is_market_hours():
        age_minutes = (datetime.now() - balances_ts).total_seconds() / 60
        is_stale = age_minutes > 15

    return CacheStatus(
        balances_timestamp=balances_ts,
        bonds_timestamp=bonds_ts,
        is_stale=is_stale,
    )


def get_bonds_by_account(holdings: list[BondHolding]) -> dict:
    """Group holdings by account with summaries."""
    bonds_by_account = {}

    for account_name in ACCOUNT_ORDER.keys():
        account_bonds = [h for h in holdings if h.account == account_name]
        if account_bonds:
            bonds_by_account[account_name] = {
                'bonds': account_bonds,
                'count': len(account_bonds),
                'face_value': sum(h.face_value for h in account_bonds),
                'annual_income': sum(h.annual_income for h in account_bonds)
            }

    return bonds_by_account


def calculate_account_income(holdings: list[BondHolding]) -> dict:
    """Calculate next month and 12-month income per account."""
    today = datetime.now()
    next_month = today.month + 1 if today.month < 12 else 1
    next_month_year = today.year if today.month < 12 else today.year + 1

    account_summaries = {}

    for account_name in ACCOUNT_ORDER.keys():
        account_bonds = [h for h in holdings if h.account == account_name]
        if not account_bonds:
            continue

        next_month_income = 0
        twelve_month_income = 0

        for bond in account_bonds:
            # Check for next month coupon payment
            if bond.payment_month_1 == next_month or bond.payment_month_2 == next_month:
                # Only count if bond hasn't matured before next month
                if not (bond.maturity_date.year < next_month_year or
                        (bond.maturity_date.year == next_month_year and
                         bond.maturity_date.month < next_month)):
                    next_month_income += bond.annual_income / 2

            # Calculate 12-month income
            for i in range(12):
                check_month = (today.month + i) % 12 + 1
                check_year = today.year + (today.month + i) // 12

                # Skip if bond already matured
                if (bond.maturity_date.year < check_year or
                    (bond.maturity_date.year == check_year and
                     bond.maturity_date.month < check_month)):
                    continue

                if bond.payment_month_1 == check_month or bond.payment_month_2 == check_month:
                    twelve_month_income += bond.annual_income / 2

        account_summaries[account_name] = {
            'next_month_income': next_month_income,
            'twelve_month_income': twelve_month_income,
            'bond_count': len(account_bonds),
            'face_value': sum(b.face_value for b in account_bonds),
            'annual_income': sum(b.annual_income for b in account_bonds)
        }

    return account_summaries
