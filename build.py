#!/usr/bin/env python3
"""
Static site builder for Financial Management.

Reads bond data from local cache, renders holdings and results pages
via Jinja2, and writes static HTML to docs/.

Usage:
    python build.py              # Build static site
    python build.py --commit     # Build, commit, and push if changed
"""

import argparse
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.webapp.cache_reader import (
    load_bond_holdings, get_bonds_by_account, ACCOUNT_ORDER
)

DOCS_DIR = Path(__file__).parent / "docs"
TEMPLATES_DIR = Path(__file__).parent / "src" / "webapp" / "templates"


def build_holdings_context(holdings, bonds_timestamp):
    """Build template context for the holdings page."""
    holdings_by_account = get_bonds_by_account(holdings)
    now = datetime.now()

    return {
        "holdings_by_account": holdings_by_account,
        "total_face_value": sum(h.face_value for h in holdings),
        "total_annual_income": sum(h.annual_income for h in holdings),
        "total_count": len(holdings),
        "data_date": bonds_timestamp.strftime("%B %d, %Y") if bonds_timestamp else "Unknown",
        "now": now,
    }


def build_results_context(holdings, bonds_timestamp):
    """Build template context for the results page."""
    today = datetime.now()
    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    current_year = today.year
    years = [current_year, current_year + 1, current_year + 2]

    results_by_account = {}
    for account_name in ACCOUNT_ORDER.keys():
        account_bonds = [h for h in holdings if h.account == account_name]
        if not account_bonds:
            continue

        account_results = {}
        for year in years:
            year_data = []
            year_total = {'coupon_income': 0, 'maturities': 0, 'total_cash': 0}

            for month in range(1, 13):
                month_income = 0
                month_maturities = 0

                for bond in account_bonds:
                    bond_matured_before = (
                        bond.maturity_date.year < year or
                        (bond.maturity_date.year == year and bond.maturity_date.month < month)
                    )
                    if bond_matured_before:
                        continue

                    if bond.payment_month_1 == month or bond.payment_month_2 == month:
                        month_income += bond.annual_income / 2

                    if bond.maturity_date.year == year and bond.maturity_date.month == month:
                        month_maturities += bond.face_value

                total_cash = month_income + month_maturities
                is_historical = (year < current_year) or (year == current_year and month < today.month)

                year_data.append({
                    'month': month,
                    'month_name': month_names[month],
                    'coupon_income': month_income,
                    'maturities': month_maturities,
                    'total_cash': total_cash,
                    'is_historical': is_historical
                })

                year_total['coupon_income'] += month_income
                year_total['maturities'] += month_maturities
                year_total['total_cash'] += total_cash

            account_results[year] = {
                'months': year_data,
                'total': year_total
            }

        results_by_account[account_name] = account_results

    grand_totals_by_year = {}
    for year in years:
        year_totals = {'coupon_income': 0, 'maturities': 0, 'total_cash': 0}
        for account_name, account_years in results_by_account.items():
            if year in account_years:
                year_totals['coupon_income'] += account_years[year]['total']['coupon_income']
                year_totals['maturities'] += account_years[year]['total']['maturities']
                year_totals['total_cash'] += account_years[year]['total']['total_cash']
        grand_totals_by_year[year] = year_totals

    return {
        "results_by_account": results_by_account,
        "years": years,
        "grand_totals_by_year": grand_totals_by_year,
        "current_month": today.month,
        "current_year": current_year,
        "data_date": bonds_timestamp.strftime("%B %d, %Y") if bonds_timestamp else "Unknown",
        "now": today,
    }


def build():
    """Build the static site into docs/."""
    holdings, bonds_timestamp = load_bond_holdings()
    if not holdings:
        print("ERROR: No bond holdings found in cache. Cannot build.", file=sys.stderr)
        sys.exit(1)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    DOCS_DIR.mkdir(exist_ok=True)

    # Build holdings page
    holdings_ctx = build_holdings_context(holdings, bonds_timestamp)
    holdings_template = env.get_template("holdings.html")
    holdings_html = holdings_template.render(**holdings_ctx)
    (DOCS_DIR / "holdings.html").write_text(holdings_html)
    print(f"Built holdings.html ({holdings_ctx['total_count']} bonds)")

    # Build results page
    results_ctx = build_results_context(holdings, bonds_timestamp)
    results_template = env.get_template("results.html")
    results_html = results_template.render(**results_ctx)
    (DOCS_DIR / "results.html").write_text(results_html)
    print(f"Built results.html ({len(results_ctx['years'])} years)")

    # Write index.html redirect
    index_html = '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=holdings.html"></head></html>'
    (DOCS_DIR / "index.html").write_text(index_html)
    print("Built index.html (redirect to holdings.html)")


def commit_and_push():
    """Stage docs/, commit if changed, and push."""
    repo_dir = Path(__file__).parent

    subprocess.run(["git", "add", "docs/"], cwd=repo_dir, check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_dir,
    )
    if result.returncode == 0:
        print("No changes to commit.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "commit", "-m", f"Update static site ({timestamp})"],
        cwd=repo_dir,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=repo_dir, check=True)
    print("Committed and pushed.")


def main():
    parser = argparse.ArgumentParser(description="Build static financial site")
    parser.add_argument("--commit", action="store_true",
                        help="Commit and push docs/ if changed")
    args = parser.parse_args()

    build()

    if args.commit:
        commit_and_push()


if __name__ == "__main__":
    main()
