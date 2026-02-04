#!/usr/bin/env python3
"""Debug positions page content."""

import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME")
FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD")
BROWSER_STATE_PATH = os.getenv("BROWSER_STATE_PATH", "./session_state")
LOGIN_URL = "https://digital.fidelity.com/prgw/digital/login/full-page"
POSITIONS_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/positions"

state_path = Path(BROWSER_STATE_PATH)

with sync_playwright() as p:
    context = p.firefox.launch_persistent_context(
        user_data_dir=str(state_path / "firefox_data"),
        headless=False,
        viewport={"width": 1400, "height": 1200},
    )

    page = context.new_page()

    # Login
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    if "login" in page.url.lower():
        page.locator('#dom-username-input').type(FIDELITY_USERNAME, delay=30)
        page.locator('#dom-pswd-input').type(FIDELITY_PASSWORD, delay=30)
        page.locator('#dom-pswd-input').press("Enter")
        page.wait_for_timeout(5000)

    # Navigate to positions
    page.goto(POSITIONS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Scroll
    for _ in range(3):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(1000)

    # Get inner text (cleaner than text_content)
    inner_text = page.locator("body").inner_text()

    # Save to file
    with open("positions_inner_text.txt", "w") as f:
        f.write(inner_text)
    print(f"Saved {len(inner_text)} chars to positions_inner_text.txt")

    # Show sample of lines
    lines = inner_text.split('\n')
    print(f"\nTotal lines: {len(lines)}")
    print("\nFirst 100 non-empty lines:")
    count = 0
    for i, line in enumerate(lines):
        if line.strip():
            print(f"{i:4}: {line[:80]}")
            count += 1
            if count >= 100:
                break

    page.wait_for_timeout(30000)
    context.close()
