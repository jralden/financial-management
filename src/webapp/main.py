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
    # Get account balances
    balances = db.query(AccountBalance).order_by(AccountBalance.account_type).all()
    total_balance = sum(b.balance for b in balances)
    total_change = sum(b.daily_change for b in balances)

    # Get bond summary
    bond_count = db.query(BondHolding).count()
    total_face_value = db.query(func.sum(BondHolding.face_value)).scalar() or 0

    # Get next 6 months projections
    today = datetime.now()
    projections = db.query(MonthlyProjection).filter(
        (MonthlyProjection.year > today.year) |
        ((MonthlyProjection.year == today.year) & (MonthlyProjection.month >= today.month))
    ).order_by(MonthlyProjection.year, MonthlyProjection.month).limit(6).all()

    # Get last sync
    last_sync = db.query(SyncLog).filter(
        SyncLog.status == 'success'
    ).order_by(SyncLog.completed_at.desc()).first()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "balances": balances,
        "total_balance": total_balance,
        "total_change": total_change,
        "bond_count": bond_count,
        "total_face_value": total_face_value,
        "projections": projections,
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

    return templates.TemplateResponse("holdings.html", {
        "request": request,
        "holdings": holdings,
        "total_face_value": sum(h.face_value for h in holdings),
        "total_annual_income": sum(h.face_value * h.coupon_rate for h in holdings),
        "now": datetime.now()
    })


@app.get("/projections", response_class=HTMLResponse)
async def projections_page(request: Request, db: Session = Depends(get_db)):
    """Monthly projections page."""
    projections = db.query(MonthlyProjection).order_by(
        MonthlyProjection.year, MonthlyProjection.month
    ).all()

    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    return templates.TemplateResponse("projections.html", {
        "request": request,
        "projections": projections,
        "month_names": month_names,
        "now": datetime.now()
    })


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
