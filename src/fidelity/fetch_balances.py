#!/usr/bin/env python3
"""
Fast headless balance fetch with timing.

Usage:
    python -m src.fidelity.fetch_balances          # Headless mode (fast)
    python -m src.fidelity.fetch_balances --headed # Visible browser (debug)
"""

import os
import re
import json
import sys
import time
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
    account_type: str
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
    fetch_time_seconds: float


def parse_dollar_amount(text: str) -> float:
    if not text:
        return 0.0
    cleaned = text.replace('$', '').replace(',', '').strip()
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_percent(text: str) -> float:
    if not text:
        return 0.0
    cleaned = text.replace('%', '').replace('(', '').replace(')', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def login(page: Page) -> bool:
    """Login to Fidelity."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    # Check if already logged in
    if "portfolio" in page.url.lower() or "summary" in page.url.lower():
        return True

    if "login" not in page.url.lower():
        return False

    # Enter credentials
    page.locator('#dom-username-input').type(FIDELITY_USERNAME, delay=30)
    page.locator('#dom-pswd-input').type(FIDELITY_PASSWORD, delay=30)
    page.locator('#dom-pswd-input').press("Enter")

    page.wait_for_timeout(5000)

    # Check for 2FA
    page_text = page.locator("body").text_content() or ""
    if "authenticator" in page_text.lower() or "security code" in page_text.lower() or "notification" in page_text.lower():
        # Check if we're in headed mode (can complete 2FA manually)
        # We detect this by checking if slow_mo was set (hacky but works)
        print("2FA required - waiting 90 seconds for manual completion...", file=sys.stderr)
        page.wait_for_timeout(90000)
        # Check again
        if "login" in page.url.lower():
            print("ERROR: 2FA not completed", file=sys.stderr)
            return False

    return "login" not in page.url.lower()


def extract_balances(page: Page) -> Optional[PortfolioSummary]:
    """Extract account balances."""
    page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    body_text = page.locator("body").text_content() or ""
    accounts = []

    # Parse total
    total_balance = 0.0
    total_change = 0.0
    total_change_pct = 0.0

    all_accounts_match = re.search(r'All accounts.*?\$([\d,]+\.?\d*)', body_text)
    if all_accounts_match:
        total_balance = parse_dollar_amount(all_accounts_match.group(1))

    gain_loss_match = re.search(r'([+-]?\$[\d,]+\.?\d*)\s*\(([+-]?[\d.]+)%\)\s*Today', body_text)
    if gain_loss_match:
        total_change = parse_dollar_amount(gain_loss_match.group(1))
        total_change_pct = parse_percent(gain_loss_match.group(2))

    # Parse individual accounts
    account_elements = page.locator('[data-testid*="account"]').all()
    current_type = "Investment"

    for el in account_elements:
        text = el.text_content() or ""

        if "Investment" in text and len(text) < 50:
            current_type = "Investment"
            continue
        elif "Retirement" in text and len(text) < 50:
            current_type = "Retirement"
            continue
        elif "Authorized" in text and len(text) < 50:
            current_type = "Authorized"
            continue

        account_match = re.search(
            r'([\w\s\'-]+?)\s*[\(\s]*([A-Z]?\d{5,})[\)\s]*'
            r'.*?balance:\s*\$([\d,]+\.?\d*)'
            r'.*?gains/losses:\s*([+-]?\$?[\d,]+\.?\d*)\s*\(([+-]?[\d.]+)%\)',
            text,
            re.IGNORECASE
        )

        if account_match:
            name = account_match.group(1).strip()
            name = re.sub(r'\s+', ' ', name)
            name = re.sub(r'^\d+\s*', '', name)
            name = re.sub(r'Investment|Retirement|Authorized', '', name, flags=re.IGNORECASE)
            name = name.strip()
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

            if balance > 0 and number and not any(a.account_number == number for a in accounts):
                accounts.append(Account(
                    name=name,
                    account_number=number,
                    account_type=current_type,
                    balance=balance,
                    daily_change=change,
                    daily_change_percent=change_pct
                ))

    return PortfolioSummary(
        timestamp=datetime.now().isoformat(),
        total_balance=total_balance,
        total_daily_change=total_change,
        total_daily_change_percent=total_change_pct,
        accounts=accounts,
        fetch_time_seconds=0.0  # Will be set by caller
    )


def fetch_balances(headless: bool = True) -> Optional[PortfolioSummary]:
    """Fetch balances. Returns PortfolioSummary or None on failure."""
    start_time = time.time()

    state_path = Path(BROWSER_STATE_PATH)
    state_path.mkdir(exist_ok=True)

    with sync_playwright() as p:
        # Try Firefox which has different fingerprints than Chrome
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(state_path / "firefox_data"),
            headless=headless,
            viewport={"width": 1400, "height": 900},
        )

        page = context.new_page()

        try:
            if not login(page):
                return None

            summary = extract_balances(page)
            if summary:
                summary.fetch_time_seconds = time.time() - start_time

            return summary

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return None
        finally:
            context.close()


def main():
    headless = "--headed" not in sys.argv

    print(f"Fetching balances ({'headless' if headless else 'headed'} mode)...")
    start = time.time()

    summary = fetch_balances(headless=headless)

    elapsed = time.time() - start

    if summary:
        print(f"\n{'='*50}")
        print(f"FETCH COMPLETE in {elapsed:.2f} seconds")
        print(f"{'='*50}")
        print(f"Total: ${summary.total_balance:,.2f} ({summary.total_daily_change:+,.2f})")
        print(f"{'─'*50}")
        for acc in summary.accounts:
            print(f"  {acc.name}: ${acc.balance:,.2f} ({acc.daily_change:+,.2f})")
        print(f"{'='*50}")

        # Save to JSON
        with open("portfolio_data.json", "w") as f:
            json.dump(asdict(summary), f, indent=2)
        print(f"Saved to portfolio_data.json")
    else:
        print(f"\nFetch FAILED after {elapsed:.2f} seconds")
        sys.exit(1)


if __name__ == "__main__":
    main()
