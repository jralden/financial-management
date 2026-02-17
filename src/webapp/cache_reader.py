"""
Cache reader for bond holdings data.

Reads from local cache files at ~/.cache/financial-management/.
"""

import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

CACHE_DIR = Path.home() / ".cache" / "financial-management"
BONDS_FILE = CACHE_DIR / "bond_holdings.json"


# Account ordering
ACCOUNT_ORDER = {
    "Joint WROS - TOD": 0,
    "Mary's IRA": 1,
    "John's IRA": 2,
}


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


def _read_json(local_path: Path) -> Optional[dict]:
    """Read JSON from local filesystem."""
    if not local_path.exists():
        return None
    with open(local_path) as f:
        return json.load(f)


def load_bond_holdings() -> tuple[list[BondHolding], Optional[datetime]]:
    """Load bond holdings from cache.

    Returns:
        (holdings, timestamp)
    """
    try:
        data = _read_json(BONDS_FILE)
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
