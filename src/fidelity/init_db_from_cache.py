#!/usr/bin/env python3
"""Initialize the bond database from cached holdings."""

import json
from pathlib import Path
from datetime import date
from src.fidelity.bond_database import upsert_bond_metadata, upsert_holding, print_database_summary

CACHE_DIR = Path.home() / ".cache" / "financial-management"
BONDS_CACHE_FILE = CACHE_DIR / "bond_holdings.json"

def main():
    if not BONDS_CACHE_FILE.exists():
        print(f"No cached bonds found at {BONDS_CACHE_FILE}")
        print("Run: python -m src.fidelity.bond_income --headed")
        return

    with open(BONDS_CACHE_FILE) as f:
        data = json.load(f)

    holdings = data.get('holdings', [])
    print(f"Loading {len(holdings)} bonds from cache...")

    for h in holdings:
        # Parse maturity date
        maturity = date.fromisoformat(h['maturity_date'])

        # Upsert bond metadata
        upsert_bond_metadata(
            cusip=h['cusip'],
            issuer=h['issuer'],
            coupon_rate=h['coupon_rate'],
            maturity_date=maturity
        )

        # Upsert holding
        upsert_holding(
            cusip=h['cusip'],
            account=h['account'],
            face_value=h['face_value'],
            current_value=h['current_value']
        )

    print("Database initialized!")
    print_database_summary()

if __name__ == "__main__":
    main()
