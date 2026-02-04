#!/usr/bin/env python3
"""
Extract account balances from Fidelity after login.
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
FIDELITY_URL = os.getenv("FIDELITY_URL", "digital.fidelity.com/prgw/digital/login/full-page")
LOGIN_URL = f"https://{FIDELITY_URL}" if not FIDELITY_URL.startswith("http") else FIDELITY_URL
PORTFOLIO_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"


def login(page) -> bool:
    """Login to Fidelity. Returns True if successful."""
    print("[Login] Navigating to login page...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    # Check if already logged in
    if "portfolio" in page.url.lower() or "summary" in page.url.lower():
        print("[Login] Already logged in!")
        return True

    # Check if on login page
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
    if "authenticator" in page_text.lower() or "security code" in page_text.lower() or "notification" in page_text.lower():
        print("[Login] 2FA detected - waiting 60s for manual completion...")
        page.wait_for_timeout(60000)

    current_url = page.url
    if "login" in current_url.lower():
        print("[Login] FAILED - still on login page")
        return False

    print("[Login] SUCCESS!")
    return True


def extract_balances(page):
    """Navigate to portfolio and extract account balances."""
    print("\n[Balances] Navigating to portfolio summary...")
    page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)  # Let the page load account data

    page.screenshot(path="portfolio_summary.png")
    print("[Balances] Screenshot saved: portfolio_summary.png")

    print(f"[Balances] Current URL: {page.url}")
    print(f"[Balances] Page title: {page.title()}")

    # Get the full page text for analysis
    body_text = page.locator("body").text_content() or ""

    # Look for account sections - Fidelity typically shows accounts in a list
    print("\n[Balances] Analyzing page structure...")

    # Try to find account containers/rows
    # Common patterns: account cards, table rows, list items with balances

    # First, let's see what elements might contain account info
    potential_selectors = [
        '[data-testid*="account"]',
        '[class*="account"]',
        '[class*="Account"]',
        '[class*="balance"]',
        '[class*="Balance"]',
        '[class*="portfolio"]',
        '.account-row',
        '.account-card',
        'table tr',
    ]

    for selector in potential_selectors:
        try:
            elements = page.locator(selector).all()
            if elements and len(elements) > 0 and len(elements) < 50:
                print(f"\n  Found {len(elements)} elements matching '{selector}'")
                for i, el in enumerate(elements[:10]):
                    text = (el.text_content() or "").strip()
                    if text and len(text) > 10:
                        # Truncate long text
                        display_text = text[:200].replace('\n', ' ')
                        print(f"    [{i}] {display_text}...")
        except Exception as e:
            pass

    # Extract all dollar amounts with context
    print("\n[Balances] Looking for dollar amounts...")

    # Find elements that contain dollar amounts
    all_text_elements = page.locator("body *").all()

    amounts_found = []
    for el in all_text_elements:
        try:
            text = el.text_content() or ""
            # Look for dollar amounts
            if "$" in text and len(text) < 500:
                matches = re.findall(r'\$[\d,]+\.?\d*', text)
                for match in matches:
                    # Get a clean version of the amount
                    amount_str = match.replace('$', '').replace(',', '')
                    try:
                        amount = float(amount_str)
                        if amount > 1000:  # Filter small amounts
                            # Try to get context (parent text or nearby text)
                            parent_text = ""
                            try:
                                parent = el.locator("..").first
                                parent_text = (parent.text_content() or "")[:100]
                            except:
                                pass

                            if match not in [a[0] for a in amounts_found]:
                                amounts_found.append((match, amount, text[:100].strip()))
                    except:
                        pass
        except:
            pass

    # Sort by amount descending and show top ones
    amounts_found.sort(key=lambda x: x[1], reverse=True)

    print(f"\n[Balances] Found {len(amounts_found)} significant dollar amounts:")
    for match, amount, context in amounts_found[:15]:
        context_clean = context.replace('\n', ' ').strip()
        print(f"  {match:>15} | {context_clean[:60]}...")

    # Also dump the raw page text for manual analysis
    print("\n[Balances] Saving raw page content for analysis...")
    with open("portfolio_raw.txt", "w") as f:
        f.write(body_text)
    print("[Balances] Raw content saved to: portfolio_raw.txt")

    return amounts_found


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
                balances = extract_balances(page)

                print("\n" + "="*50)
                print("Browser will stay open for 60 seconds for inspection")
                print("="*50)
                page.wait_for_timeout(60000)
            else:
                print("\nLogin failed. Check screenshots for details.")
                page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nError: {e}")
            page.screenshot(path="error.png")
            page.wait_for_timeout(30000)
        finally:
            context.close()


if __name__ == "__main__":
    main()
