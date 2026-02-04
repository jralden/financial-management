#!/usr/bin/env python3
"""
Extract bond holdings and project income by tax year.

VS-2: Bond Income Projection by Tax Year
"""

import os
import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from collections import defaultdict
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
LOGIN_URL = "https://digital.fidelity.com/prgw/digital/login/full-page"
POSITIONS_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/positions"

# Cache location
CACHE_DIR = Path.home() / ".cache" / "financial-management"
BONDS_CACHE_FILE = CACHE_DIR / "bond_holdings.json"


@dataclass
class BondHolding:
    """Represents a single bond holding."""
    cusip: str
    issuer: str
    coupon_rate: float  # As decimal (0.08875 for 8.875%)
    maturity_date: date
    face_value: float   # In dollars
    current_value: float
    account: str        # Which account holds this bond

    @property
    def annual_income(self) -> float:
        """Calculate annual coupon income."""
        return self.face_value * self.coupon_rate

    @property
    def semiannual_payment(self) -> float:
        """Most bonds pay semiannually."""
        return self.annual_income / 2

    def income_for_year(self, year: int) -> float:
        """Calculate income for a specific tax year, accounting for maturity."""
        today = date.today()

        # If bond already matured, no income
        if self.maturity_date.year < year:
            return 0.0

        # For maturity year, prorate based on maturity month
        if self.maturity_date.year == year:
            # Assume coupons paid semiannually
            # If matures after June, gets both payments
            # If matures before June, gets only first payment
            months_active = self.maturity_date.month
            if months_active >= 6:
                return self.annual_income
            else:
                return self.semiannual_payment

        # Bond active for full year
        return self.annual_income


@dataclass
class BondPortfolio:
    """Collection of bond holdings with income projections."""
    timestamp: str
    holdings: list[BondHolding]
    fetch_time_seconds: float = 0.0

    def total_face_value(self) -> float:
        return sum(h.face_value for h in self.holdings)

    def total_current_value(self) -> float:
        return sum(h.current_value for h in self.holdings)

    def total_annual_income(self) -> float:
        return sum(h.annual_income for h in self.holdings)

    def income_by_year(self, start_year: int = None, years: int = 5) -> dict[int, float]:
        """Project income by tax year."""
        if start_year is None:
            start_year = date.today().year

        result = {}
        for year in range(start_year, start_year + years):
            result[year] = sum(h.income_for_year(year) for h in self.holdings)
        return result

    def income_by_account(self) -> dict[str, float]:
        """Get annual income grouped by account."""
        result = defaultdict(float)
        for h in self.holdings:
            result[h.account] += h.annual_income
        return dict(result)

    def maturing_bonds(self, within_years: int = 2) -> list[BondHolding]:
        """Get bonds maturing within N years."""
        cutoff = date.today().replace(year=date.today().year + within_years)
        return sorted(
            [h for h in self.holdings if h.maturity_date <= cutoff],
            key=lambda h: h.maturity_date
        )


def parse_maturity_date(text: str) -> Optional[date]:
    """Parse maturity date from various formats."""
    # Try different patterns
    patterns = [
        (r'([A-Za-z]{3})-(\d{1,2})-(\d{4})', lambda m: datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", '%b-%d-%Y').date()),
        (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda m: datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", '%m/%d/%Y').date()),
        (r'(\d{4})-(\d{2})-(\d{2})', lambda m: datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", '%Y-%m-%d').date()),
    ]

    for pattern, parser in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return parser(match)
            except ValueError:
                continue
    return None


def login(page: Page) -> bool:
    """Login to Fidelity."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    if "portfolio" in page.url.lower() or "positions" in page.url.lower():
        return True

    if "login" not in page.url.lower():
        return False

    page.locator('#dom-username-input').type(FIDELITY_USERNAME, delay=30)
    page.locator('#dom-pswd-input').type(FIDELITY_PASSWORD, delay=30)
    page.locator('#dom-pswd-input').press("Enter")
    page.wait_for_timeout(5000)

    return "login" not in page.url.lower()


def extract_bonds(page: Page) -> list[BondHolding]:
    """Extract bond holdings from positions page using DOM inspection."""
    holdings = []

    # Scroll to load all content
    for _ in range(3):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(1000)

    # Get the page text
    all_text = page.locator("body").inner_text()
    lines = all_text.split('\n')

    current_account = "Unknown"
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Check for account headers
        if "Joint WROS - TOD" in line and "Z" in line:
            current_account = "Joint WROS - TOD"
        elif "John's IRA" in line:
            current_account = "John's IRA"
        elif "Mary's IRA" in line:
            current_account = "Mary's IRA"

        # Look for CUSIP pattern - 9 alphanumeric chars, typically starts with digits
        # Examples: 00440EAC1, 054536AA5, 912810EW4
        cusip_match = re.match(r'^([0-9]{2,6}[A-Z0-9]{3,7})$', line)

        if cusip_match and len(line) == 9:
            cusip = cusip_match.group(1)

            # Look ahead for bond data (next 15-20 lines)
            context_lines = lines[i:i+20]
            context = '\n'.join(context_lines)

            # Look for coupon rate and maturity pattern like "8.875%  Aug-15-2029"
            # or the company name line like "CHUBB INA HLDGS INC BOND 8.87500% 08/15/2029"
            coupon_match = re.search(r'(\d+\.?\d*)%', context)
            coupon_rate = float(coupon_match.group(1)) / 100 if coupon_match else None

            maturity = parse_maturity_date(context)

            # Extract issuer from the bond description line
            issuer = "Unknown"
            for ctx_line in context_lines[1:10]:
                ctx_line = ctx_line.strip()
                # Look for lines containing company names (all caps with BOND/CORP/INC etc)
                if re.search(r'(BOND|CORP|INC|CO\b|LLC|FIN|NOTE|CAP)', ctx_line, re.IGNORECASE):
                    issuer = ctx_line[:50]
                    break

            # Find quantity (face value) - look for a standalone number like "21,000"
            # It appears after the price data
            face_value = None
            for ctx_line in context_lines:
                ctx_line = ctx_line.strip()
                # Match patterns like "21,000" or "150,000" (face values)
                qty_match = re.match(r'^(\d{1,3}(?:,\d{3})*)$', ctx_line)
                if qty_match:
                    val = float(qty_match.group(1).replace(',', ''))
                    # Face values are typically between 1,000 and 500,000
                    if 1000 <= val <= 500000:
                        face_value = val
                        break

            # Look for current value ($ amount in range $10k-$500k)
            current_value = 0.0
            value_matches = re.findall(r'\$(\d{1,3}(?:,\d{3})*\.?\d*)', context)
            if value_matches:
                values = [float(v.replace(',', '')) for v in value_matches]
                # Current value should be > $1000 but not the face value
                reasonable_values = [v for v in values if 1000 < v < 500000]
                if reasonable_values:
                    current_value = max(reasonable_values)

            # Validate we have minimum required data for a bond
            if coupon_rate and maturity and face_value:
                holding = BondHolding(
                    cusip=cusip,
                    issuer=issuer,
                    coupon_rate=coupon_rate,
                    maturity_date=maturity,
                    face_value=face_value,
                    current_value=current_value,
                    account=current_account
                )

                # Avoid duplicates
                if not any(h.cusip == cusip for h in holdings):
                    holdings.append(holding)
                    print(f"  {cusip}: {issuer[:30]:<30} {coupon_rate*100:5.2f}% {maturity} ${face_value:>10,.0f}")

        i += 1

    return holdings


def fetch_bond_holdings(headless: bool = True) -> Optional[BondPortfolio]:
    """Fetch all bond holdings from Fidelity."""
    import time
    start_time = time.time()

    state_path = Path(BROWSER_STATE_PATH)

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(state_path / "firefox_data"),
            headless=headless,
            viewport={"width": 1400, "height": 1200},
        )

        page = context.new_page()

        try:
            if not login(page):
                print("Login failed")
                return None

            print("\nNavigating to Positions...")
            page.goto(POSITIONS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            page.screenshot(path="positions_debug.png")

            print("\nExtracting bond holdings...")
            holdings = extract_bonds(page)

            print(f"\nFound {len(holdings)} bonds")

            portfolio = BondPortfolio(
                timestamp=datetime.now().isoformat(),
                holdings=holdings,
                fetch_time_seconds=time.time() - start_time
            )

            return portfolio

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            context.close()


def save_portfolio(portfolio: BondPortfolio):
    """Save portfolio to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Convert to JSON-serializable format
    data = {
        "timestamp": portfolio.timestamp,
        "fetch_time_seconds": portfolio.fetch_time_seconds,
        "holdings": [
            {
                **{k: v for k, v in asdict(h).items() if k != 'maturity_date'},
                "maturity_date": h.maturity_date.isoformat(),
                "annual_income": h.annual_income,
            }
            for h in portfolio.holdings
        ],
        "summary": {
            "total_face_value": portfolio.total_face_value(),
            "total_current_value": portfolio.total_current_value(),
            "total_annual_income": portfolio.total_annual_income(),
            "income_by_year": portfolio.income_by_year(),
            "bond_count": len(portfolio.holdings),
        }
    }

    with open(BONDS_CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved to {BONDS_CACHE_FILE}")


def print_income_projection(portfolio: BondPortfolio):
    """Print income projection report."""
    print("\n" + "="*70)
    print("BOND INCOME PROJECTION BY TAX YEAR")
    print("="*70)

    print(f"\nPortfolio Summary:")
    print(f"  Total Bonds: {len(portfolio.holdings)}")
    print(f"  Total Face Value: ${portfolio.total_face_value():,.2f}")
    print(f"  Total Current Value: ${portfolio.total_current_value():,.2f}")
    print(f"  Total Annual Income: ${portfolio.total_annual_income():,.2f}")

    print(f"\nProjected Income by Tax Year:")
    print("-"*40)
    income_by_year = portfolio.income_by_year(years=6)
    max_income = max(income_by_year.values()) if income_by_year.values() else 1
    for year, income in income_by_year.items():
        bar_len = int(40 * income / max_income) if max_income > 0 else 0
        bar = "█" * bar_len
        print(f"  {year}: ${income:>12,.2f}  {bar}")

    print(f"\nIncome by Account:")
    print("-"*40)
    for account, income in portfolio.income_by_account().items():
        print(f"  {account:<20} ${income:>12,.2f}")

    print(f"\nBonds Maturing Within 2 Years:")
    print("-"*70)
    maturing = portfolio.maturing_bonds(within_years=2)
    if maturing:
        for h in maturing:
            print(f"  {h.maturity_date}  {h.cusip}  {h.issuer[:25]:<25} "
                  f"${h.face_value:>10,.0f}  {h.coupon_rate*100:5.2f}%")
    else:
        print("  None")

    print("="*70)


def main():
    import sys

    headless = "--headed" not in sys.argv

    print(f"Fetching bond holdings ({'headless' if headless else 'headed'} mode)...")

    portfolio = fetch_bond_holdings(headless=headless)

    if portfolio and portfolio.holdings:
        print_income_projection(portfolio)
        save_portfolio(portfolio)
    else:
        print("Failed to fetch bond holdings or no bonds found")
        sys.exit(1)


if __name__ == "__main__":
    main()
