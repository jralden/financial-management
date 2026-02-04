#!/usr/bin/env python3
"""
Monthly Bond Income Projection

Projects cash flow by month based on bond holdings and payment schedules.
Uses the bond database to track payment months for each bond.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from calendar import month_abbr

from src.fidelity.bond_database import (
    get_db_connection,
    sync_from_portfolio,
    get_holdings_with_metadata,
    print_database_summary
)
from src.fidelity.bond_income import fetch_bond_holdings, BondHolding

CACHE_DIR = Path.home() / ".cache" / "financial-management"


@dataclass
class MonthlyPayment:
    """Represents expected payment in a month."""
    year: int
    month: int
    cusip: str
    issuer: str
    account: str
    payment_amount: float  # Semiannual coupon payment
    is_maturity: bool  # Does the bond mature this month?
    maturity_principal: float  # Principal returned at maturity


def calculate_monthly_income(
    start_date: Optional[date] = None,
    months_ahead: int = 24
) -> list[MonthlyPayment]:
    """
    Calculate expected income for each month.

    Returns list of MonthlyPayment objects for each payment expected.
    """
    if start_date is None:
        start_date = date.today()

    holdings = get_holdings_with_metadata()
    payments = []

    for h in holdings:
        cusip = h['cusip']
        issuer = h['issuer'] or 'Unknown'
        account = h['account']
        face_value = h['face_value']
        coupon_rate = h['coupon_rate']
        maturity_str = h['maturity_date']
        pay_month_1 = h['payment_month_1']
        pay_month_2 = h['payment_month_2']
        pay_day = h['payment_day'] or 15

        # Parse maturity date
        maturity = date.fromisoformat(maturity_str) if maturity_str else None

        # Semiannual payment amount
        semiannual_payment = face_value * coupon_rate / 2

        # Generate payments for each month in the projection period
        current = start_date.replace(day=1)
        end_date = date(
            start_date.year + (start_date.month + months_ahead - 1) // 12,
            (start_date.month + months_ahead - 1) % 12 + 1,
            1
        )

        while current <= end_date:
            year = current.year
            month = current.month

            # Skip if bond has already matured
            if maturity and date(year, month, pay_day) > maturity:
                current = date(year + (month // 12), (month % 12) + 1, 1)
                continue

            # Check if this is a payment month
            is_payment_month = month in (pay_month_1, pay_month_2)

            # Check if this is the maturity month
            is_maturity_month = (maturity and
                                  maturity.year == year and
                                  maturity.month == month)

            if is_payment_month or is_maturity_month:
                payments.append(MonthlyPayment(
                    year=year,
                    month=month,
                    cusip=cusip,
                    issuer=issuer[:30],
                    account=account,
                    payment_amount=semiannual_payment if is_payment_month else 0,
                    is_maturity=is_maturity_month,
                    maturity_principal=face_value if is_maturity_month else 0
                ))

            # Move to next month
            if month == 12:
                current = date(year + 1, 1, 1)
            else:
                current = date(year, month + 1, 1)

    return payments


def aggregate_monthly_totals(
    payments: list[MonthlyPayment]
) -> dict[tuple[int, int], dict]:
    """Aggregate payments by month."""
    monthly = defaultdict(lambda: {
        'coupon_income': 0.0,
        'maturities': 0.0,
        'total_cash': 0.0,
        'details': []
    })

    for p in payments:
        key = (p.year, p.month)
        monthly[key]['coupon_income'] += p.payment_amount
        monthly[key]['maturities'] += p.maturity_principal
        monthly[key]['total_cash'] += p.payment_amount + p.maturity_principal
        monthly[key]['details'].append(p)

    return dict(monthly)


def print_monthly_projection(months_ahead: int = 24):
    """Print monthly income projection."""
    payments = calculate_monthly_income(months_ahead=months_ahead)
    monthly = aggregate_monthly_totals(payments)

    print(f"\n{'='*80}")
    print("MONTHLY BOND INCOME PROJECTION")
    print(f"{'='*80}")
    print(f"Projection period: {months_ahead} months from {date.today()}")

    # Sort by year/month
    sorted_months = sorted(monthly.keys())

    print(f"\n{'Month':<10} {'Coupon Income':>14} {'Maturities':>14} {'Total Cash':>14}")
    print("-"*54)

    total_coupon = 0
    total_maturities = 0

    for year, month in sorted_months:
        data = monthly[(year, month)]
        month_name = f"{month_abbr[month]}-{year}"
        coupon = data['coupon_income']
        maturities = data['maturities']
        total = data['total_cash']

        total_coupon += coupon
        total_maturities += maturities

        # Highlight months with maturities
        marker = " ***" if maturities > 0 else ""

        print(f"{month_name:<10} ${coupon:>13,.2f} ${maturities:>13,.2f} ${total:>13,.2f}{marker}")

    print("-"*54)
    print(f"{'TOTAL':<10} ${total_coupon:>13,.2f} ${total_maturities:>13,.2f} ${total_coupon + total_maturities:>13,.2f}")

    # Show maturity details
    maturities = [p for p in payments if p.is_maturity]
    if maturities:
        print(f"\n{'='*80}")
        print("UPCOMING MATURITIES")
        print(f"{'='*80}")
        print(f"{'Date':<12} {'CUSIP':<12} {'Issuer':<25} {'Principal':>14}")
        print("-"*65)
        for p in sorted(maturities, key=lambda x: (x.year, x.month)):
            month_name = f"{month_abbr[p.month]}-{p.year}"
            print(f"{month_name:<12} {p.cusip:<12} {p.issuer:<25} ${p.maturity_principal:>13,.0f}")

    print(f"\n{'='*80}")


def print_detailed_monthly(year: int, month: int):
    """Print detailed breakdown for a specific month."""
    payments = calculate_monthly_income(months_ahead=24)
    month_payments = [p for p in payments if p.year == year and p.month == month]

    if not month_payments:
        print(f"No payments expected in {month_abbr[month]}-{year}")
        return

    print(f"\n{'='*70}")
    print(f"DETAILED INCOME FOR {month_abbr[month].upper()}-{year}")
    print(f"{'='*70}")
    print(f"{'CUSIP':<12} {'Issuer':<25} {'Account':<15} {'Amount':>12}")
    print("-"*70)

    total = 0
    for p in sorted(month_payments, key=lambda x: x.issuer):
        amount = p.payment_amount + p.maturity_principal
        total += amount
        mat_marker = " (MAT)" if p.is_maturity else ""
        print(f"{p.cusip:<12} {p.issuer:<25} {p.account:<15} ${amount:>11,.2f}{mat_marker}")

    print("-"*70)
    print(f"{'TOTAL':<52} ${total:>11,.2f}")


def export_monthly_json(months_ahead: int = 24) -> dict:
    """Export monthly projection as JSON for dashboard use."""
    payments = calculate_monthly_income(months_ahead=months_ahead)
    monthly = aggregate_monthly_totals(payments)

    result = {
        'generated_at': datetime.now().isoformat(),
        'months_ahead': months_ahead,
        'monthly_totals': [],
        'maturities': []
    }

    for (year, month), data in sorted(monthly.items()):
        result['monthly_totals'].append({
            'year': year,
            'month': month,
            'month_name': f"{month_abbr[month]}-{year}",
            'coupon_income': data['coupon_income'],
            'maturities': data['maturities'],
            'total_cash': data['total_cash']
        })

    for p in payments:
        if p.is_maturity:
            result['maturities'].append({
                'year': p.year,
                'month': p.month,
                'cusip': p.cusip,
                'issuer': p.issuer,
                'account': p.account,
                'principal': p.maturity_principal
            })

    # Save to cache
    output_file = CACHE_DIR / "monthly_income.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\nExported to {output_file}")

    return result


def main():
    import sys

    # Check if we need to sync from Fidelity first
    if "--sync" in sys.argv:
        print("Syncing from Fidelity...")
        portfolio = fetch_bond_holdings(headless="--headed" not in sys.argv)
        if portfolio and portfolio.holdings:
            sync_from_portfolio(portfolio.holdings)
            print(f"Synced {len(portfolio.holdings)} bonds to database")
        else:
            print("Failed to fetch holdings")
            sys.exit(1)

    if "--db" in sys.argv:
        print_database_summary()

    if "--detail" in sys.argv:
        # Parse month from args like --detail 2026-03
        idx = sys.argv.index("--detail")
        if idx + 1 < len(sys.argv):
            parts = sys.argv[idx + 1].split("-")
            if len(parts) == 2:
                year, month = int(parts[0]), int(parts[1])
                print_detailed_monthly(year, month)
                return

    if "--export" in sys.argv:
        export_monthly_json()

    # Default: show monthly projection
    months = 24
    if "--months" in sys.argv:
        idx = sys.argv.index("--months")
        if idx + 1 < len(sys.argv):
            months = int(sys.argv[idx + 1])

    print_monthly_projection(months_ahead=months)


if __name__ == "__main__":
    main()
