"""
Financial Management Web Application

Deployed on Railway - serves dashboard and bond evaluation tools.
"""

from datetime import datetime, date
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
import os

from src.database.models import (
    get_session, init_database, AccountBalance, BondHolding,
    MonthlyProjection, SyncLog
)

# Account ordering - Joint WROS first, then Mary's IRA, then John's IRA
ACCOUNT_ORDER = {
    "Joint WROS - TOD": 0,
    "Mary's IRA": 1,
    "John's IRA": 2,
}

def account_sort_key(item, attr='account_name'):
    """Sort key function for ordering accounts."""
    name = getattr(item, attr) if hasattr(item, attr) else item.get(attr, '')
    return ACCOUNT_ORDER.get(name, 99)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    try:
        init_database()
    except Exception as e:
        print(f"Warning: Database initialization failed: {e}")
        print("App will start but database features may not work")
    yield


app = FastAPI(
    title="Financial Management",
    description="Bond portfolio management and income projection",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files and templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)


# Dependency
def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


# --- Pydantic Models ---

class AccountBalanceResponse(BaseModel):
    account_name: str
    account_type: str
    balance: float
    daily_change: float
    daily_change_percent: float

    class Config:
        from_attributes = True


class BondHoldingResponse(BaseModel):
    cusip: str
    issuer: str
    coupon_rate: float
    maturity_date: date
    face_value: float
    current_value: float
    account: str
    annual_income: float

    class Config:
        from_attributes = True


class MonthlyProjectionResponse(BaseModel):
    year: int
    month: int
    month_name: str
    coupon_income: float
    maturities: float
    total_cash: float

    class Config:
        from_attributes = True


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page."""
    # Get account balances sorted in specified order
    balances = db.query(AccountBalance).all()
    balances = sorted(balances, key=lambda b: account_sort_key(b, 'account_name'))
    total_balance = sum(b.balance for b in balances)
    total_change = sum(b.daily_change for b in balances)

    # Get bonds grouped by account
    holdings = db.query(BondHolding).order_by(BondHolding.maturity_date).all()
    bonds_by_account = {}
    for account_name in ACCOUNT_ORDER.keys():
        account_bonds = [h for h in holdings if h.account == account_name]
        if account_bonds:
            bonds_by_account[account_name] = {
                'bonds': account_bonds,
                'count': len(account_bonds),
                'face_value': sum(h.face_value for h in account_bonds),
                'annual_income': sum(h.face_value * h.coupon_rate for h in account_bonds)
            }

    # Get next 12 months projections
    today = datetime.now()
    projections = db.query(MonthlyProjection).filter(
        (MonthlyProjection.year > today.year) |
        ((MonthlyProjection.year == today.year) & (MonthlyProjection.month >= today.month))
    ).order_by(MonthlyProjection.year, MonthlyProjection.month).limit(12).all()

    # Calculate next month and 12-month income per account (from bond holdings)
    next_month = today.month + 1 if today.month < 12 else 1
    next_month_year = today.year if today.month < 12 else today.year + 1

    account_summaries = {}
    for account_name, data in bonds_by_account.items():
        next_month_income = 0
        twelve_month_income = 0

        for bond in data['bonds']:
            # Check for next month coupon payment
            if bond.payment_month_1 == next_month or bond.payment_month_2 == next_month:
                # Only count if bond hasn't matured before next month
                if not (bond.maturity_date.year < next_month_year or
                        (bond.maturity_date.year == next_month_year and bond.maturity_date.month < next_month)):
                    next_month_income += (bond.face_value * bond.coupon_rate) / 2

            # Calculate 12-month income (coupon payments only, not maturities)
            for i in range(12):
                check_month = (today.month + i) % 12 + 1
                check_year = today.year + (today.month + i) // 12

                # Skip if bond already matured
                if (bond.maturity_date.year < check_year or
                    (bond.maturity_date.year == check_year and bond.maturity_date.month < check_month)):
                    continue

                # Coupon payment only
                if bond.payment_month_1 == check_month or bond.payment_month_2 == check_month:
                    twelve_month_income += (bond.face_value * bond.coupon_rate) / 2

        account_summaries[account_name] = {
            'next_month_income': next_month_income,
            'twelve_month_income': twelve_month_income,
            'bond_count': data['count'],
            'face_value': data['face_value'],
            'annual_income': data['annual_income']
        }

    # Get last sync
    last_sync = db.query(SyncLog).filter(
        SyncLog.status == 'success'
    ).order_by(SyncLog.completed_at.desc()).first()

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
            'cash_balance': balance.cash_balance or 0,
            'bond_count': summary.get('bond_count', 0),
            'face_value': summary.get('face_value', 0),
            'next_month_income': summary.get('next_month_income', 0),
            'twelve_month_income': summary.get('twelve_month_income', 0),
        })

    total_cash_balance = sum(a['cash_balance'] for a in combined_accounts)

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
        "last_sync": last_sync,
        "now": datetime.now()
    })


@app.get("/api/balances")
async def get_balances(db: Session = Depends(get_db)):
    """Get all account balances."""
    balances = db.query(AccountBalance).all()
    return {
        "balances": [
            {
                "account_name": b.account_name,
                "account_type": b.account_type,
                "balance": b.balance,
                "daily_change": b.daily_change,
                "daily_change_percent": b.daily_change_percent,
                "as_of": b.as_of.isoformat() if b.as_of else None
            }
            for b in balances
        ],
        "total": sum(b.balance for b in balances)
    }


@app.get("/api/holdings")
async def get_holdings(db: Session = Depends(get_db)):
    """Get all bond holdings."""
    holdings = db.query(BondHolding).order_by(BondHolding.maturity_date).all()
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
                "annual_income": h.face_value * h.coupon_rate,
                "payment_months": [h.payment_month_1, h.payment_month_2],
                "payment_verified": h.payment_verified
            }
            for h in holdings
        ],
        "summary": {
            "count": len(holdings),
            "total_face_value": sum(h.face_value for h in holdings),
            "total_annual_income": sum(h.face_value * h.coupon_rate for h in holdings)
        }
    }


@app.get("/api/projections")
async def get_projections(months: int = 24, db: Session = Depends(get_db)):
    """Get monthly income projections."""
    projections = db.query(MonthlyProjection).order_by(
        MonthlyProjection.year, MonthlyProjection.month
    ).limit(months).all()

    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    return {
        "projections": [
            {
                "year": p.year,
                "month": p.month,
                "month_name": f"{month_names[p.month]}-{p.year}",
                "coupon_income": p.coupon_income,
                "maturities": p.maturities,
                "total_cash": p.total_cash
            }
            for p in projections
        ],
        "totals": {
            "coupon_income": sum(p.coupon_income for p in projections),
            "maturities": sum(p.maturities for p in projections),
            "total_cash": sum(p.total_cash for p in projections)
        }
    }


@app.get("/api/maturities")
async def get_upcoming_maturities(months: int = 12, db: Session = Depends(get_db)):
    """Get bonds maturing within N months."""
    today = date.today()
    cutoff = date(today.year + (today.month + months - 1) // 12,
                  (today.month + months - 1) % 12 + 1, 1)

    holdings = db.query(BondHolding).filter(
        BondHolding.maturity_date <= cutoff
    ).order_by(BondHolding.maturity_date).all()

    return {
        "maturities": [
            {
                "cusip": h.cusip,
                "issuer": h.issuer,
                "maturity_date": h.maturity_date.isoformat(),
                "face_value": h.face_value,
                "account": h.account
            }
            for h in holdings
        ],
        "total_principal": sum(h.face_value for h in holdings)
    }


@app.get("/api/sync-status")
async def get_sync_status(db: Session = Depends(get_db)):
    """Get status of last data sync."""
    last_sync = db.query(SyncLog).order_by(SyncLog.completed_at.desc()).first()

    if not last_sync:
        return {"status": "never", "message": "No sync recorded"}

    return {
        "status": last_sync.status,
        "sync_type": last_sync.sync_type,
        "records_synced": last_sync.records_synced,
        "started_at": last_sync.started_at.isoformat() if last_sync.started_at else None,
        "completed_at": last_sync.completed_at.isoformat() if last_sync.completed_at else None,
        "error_message": last_sync.error_message
    }


@app.get("/holdings", response_class=HTMLResponse)
async def holdings_page(request: Request, db: Session = Depends(get_db)):
    """Bond holdings page."""
    holdings = db.query(BondHolding).order_by(BondHolding.maturity_date).all()

    # Group holdings by account in specified order
    holdings_by_account = {}
    for account_name in ACCOUNT_ORDER.keys():
        account_bonds = [h for h in holdings if h.account == account_name]
        if account_bonds:
            holdings_by_account[account_name] = {
                'bonds': account_bonds,
                'count': len(account_bonds),
                'face_value': sum(h.face_value for h in account_bonds),
                'annual_income': sum(h.face_value * h.coupon_rate for h in account_bonds)
            }

    # Get last sync
    last_sync = db.query(SyncLog).filter(
        SyncLog.status == 'success'
    ).order_by(SyncLog.completed_at.desc()).first()

    return templates.TemplateResponse("holdings.html", {
        "request": request,
        "holdings_by_account": holdings_by_account,
        "total_face_value": sum(h.face_value for h in holdings),
        "total_annual_income": sum(h.face_value * h.coupon_rate for h in holdings),
        "total_count": len(holdings),
        "last_sync": last_sync,
        "now": datetime.now()
    })


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request, db: Session = Depends(get_db)):
    """Monthly results page - cash flow by account."""
    today = datetime.now()

    # Get all bond holdings
    holdings = db.query(BondHolding).all()

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
                        month_income += (bond.face_value * bond.coupon_rate) / 2

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

    # Get last sync
    last_sync = db.query(SyncLog).filter(
        SyncLog.status == 'success'
    ).order_by(SyncLog.completed_at.desc()).first()

    return templates.TemplateResponse("results.html", {
        "request": request,
        "results_by_account": results_by_account,
        "years": years,
        "grand_totals_by_year": grand_totals_by_year,
        "current_month": today.month,
        "current_year": current_year,
        "last_sync": last_sync,
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
