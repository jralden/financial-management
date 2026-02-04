#!/usr/bin/env python3
"""
Extract structured account data from Fidelity.
"""

import os
import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
FIDELITY_URL = os.getenv("FIDELITY_URL", "digital.fidelity.com/prgw/digital/login/full-page")
LOGIN_URL = f"https://{FIDELITY_URL}" if not FIDELITY_URL.startswith("http") else FIDELITY_URL
PORTFOLIO_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"


@dataclass
class Account:
    name: str
    account_number: str
    account_type: str  # Investment, Retirement, Authorized
    balance: float
    daily_change: float
    daily_change_percent: float


@dataclass
class PortfolioSummary:
    timestamp: str
    total_balance: float
    total_daily_change: float
    total_daily_change_percent: float
    accounts: list[Account]


def parse_dollar_amount(text: str) -> float:
    """Parse a dollar amount string to float."""
    if not text:
        return 0.0
    # Remove $ and commas
    cleaned = text.replace('$', '').replace(',', '').strip()
    # Handle negative amounts (could be with - or parentheses)
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_percent(text: str) -> float:
    """Parse a percentage string to float."""
    if not text:
        return 0.0
    cleaned = text.replace('%', '').replace('(', '').replace(')', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def login(page: Page) -> bool:
    """Login to Fidelity. Returns True if successful."""
    print("[Login] Navigating to login page...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    # Check if already logged in
    if "portfolio" in page.url.lower() or "summary" in page.url.lower():
        print("[Login] Already logged in!")
        return True

    if "login" not in page.url.lower():
        print(f"[Login] Unexpected URL: {page.url}")
        return False

    print("[Login] Entering credentials...")
    page.locator('#dom-username-input').type(FIDELITY_USERNAME, delay=50)
    page.wait_for_timeout(300)
    page.locator('#dom-pswd-input').type(FIDELITY_PASSWORD, delay=50)
    page.wait_for_timeout(300)
    page.locator('#dom-pswd-input').press("Enter")

    print("[Login] Waiting for login result...")
    page.wait_for_timeout(8000)

    # Check for 2FA
    page_text = page.locator("body").text_content() or ""
    if "authenticator" in page_text.lower() or "security code" in page_text.lower():
        print("[Login] 2FA detected - waiting 60s for manual completion...")
        page.wait_for_timeout(60000)

    if "login" in page.url.lower():
        print("[Login] FAILED")
        return False

    print("[Login] SUCCESS!")
    return True


def extract_account_data(page: Page) -> Optional[PortfolioSummary]:
    """Extract structured account data from portfolio page."""
    print("\n[Extract] Navigating to portfolio summary...")
    page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    print(f"[Extract] Page: {page.title()}")

    accounts = []

    # Extract individual accounts from the sidebar
    # Look for account rows with balance information
    account_sections = {
        "Investment": [],
        "Retirement": [],
        "Authorized": []
    }

    # Get all text and parse it
    body_text = page.locator("body").text_content() or ""

    # Pattern for account entries: Account Name followed by account number and balance
    # Example: "Joint WROS - TOD Z24348867 $1,513,809.30 -$1,997.73 (-0.13%)"

    # Try to extract from specific elements
    # The accounts are in the left sidebar with class containing "account"

    # Look for balance elements that contain account info
    balance_elements = page.locator('[class*="balance"]').all()

    for el in balance_elements:
        text = el.text_content() or ""
        # Look for patterns like "Joint WROS - TOD Z24348867 , balance: $1,513,809.30"
        # or "balance: $X,XXX.XX, gains/losses: -$X.XX"

    # Alternative: parse the structured text we captured earlier
    # Based on the output, we can see patterns like:
    # "Joint WROS - TOD Z24348867 , balance:  $1,513,809.30, gains/losses: -$1,997.73 (-0.13%)"

    # Let's try to get account cards/rows directly
    # Look for elements that contain both account number and balance

    # Pattern for Fidelity account numbers (varies by type)
    account_pattern = re.compile(
        r'(Joint WROS - TOD|[\w\s\']+IRA|[\w\s]+)\s*'  # Account name
        r'[\(\s]*([A-Z]?\d+)[\)\s]*'  # Account number
        r'.*?'
        r'\$?([\d,]+\.?\d*)'  # Balance
        r'.*?'
        r'(-?\$?[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)?',  # Daily change
        re.IGNORECASE | re.DOTALL
    )

    # Get text content that might contain account info
    sidebar_text = ""
    try:
        sidebar = page.locator('[class*="account"]').first
        sidebar_text = sidebar.text_content() or ""
    except:
        pass

    # Parse total balance
    total_balance = 0.0
    total_change = 0.0
    total_change_pct = 0.0

    # Look for "All accounts" total
    all_accounts_match = re.search(r'All accounts.*?\$([\d,]+\.?\d*)', body_text)
    if all_accounts_match:
        total_balance = parse_dollar_amount(all_accounts_match.group(1))

    # Look for today's gain/loss
    gain_loss_match = re.search(r'(-?\$[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)\s*Today', body_text)
    if gain_loss_match:
        total_change = parse_dollar_amount(gain_loss_match.group(1))
        total_change_pct = parse_percent(gain_loss_match.group(2))

    # Extract individual accounts using the testid pattern we found
    account_elements = page.locator('[data-testid*="account"]').all()

    current_type = "Investment"
    for el in account_elements:
        text = el.text_content() or ""

        # Check for section headers
        if "Investment" in text and len(text) < 50:
            current_type = "Investment"
            continue
        elif "Retirement" in text and len(text) < 50:
            current_type = "Retirement"
            continue
        elif "Authorized" in text and len(text) < 50:
            current_type = "Authorized"
            continue

        # Try to parse account info
        # Pattern: "Joint WROS - TOD Z24348867 , balance: $1,513,809.30, gains/losses: -$1,997.73 (-0.13%)"
        account_match = re.search(
            r'([\w\s\'-]+?)\s*[\(\s]*([A-Z]?\d{5,})[\)\s]*'  # Name and number
            r'.*?balance:\s*\$([\d,]+\.?\d*)'  # Balance
            r'.*?gains/losses:\s*(-?\$?[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)',  # Change
            text,
            re.IGNORECASE
        )

        if account_match:
            name = account_match.group(1).strip()
            # Clean up the name - remove extra whitespace and section headers
            name = re.sub(r'\s+', ' ', name)  # Collapse whitespace
            name = re.sub(r'^\d+\s*', '', name)  # Remove leading numbers
            name = re.sub(r'Investment|Retirement|Authorized', '', name, flags=re.IGNORECASE)
            name = name.strip()
            # Extract just the account name if it contains "Joint WROS" or "IRA"
            if "Joint WROS" in name:
                name = "Joint WROS - TOD"
            elif "IRA" in name:
                ira_match = re.search(r"([\w']+\s*IRA)", name)
                if ira_match:
                    name = ira_match.group(1)

            number = account_match.group(2).strip()
            balance = parse_dollar_amount(account_match.group(3))
            change = parse_dollar_amount(account_match.group(4))
            change_pct = parse_percent(account_match.group(5))

            # Skip if this looks like a duplicate or header
            if balance > 0 and number:
                account = Account(
                    name=name,
                    account_number=number,
                    account_type=current_type,
                    balance=balance,
                    daily_change=change,
                    daily_change_percent=change_pct
                )
                # Avoid duplicates
                if not any(a.account_number == number for a in accounts):
                    accounts.append(account)
                    print(f"[Extract] Found: {name} ({number}): ${balance:,.2f}")

    # If regex parsing didn't work well, try a simpler approach
    # based on the known output format
    if not accounts:
        print("[Extract] Trying alternate parsing method...")

        # Parse known patterns from the raw text
        patterns = [
            (r"Joint WROS - TOD\s*Z(\d+).*?\$([\d,]+\.?\d*).*?(-?\$[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)",
             "Joint WROS - TOD", "Investment"),
            (r"John's IRA\s*(\d+).*?\$([\d,]+\.?\d*).*?(-?\$[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)",
             "John's IRA", "Retirement"),
            (r"Mary's IRA\s*(\d+).*?\$([\d,]+\.?\d*).*?(-?\$[\d,]+\.?\d*)\s*\((-?[\d.]+)%\)",
             "Mary's IRA", "Retirement"),
        ]

        for pattern, name, acc_type in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                account = Account(
                    name=name,
                    account_number=match.group(1),
                    account_type=acc_type,
                    balance=parse_dollar_amount(match.group(2)),
                    daily_change=parse_dollar_amount(match.group(3)),
                    daily_change_percent=parse_percent(match.group(4))
                )
                accounts.append(account)
                print(f"[Extract] Found: {name} ({match.group(1)}): ${account.balance:,.2f}")

    summary = PortfolioSummary(
        timestamp=datetime.now().isoformat(),
        total_balance=total_balance,
        total_daily_change=total_change,
        total_daily_change_percent=total_change_pct,
        accounts=accounts
    )

    return summary


def main():
    state_path = Path(BROWSER_STATE_PATH)
    state_path.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(state_path / "browser_data"),
            headless=False,
            slow_mo=100,
            viewport={"width": 1400, "height": 900},
        )

        page = context.new_page()

        try:
            if login(page):
                summary = extract_account_data(page)

                if summary:
                    print("\n" + "="*60)
                    print("PORTFOLIO SUMMARY")
                    print("="*60)
                    print(f"Timestamp: {summary.timestamp}")
                    print(f"Total Balance: ${summary.total_balance:,.2f}")
                    print(f"Today's Change: ${summary.total_daily_change:,.2f} ({summary.total_daily_change_percent:.2f}%)")
                    print("-"*60)
                    print("ACCOUNTS:")
                    for acc in summary.accounts:
                        print(f"  {acc.name} ({acc.account_number})")
                        print(f"    Type: {acc.account_type}")
                        print(f"    Balance: ${acc.balance:,.2f}")
                        print(f"    Today: ${acc.daily_change:,.2f} ({acc.daily_change_percent:.2f}%)")
                    print("="*60)

                    # Save to JSON
                    output = asdict(summary)
                    with open("portfolio_data.json", "w") as f:
                        json.dump(output, f, indent=2)
                    print("\nData saved to: portfolio_data.json")

                print("\nBrowser staying open for 30 seconds...")
                page.wait_for_timeout(30000)
            else:
                print("\nLogin failed.")
                page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            page.wait_for_timeout(30000)
        finally:
            context.close()


if __name__ == "__main__":
    main()
