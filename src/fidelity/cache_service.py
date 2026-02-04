#!/usr/bin/env python3
"""
Fidelity Balance Cache Service

Fetches account balances and caches them for instant dashboard access.
Designed to run as a scheduled background job via launchd.

Usage:
    python -m src.fidelity.cache_service           # Fetch and cache once
    python -m src.fidelity.cache_service --status  # Show cache status
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.fidelity.fetch_balances import fetch_balances

# Cache location - use a standard location for easy access
CACHE_DIR = Path.home() / ".cache" / "financial-management"
CACHE_FILE = CACHE_DIR / "fidelity_balances.json"
LOG_FILE = CACHE_DIR / "fetch.log"

# Market hours (Eastern Time)
MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR = 9   # 9:00 AM ET
MARKET_CLOSE_HOUR = 17  # 5:00 PM ET
MARKET_DAYS = {0, 1, 2, 3, 4}  # Monday=0 through Friday=4


def is_market_hours() -> bool:
    """Check if current time is within market hours (weekdays 9am-5pm ET)."""
    now_et = datetime.now(MARKET_TZ)

    # Check weekday (Monday=0 through Friday=4)
    if now_et.weekday() not in MARKET_DAYS:
        return False

    # Check hour (9:00 AM to 5:00 PM)
    if now_et.hour < MARKET_OPEN_HOUR or now_et.hour >= MARKET_CLOSE_HOUR:
        return False

    return True


def get_market_status() -> str:
    """Get human-readable market status."""
    now_et = datetime.now(MARKET_TZ)
    day_name = now_et.strftime("%A")
    time_str = now_et.strftime("%I:%M %p ET")

    if is_market_hours():
        return f"OPEN ({day_name} {time_str})"
    else:
        return f"CLOSED ({day_name} {time_str})"


def log(message: str):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)

    # Also append to log file
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"Warning: Could not write to log: {e}", file=sys.stderr)


def fetch_and_cache(force: bool = False) -> bool:
    """Fetch balances and save to cache. Returns True on success.

    Args:
        force: If True, fetch even outside market hours
    """
    # Check market hours unless forced
    if not force and not is_market_hours():
        log(f"Skipping fetch - market {get_market_status()}")
        return True  # Return True since this isn't a failure

    log(f"Starting balance fetch (market {get_market_status()})...")

    try:
        summary = fetch_balances(headless=True)

        if not summary:
            log("ERROR: Fetch returned no data")
            return False

        if not summary.accounts:
            log("ERROR: No accounts found")
            return False

        # Ensure cache directory exists
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Convert to dict for JSON serialization
        from dataclasses import asdict
        data = asdict(summary)

        # Add cache metadata
        data["cached_at"] = datetime.now().isoformat()
        data["cache_version"] = 1

        # Write atomically (write to temp, then rename)
        temp_file = CACHE_FILE.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        temp_file.rename(CACHE_FILE)

        log(f"SUCCESS: Cached {len(summary.accounts)} accounts, total ${summary.total_balance:,.2f}")
        log(f"Fetch time: {summary.fetch_time_seconds:.2f}s")

        # Sync to Railway if DATABASE_URL is set
        try:
            if os.environ.get("DATABASE_URL"):
                from src.database.sync import sync_all
                log("Syncing to Railway database...")
                sync_all()
                log("Railway sync complete")
        except Exception as e:
            log(f"WARNING: Railway sync failed: {e}")
            # Don't fail the whole operation if sync fails

        return True

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_status():
    """Show current cache status."""
    print(f"Cache file: {CACHE_FILE}")
    print(f"Log file: {LOG_FILE}")
    print(f"Market: {get_market_status()}")
    print()

    if not CACHE_FILE.exists():
        print("Status: NO CACHE - run fetch first")
        return

    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)

        cached_at = data.get("cached_at", "unknown")
        total = data.get("total_balance", 0)
        change = data.get("total_daily_change", 0)
        accounts = data.get("accounts", [])
        fetch_time = data.get("fetch_time_seconds", 0)

        # Calculate age
        try:
            cached_dt = datetime.fromisoformat(cached_at)
            age_seconds = (datetime.now() - cached_dt).total_seconds()
            if age_seconds < 60:
                age_str = f"{age_seconds:.0f} seconds ago"
            elif age_seconds < 3600:
                age_str = f"{age_seconds/60:.0f} minutes ago"
            else:
                age_str = f"{age_seconds/3600:.1f} hours ago"
        except:
            age_str = "unknown"

        print(f"Status: CACHED")
        print(f"Last fetch: {cached_at} ({age_str})")
        print(f"Fetch duration: {fetch_time:.2f}s")
        print()
        print(f"Total Balance: ${total:,.2f} ({change:+,.2f} today)")
        print(f"Accounts: {len(accounts)}")
        for acc in accounts:
            print(f"  - {acc['name']}: ${acc['balance']:,.2f}")

    except Exception as e:
        print(f"Status: ERROR reading cache - {e}")


def read_cache() -> dict | None:
    """Read cached data. Returns None if no cache or error."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except:
        return None


def main():
    if "--status" in sys.argv:
        show_status()
    elif "--help" in sys.argv:
        print(__doc__)
        print(f"\nCache location: {CACHE_FILE}")
        print(f"\nOptions:")
        print(f"  --status  Show cache status")
        print(f"  --force   Fetch even outside market hours")
        print(f"\nMarket hours: Weekdays {MARKET_OPEN_HOUR}:00 AM - {MARKET_CLOSE_HOUR % 12}:00 PM ET")
    else:
        force = "--force" in sys.argv
        success = fetch_and_cache(force=force)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
