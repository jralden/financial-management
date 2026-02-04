#!/usr/bin/env python3
"""
Fidelity Login Test Script

This script tests automated login to Fidelity.com to validate:
1. Can we authenticate programmatically?
2. Does the "recognized device" bypass 2FA?
3. Can we extract account balances?

Run with: python -m src.fidelity.login_test
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Load environment variables
load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")

# Fidelity URLs - use env var or default
FIDELITY_URL = os.getenv("FIDELITY_URL", "digital.fidelity.com/prgw/digital/login/full-page")
LOGIN_URL = f"https://{FIDELITY_URL}" if not FIDELITY_URL.startswith("http") else FIDELITY_URL
PORTFOLIO_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"


def check_credentials():
    """Verify credentials are configured."""
    if not FIDELITY_USERNAME or not FIDELITY_PASSWORD:
        print("ERROR: Missing credentials!")
        print("Please create a .env file with:")
        print("  FIDELITY_USERNAME=your_username")
        print("  FIDELITY_PASSWORD=your_password")
        sys.exit(1)
    print(f"Using username: {FIDELITY_USERNAME}")
    print(f"Login URL: {LOGIN_URL}")


def test_login():
    """Test Fidelity login and extract account information."""
    check_credentials()

    state_path = Path(BROWSER_STATE_PATH)
    state_path.mkdir(exist_ok=True)

    with sync_playwright() as p:
        # Use persistent context to maintain session/cookies
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(state_path / "browser_data"),
            headless=False,  # Visible browser for debugging
            slow_mo=200,     # Slow down actions for visibility
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()

        try:
            # Step 1: Navigate to login page
            print("\n[1/6] Navigating to Fidelity login page...")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)  # Let page fully render

            # Take screenshot of login page
            page.screenshot(path="01_login_page.png")
            print("Screenshot saved: 01_login_page.png")

            # Check if we're already logged in (session persisted)
            current_url = page.url
            if "portfolio" in current_url.lower() or "summary" in current_url.lower():
                print("Already logged in! Session was persisted.")
                extract_balances(page)
                return

            # Step 2: Analyze the page structure
            print("\n[2/6] Analyzing page structure...")

            # Find all input fields
            inputs = page.locator("input").all()
            print(f"Found {len(inputs)} input fields:")
            for inp in inputs:
                inp_id = inp.get_attribute("id") or ""
                inp_name = inp.get_attribute("name") or ""
                inp_type = inp.get_attribute("type") or ""
                inp_placeholder = inp.get_attribute("placeholder") or ""
                if inp_id or inp_name:
                    print(f"  - id='{inp_id}' name='{inp_name}' type='{inp_type}' placeholder='{inp_placeholder}'")

            # Find all buttons
            buttons = page.locator("button").all()
            print(f"\nFound {len(buttons)} buttons:")
            for btn in buttons:
                btn_id = btn.get_attribute("id") or ""
                btn_text = btn.text_content() or ""
                btn_type = btn.get_attribute("type") or ""
                print(f"  - id='{btn_id}' type='{btn_type}' text='{btn_text.strip()[:50]}'")

            # Step 3: Enter username
            print("\n[3/6] Entering username...")
            # Try multiple possible selectors
            username_selectors = [
                '#dom-username-input',
                '#userId',
                'input[name="username"]',
                'input[type="text"]',
                'input[autocomplete="username"]',
            ]

            username_field = None
            for selector in username_selectors:
                try:
                    field = page.locator(selector).first
                    if field.is_visible():
                        username_field = field
                        print(f"  Found username field with: {selector}")
                        break
                except:
                    continue

            if not username_field:
                print("  ERROR: Could not find username field!")
                page.screenshot(path="error_no_username.png")
                return

            # Use human-like typing instead of fill()
            username_field.click()
            page.wait_for_timeout(300)
            # Clear any existing content first
            username_field.press("Control+a")
            page.wait_for_timeout(100)
            # Type character by character with small delays
            username_field.type(FIDELITY_USERNAME, delay=50)
            page.wait_for_timeout(500)

            # Step 4: Enter password
            print("[4/6] Entering password...")
            password_selectors = [
                '#dom-pswd-input',
                '#password',
                'input[name="password"]',
                'input[type="password"]',
            ]

            password_field = None
            for selector in password_selectors:
                try:
                    field = page.locator(selector).first
                    if field.is_visible():
                        password_field = field
                        print(f"  Found password field with: {selector}")
                        break
                except:
                    continue

            if not password_field:
                print("  ERROR: Could not find password field!")
                page.screenshot(path="error_no_password.png")
                return

            # Use human-like typing
            password_field.click()
            page.wait_for_timeout(300)
            password_field.type(FIDELITY_PASSWORD, delay=50)
            page.wait_for_timeout(500)

            # Screenshot before clicking login
            page.screenshot(path="02_before_login.png")
            print("Screenshot saved: 02_before_login.png")

            # Step 5: Submit login (try pressing Enter instead of clicking)
            print("[5/6] Submitting login form...")
            # Press Enter to submit (more reliable than clicking)
            password_field.press("Enter")

            # Step 6: Wait for result
            print("[6/6] Waiting for login result...")
            page.wait_for_timeout(8000)  # Wait for redirect/2FA

            # Screenshot after login attempt
            page.screenshot(path="03_after_login.png")
            print("Screenshot saved: 03_after_login.png")

            # Check what happened
            current_url = page.url
            print(f"\nCurrent URL: {current_url}")

            # Check for error messages on the page
            error_selectors = [
                '.error-message',
                '.alert-error',
                '[role="alert"]',
                '.pvd-alert',
                '.error',
                '#dom-login-error',
            ]

            for selector in error_selectors:
                try:
                    error_el = page.locator(selector).first
                    if error_el.is_visible():
                        print(f"\n⚠️  Error message found: {error_el.text_content().strip()}")
                except:
                    continue

            # Check for 2FA challenge - also check page content, not just URL
            page_text = page.locator("body").text_content() or ""
            is_2fa_page = (
                "security" in current_url.lower() or
                "verify" in current_url.lower() or
                "authentication" in current_url.lower() or
                "authenticator app" in page_text.lower() or
                "security code" in page_text.lower()
            )

            if is_2fa_page:
                print("\n⚠️  2FA CHALLENGE DETECTED!")
                print("="*50)
                print("Please complete these steps in the browser window:")
                print("  1. Enter your authenticator code")
                print("  2. CHECK 'Don't ask me again on this device'")
                print("  3. Click Continue")
                print("="*50)
                print("\nYou have 3 MINUTES to complete 2FA...")
                page.screenshot(path="04_2fa_challenge.png")
                page.wait_for_timeout(180000)  # 3 minutes for 2FA
                current_url = page.url
                page.screenshot(path="05_after_2fa.png")
                print("Screenshot saved: 05_after_2fa.png")

            # Check for successful login
            if "portfolio" in current_url.lower() or "summary" in current_url.lower() or "accounts" in current_url.lower():
                print("\n✅ LOGIN SUCCESSFUL!")
                page.screenshot(path="05_success.png")
                extract_balances(page)
            elif "login" in current_url.lower():
                print("\n❌ LOGIN FAILED - Still on login page")
                print("Check the screenshots and error messages above.")
            else:
                print(f"\n❓ UNKNOWN STATE - URL: {current_url}")
                print("Check 03_after_login.png for details.")

            # Keep browser open for inspection
            print("\nBrowser will stay open for 30 seconds for inspection...")
            print("Press Ctrl+C to close earlier.")
            page.wait_for_timeout(30000)

        except PlaywrightTimeout as e:
            print(f"\n❌ TIMEOUT: {e}")
            page.screenshot(path="error_timeout.png")
        except KeyboardInterrupt:
            print("\nClosing browser...")
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            page.screenshot(path="error_exception.png")
        finally:
            context.close()


def extract_balances(page):
    """Attempt to extract account balances from the portfolio page."""
    try:
        print("\n--- Extracting Account Data ---")
        page.wait_for_timeout(3000)

        # Take a screenshot
        page.screenshot(path="portfolio_page.png")
        print("Screenshot saved: portfolio_page.png")

        print(f"Page title: {page.title()}")

        # Dump the visible text on the page for analysis
        body_text = page.locator("body").text_content()

        # Look for dollar amounts (simplified pattern)
        import re
        amounts = re.findall(r'\$[\d,]+\.?\d*', body_text or "")
        if amounts:
            print(f"\nFound {len(amounts)} dollar amounts on page:")
            for amt in amounts[:20]:  # Show first 20
                print(f"  {amt}")

    except Exception as e:
        print(f"Error extracting balances: {e}")


if __name__ == "__main__":
    test_login()
