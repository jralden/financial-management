#!/usr/bin/env python3
"""
Explore Fidelity Positions page to understand bond data structure.
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
FIDELITY_URL = os.getenv("FIDELITY_URL", "digital.fidelity.com/prgw/digital/login/full-page")
LOGIN_URL = f"https://{FIDELITY_URL}" if not FIDELITY_URL.startswith("http") else FIDELITY_URL
POSITIONS_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/positions"


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


def explore_positions(page: Page):
    """Navigate to positions and explore the structure."""
    print("\n[1] Navigating to Positions page...")
    page.goto(POSITIONS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    page.screenshot(path="positions_page.png")
    print(f"Screenshot saved: positions_page.png")
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")

    # Look for bond-related content
    body_text = page.locator("body").text_content() or ""

    # Save raw text for analysis
    with open("positions_raw.txt", "w") as f:
        f.write(body_text)
    print("Raw text saved: positions_raw.txt")

    # Look for tables or structured data
    print("\n[2] Looking for data structures...")

    # Check for tables
    tables = page.locator("table").all()
    print(f"Found {len(tables)} tables")

    # Check for position rows/cards
    position_selectors = [
        '[data-testid*="position"]',
        '[class*="position"]',
        '[class*="holding"]',
        'tr[class*="row"]',
    ]

    for selector in position_selectors:
        elements = page.locator(selector).all()
        if elements:
            print(f"\nFound {len(elements)} elements matching '{selector}'")
            for i, el in enumerate(elements[:5]):
                text = (el.text_content() or "")[:200].replace('\n', ' ')
                print(f"  [{i}] {text}...")

    # Look for bond-specific keywords
    print("\n[3] Searching for bond-related content...")
    bond_keywords = ["CUSIP", "Coupon", "Maturity", "Bond", "Treasury", "Corporate"]
    for keyword in bond_keywords:
        count = body_text.lower().count(keyword.lower())
        if count > 0:
            print(f"  '{keyword}': found {count} times")

    # Try to find the positions table/list
    print("\n[4] Analyzing page structure...")

    # Look for expandable sections or tabs
    tabs = page.locator('[role="tab"], [class*="tab"]').all()
    if tabs:
        print(f"\nFound {len(tabs)} tabs:")
        for tab in tabs[:10]:
            print(f"  - {(tab.text_content() or '').strip()}")

    # Look for filter/view options
    filters = page.locator('select, [class*="filter"], [class*="dropdown"]').all()
    if filters:
        print(f"\nFound {len(filters)} filter/dropdown elements")


def main():
    state_path = Path(BROWSER_STATE_PATH)

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(state_path / "firefox_data"),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )

        page = context.new_page()

        try:
            if login(page):
                print("Login successful!")
                explore_positions(page)

                print("\n" + "="*50)
                print("Browser staying open for 60 seconds for inspection")
                print("="*50)
                page.wait_for_timeout(60000)
            else:
                print("Login failed")
                page.wait_for_timeout(30000)

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()


if __name__ == "__main__":
    main()
