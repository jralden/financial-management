"""
Financial Management Web Application

Deployed on Railway - serves dashboard and bond evaluation tools.
"""

from datetime import datetime, date, timezone
from typing import Optional
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from src.webapp.cache_reader import (
    load_balances, load_bond_holdings, get_cache_status,
    get_bonds_by_account, calculate_account_income, ACCOUNT_ORDER, ET_TZ
)

app = FastAPI(
    title="Financial Management",
    description="Bond portfolio management and income projection",
    version="1.0.0",
)

# Mount static files and templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)

def to_eastern(dt):
    """Convert UTC datetime to Eastern Time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET_TZ)

templates.env.filters['to_eastern'] = to_eastern


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page - reads from local scraper cache."""
    # Load data from cache files
    balances, total_balance, total_change, balances_timestamp = load_balances()
    holdings, bonds_timestamp = load_bond_holdings()

    # Get bonds grouped by account
    bonds_by_account = get_bonds_by_account(holdings)

    # Calculate income projections
    account_summaries = calculate_account_income(holdings)

    today = datetime.now()
    next_month = today.month + 1 if today.month < 12 else 1
    next_month_year = today.year if today.month < 12 else today.year + 1
    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Calculate totals across all accounts
    total_next_month_income = sum(s['next_month_income'] for s in account_summaries.values())
    total_twelve_month_income = sum(s['twelve_month_income'] for s in account_summaries.values())
    total_bonds = sum(s['bond_count'] for s in account_summaries.values())
    total_face_value = sum(s['face_value'] for s in account_summaries.values())

    # Create combined account data for unified table
    combined_accounts = []
    for balance in balances:
        account_name = balance.account_name
        summary = account_summaries.get(account_name, {})
        combined_accounts.append({
            'name': account_name,
            'balance': balance.balance,
            'daily_change': balance.daily_change,
            'daily_change_percent': balance.daily_change_percent,
            'cash_balance': balance.cash_balance,
            'bond_count': summary.get('bond_count', 0),
            'face_value': summary.get('face_value', 0),
            'next_month_income': summary.get('next_month_income', 0),
            'twelve_month_income': summary.get('twelve_month_income', 0),
        })

    total_cash_balance = sum(a['cash_balance'] for a in combined_accounts)

    # Get cache status
    cache_status = get_cache_status()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "combined_accounts": combined_accounts,
        "total_balance": total_balance,
        "total_change": total_change,
        "total_cash_balance": total_cash_balance,
        "bonds_by_account": bonds_by_account,
        "total_next_month_income": total_next_month_income,
        "total_twelve_month_income": total_twelve_month_income,
        "total_bonds": total_bonds,
        "total_face_value": total_face_value,
        "next_month_name": f"{month_names[next_month]} {next_month_year}",
        "last_fetch": balances_timestamp,
        "is_stale": cache_status.is_stale,
        "now": datetime.now()
    })


@app.get("/api/balances")
async def api_balances():
    """Get all account balances from local cache."""
    balances, total_balance, total_change, timestamp = load_balances()
    return {
        "balances": [
            {
                "account_name": b.account_name,
                "account_type": b.account_type,
                "balance": b.balance,
                "daily_change": b.daily_change,
                "daily_change_percent": b.daily_change_percent,
                "cash_balance": b.cash_balance,
            }
            for b in balances
        ],
        "total": total_balance,
        "as_of": timestamp.isoformat() if timestamp else None
    }


@app.get("/api/holdings")
async def api_holdings():
    """Get all bond holdings from local cache."""
    holdings, timestamp = load_bond_holdings()
    return {
        "holdings": [
            {
                "cusip": h.cusip,
                "issuer": h.issuer,
                "coupon_rate": h.coupon_rate,
                "maturity_date": h.maturity_date.isoformat(),
                "face_value": h.face_value,
                "current_value": h.current_value,
                "account": h.account,
                "annual_income": h.annual_income,
                "payment_months": [h.payment_month_1, h.payment_month_2],
            }
            for h in holdings
        ],
        "summary": {
            "count": len(holdings),
            "total_face_value": sum(h.face_value for h in holdings),
            "total_annual_income": sum(h.annual_income for h in holdings)
        },
        "as_of": timestamp.isoformat() if timestamp else None
    }


@app.get("/api/maturities")
async def api_maturities(months: int = 12):
    """Get bonds maturing within N months from local cache."""
    holdings, _ = load_bond_holdings()
    today = date.today()
    cutoff = date(today.year + (today.month + months - 1) // 12,
                  (today.month + months - 1) % 12 + 1, 1)

    upcoming = [h for h in holdings if h.maturity_date <= cutoff]

    return {
        "maturities": [
            {
                "cusip": h.cusip,
                "issuer": h.issuer,
                "maturity_date": h.maturity_date.isoformat(),
                "face_value": h.face_value,
                "account": h.account
            }
            for h in upcoming
        ],
        "total_principal": sum(h.face_value for h in upcoming)
    }


@app.get("/api/cache-status")
async def api_cache_status():
    """Get status of local cache data."""
    cache_status = get_cache_status()
    return {
        "balances_timestamp": cache_status.balances_timestamp.isoformat() if cache_status.balances_timestamp else None,
        "bonds_timestamp": cache_status.bonds_timestamp.isoformat() if cache_status.bonds_timestamp else None,
        "is_stale": cache_status.is_stale,
    }


@app.get("/holdings", response_class=HTMLResponse)
async def holdings_page(request: Request):
    """Bond holdings page - reads from local scraper cache."""
    holdings, bonds_timestamp = load_bond_holdings()
    holdings_by_account = get_bonds_by_account(holdings)
    cache_status = get_cache_status()

    return templates.TemplateResponse("holdings.html", {
        "request": request,
        "holdings_by_account": holdings_by_account,
        "total_face_value": sum(h.face_value for h in holdings),
        "total_annual_income": sum(h.annual_income for h in holdings),
        "total_count": len(holdings),
        "last_fetch": bonds_timestamp,
        "is_stale": cache_status.is_stale,
        "now": datetime.now()
    })


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    """Monthly results page - cash flow by account. Reads from local scraper cache."""
    today = datetime.now()

    # Get all bond holdings from cache
    holdings, bonds_timestamp = load_bond_holdings()
    cache_status = get_cache_status()

    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Determine year range - current year and next 2 years
    current_year = today.year
    years = [current_year, current_year + 1, current_year + 2]

    # Build results by account and month
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
                    # Check maturity first - if matured, no more payments
                    bond_matured_before = (
                        bond.maturity_date.year < year or
                        (bond.maturity_date.year == year and bond.maturity_date.month < month)
                    )
                    if bond_matured_before:
                        continue

                    # Check for coupon payment this month
                    if bond.payment_month_1 == month or bond.payment_month_2 == month:
                        month_income += bond.annual_income / 2

                    # Check for maturity this month
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

    # Calculate grand totals by year (across all accounts)
    grand_totals_by_year = {}
    for year in years:
        year_totals = {'coupon_income': 0, 'maturities': 0, 'total_cash': 0}
        for account_name, account_years in results_by_account.items():
            if year in account_years:
                year_totals['coupon_income'] += account_years[year]['total']['coupon_income']
                year_totals['maturities'] += account_years[year]['total']['maturities']
                year_totals['total_cash'] += account_years[year]['total']['total_cash']
        grand_totals_by_year[year] = year_totals

    return templates.TemplateResponse("results.html", {
        "request": request,
        "results_by_account": results_by_account,
        "years": years,
        "grand_totals_by_year": grand_totals_by_year,
        "current_month": today.month,
        "current_year": current_year,
        "last_fetch": bonds_timestamp,
        "is_stale": cache_status.is_stale,
        "now": datetime.now()
    })


# Keep /projections as redirect for backwards compatibility
@app.get("/projections", response_class=HTMLResponse)
async def projections_redirect(request: Request):
    """Redirect old projections URL to results."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/results", status_code=301)


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
