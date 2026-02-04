#!/usr/bin/env python3
"""
Fill credentials and pause for manual inspection.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
FIDELITY_URL = os.getenv("FIDELITY_URL", "digital.fidelity.com/prgw/digital/login/full-page")
LOGIN_URL = f"https://{FIDELITY_URL}" if not FIDELITY_URL.startswith("http") else FIDELITY_URL

def main():
    print(f"Username: {FIDELITY_USERNAME}")
    print(f"Password: {'*' * len(FIDELITY_PASSWORD)} ({len(FIDELITY_PASSWORD)} chars)")
    print(f"URL: {LOGIN_URL}")

    state_path = Path(BROWSER_STATE_PATH)
    state_path.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(state_path / "browser_data"),
            headless=False,
            slow_mo=100,
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()

        print("\n[1] Navigating to login page...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        print("[2] Filling username...")
        username_field = page.locator('#dom-username-input')
        username_field.click()
        page.wait_for_timeout(200)
        username_field.type(FIDELITY_USERNAME, delay=50)
        page.wait_for_timeout(500)

        print("[3] Filling password...")
        password_field = page.locator('#dom-pswd-input')
        password_field.click()
        page.wait_for_timeout(200)
        password_field.type(FIDELITY_PASSWORD, delay=50)

        print("\n" + "="*50)
        print("PAUSED - Please check the browser window")
        print("Verify the username and password are correct")
        print("="*50)
        print("\nWaiting 30 seconds for you to verify...")
        print("The form will NOT be submitted - just verify credentials look correct")

        page.screenshot(path="credentials_filled.png")
        print("Screenshot saved: credentials_filled.png")

        page.wait_for_timeout(30000)  # 30 second pause

        print("\n--- PAUSED COMPLETE ---")
        print("NOT submitting - just showing you what was filled")
        print("Browser will stay open for 60 more seconds for inspection...")
        page.wait_for_timeout(60000)
        context.close()
        return  # Don't proceed with login

        print("\n[4] Pressing Enter to submit...")
        password_field.press("Enter")

        print("[5] Waiting for result...")
        page.wait_for_timeout(10000)

        current_url = page.url
        print(f"\nCurrent URL: {current_url}")

        if "login" not in current_url.lower():
            print("\n✅ Appears to have navigated away from login page!")
        else:
            print("\n❌ Still on login page")

        page.screenshot(path="result.png")
        print("Screenshot saved: result.png")

        print("\nBrowser staying open for 60 seconds...")
        page.wait_for_timeout(60000)
        context.close()

if __name__ == "__main__":
    main()
